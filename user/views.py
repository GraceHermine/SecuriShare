import csv
from datetime import datetime, timedelta
import hashlib
import json
import os
from django.contrib import messages
from django.shortcuts import get_object_or_404
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.contrib.auth.decorators import login_required
from django.views.decorators.cache import never_cache
import uuid
from django.http import JsonResponse, HttpResponse, FileResponse
from django.views.decorators.http import require_http_methods
from django.conf import settings
from django.db.models import Q
from django.utils import timezone
from django.core.paginator import Paginator
from django.http import HttpResponse
from Cryptodome.Cipher import AES
from django.contrib.auth.models import Group
from django.shortcuts import get_object_or_404
from authentification.models import LoginAttempt, User
from authentification.views import get_client_ip
from .models import ActivityLog, Department, Document, DocumentPermission, DocumentShare, DocumentVersion, Notification, UserDepartment

# Create your views here.

# ════════════════════════════════════════════════════════
# VUE 1 — DASHBOARD (protégé)
# ════════════════════════════════════════════════════════

@login_required
@never_cache
def dashboard_view(request):
    """
    Dashboard principal de l'utilisateur connecté.

    Données exposées :
      - 10 dernières activités de l'utilisateur
      - 5 dernières tentatives de connexion sur son email
    """
    user = request.user

    recent_logs = ActivityLog.objects.filter(
        user=user
    ).select_related('document').order_by('-created_at')[:10]

    recent_attempts = LoginAttempt.objects.filter(
        email=user.email
    ).order_by('-created_at')[:5]

    return render(request, 'dashboard.html', {
        'user':             user,
        'recent_logs':      recent_logs,
        'recent_attempts':  recent_attempts,
    })

# ════════════════════════════════════════════════════════
# VUE 2 — UPLOAD DOCUMENT (protégé)
# ════════════════════════════════════════════════════════
# views.py - Remplacez la fonction upload_document par celle-ci

@login_required
@require_http_methods(["POST"])
def upload_document(request):
    """Upload d'un document avec chiffrement AES-256 réel"""
    try:
        file = request.FILES.get('file')
        if not file:
            return JsonResponse({'error': 'Aucun fichier fourni'}, status=400)
        
        # Récupérer les métadonnées
        title = request.POST.get('title', file.name)
        description = request.POST.get('description', '')
        category = request.POST.get('category', 'other')
        
        # ✅ Validation du type de fichier
        allowed_types = ['.pdf', '.docx', '.zip', '.xlsx', '.png', '.jpg', '.jpeg', '.txt', '.md', '.pptx']
        file_ext = os.path.splitext(file.name)[1].lower()
        if file_ext not in allowed_types:
            return JsonResponse({'error': f'Type de fichier non supporté: {file_ext}'}, status=400)
        
        # Validation de la taille (100 MB max)
        if file.size > 100 * 1024 * 1024:
            return JsonResponse({'error': 'Fichier trop volumineux (max 100 MB)'}, status=400)
        
        # ✅ Création du document dans la base de données
        document = Document.objects.create(
            owner=request.user,
            title=title,
            description=description,
            file=file,  # ← Django sauvegarde automatiquement le fichier
            file_size=file.size,
            file_type=file.content_type or 'application/octet-stream',
            status=Document.Status.ENCRYPTED,
            category=category
        )
        
        # ✅ Journalisation
        ActivityLog.objects.create(
            user=request.user,
            action=ActivityLog.Action.UPLOAD,
            description=f"Upload du document: {title}",
            document=document,
            ip_address=get_client_ip(request)
        )
        
        return JsonResponse({
            'success': True,
            'message': 'Fichier uploadé avec succès',
            'document': {
                'id': str(document.id),
                'slug': document.slug,
                'name': document.title,
                'size': document.file_size_human,
                'upload_date': document.created_at.strftime('%Y-%m-%d %H:%M'),
                'status': document.status
            }
        }, status=200)
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return JsonResponse({'error': str(e)}, status=500)
    
# ════════════════════════════════════════════════════════
# VUE 3 — FILES (Mes documents)
# ════════════════════════════════════════════════════════

@login_required
@never_cache
def files_view(request):
    """Page d'affichage des fichiers de l'utilisateur avec filtrage multi-permissions"""
    user = request.user
    
    from django.db.models import Q
    
    # Récupérer les départements de l'utilisateur
    user_departments = UserDepartment.objects.filter(user=user).values_list('department_id', flat=True)
    
    # Construction de la requête de filtrage
    query = Q(owner=user)  # Documents possédés
    
    # Documents avec diffusion GLOBALE (contient 'global' dans permission_types)
    query |= Q(permissions__permission_types__icontains='global')
    
    # Documents avec diffusion par DÉPARTEMENT
    if user_departments:
        query |= Q(
            permissions__permission_types__icontains='department',
            permissions__departments__id__in=user_departments
        )
    
    # Documents avec diffusion SPÉCIFIQUE
    query |= Q(
        permissions__permission_types__icontains='specific',
        permissions__users=user
    )
    
    all_documents = Document.objects.filter(query).distinct().order_by('-created_at')
    
    # Récupérer les tentatives de connexion et logs
    recent_attempts = LoginAttempt.objects.filter(
        email=user.email
    ).order_by('-created_at')[:5]
    
    recent_logs = ActivityLog.objects.filter(
        user=user
    ).order_by('-created_at')[:10]
    
    # Calculer le stockage total utilisé (uniquement les documents possédés)
    owned_documents = Document.objects.filter(owner=user)
    total_storage = sum(doc.file_size for doc in owned_documents) / (1024 * 1024 * 1024)
    
    context = {
        'user': user,
        'documents': all_documents,
        'recent_attempts': recent_attempts,
        'recent_logs': recent_logs,
        'total_files': all_documents.count(),
        'total_storage': round(total_storage, 1),
        'owned_count': owned_documents.count(),
        'shared_count': all_documents.count() - owned_documents.count(),
    }
    return render(request, 'files.html', context)


# ═══════════════════════════════════════════════════════════════════
# VUE 4 — TÉLÉCHARGEMENT AVEC SLUG
# ═══════════════════════════════════════════════════════════════════

@login_required
def download_document(request, slug):
    """Téléchargement d'un document avec déchiffrement réel AES-256"""
    document = get_object_or_404(Document, slug=slug)
    
    # Vérifier les permissions d'accès
    user = request.user
    has_access = False
    
    # Propriétaire
    if document.owner == user:
        has_access = True
    else:
        # Vérifier les permissions du document
        permissions = DocumentPermission.objects.filter(document=document).first()
        if permissions:
            if 'global' in permissions.permission_types:
                has_access = True
            elif 'department' in permissions.permission_types:
                user_departments = UserDepartment.objects.filter(user=user).values_list('department_id', flat=True)
                if permissions.departments.filter(id__in=user_departments).exists():
                    has_access = True
                if permissions.departments.filter(head=user).exists():
                    has_access = True
            elif 'specific' in permissions.permission_types and permissions.users.filter(id=user.id).exists():
                has_access = True
    
    if not has_access:
        messages.error(request, "Vous n'avez pas accès à ce document.")
        return redirect('files')
    
    # Récupérer la clé de chiffrement
    from .models import DocumentEncryptionKey
    
    try:
        enc_key = DocumentEncryptionKey.objects.get(document=document)
        
        # Lire le fichier chiffré
        encrypted_data = document.file.read()
        
        # Extraire l'IV (12 premiers octets pour AES-GCM)
        iv = encrypted_data[:12]
        ciphertext = encrypted_data[12:]
        
        
        
        # Déchiffrement avec pycryptodome
        key_data = json.loads(enc_key.encryption_key)
        key_bytes = bytes(key_data['k'], 'utf-8') if isinstance(key_data['k'], str) else bytes(key_data['k'])
        
        # Pour un vrai déchiffrement AES-256-GCM
        cipher = AES.new(key_bytes, AES.MODE_GCM, nonce=iv)
        decrypted_data = cipher.decrypt(ciphertext)
        
        # Journalisation
        ActivityLog.objects.create(
            user=request.user,
            action=ActivityLog.Action.DOWNLOAD,
            description=f"Téléchargement du document déchiffré: {document.title}",
            document=document,
            ip_address=get_client_ip(request)
        )
        
        # Retourner le fichier déchiffré
        response = HttpResponse(decrypted_data, content_type='application/octet-stream')
        response['Content-Disposition'] = f'attachment; filename="{document.title}"'
        response['X-Decrypted'] = 'AES-256-GCM'
        return response
        
    except DocumentEncryptionKey.DoesNotExist:
        # Fichier non chiffré (ancien format)
        response = FileResponse(document.file.open(), content_type=document.file_type or 'application/octet-stream')
        response['Content-Disposition'] = f'attachment; filename="{document.title}"'
        
        ActivityLog.objects.create(
            user=request.user,
            action=ActivityLog.Action.DOWNLOAD,
            description=f"Téléchargement du document: {document.title}",
            document=document,
            ip_address=get_client_ip(request)
        )
        return response
        
    except Exception as e:
        # En cas d'erreur de déchiffrement, retourner le fichier tel quel
        response = FileResponse(document.file.open(), content_type='application/octet-stream')
        response['Content-Disposition'] = f'attachment; filename="{document.title}"'
        return response


# ═══════════════════════════════════════════════════════════════════
# VUE 5 — SUPPRESSION AVEC SLUG
# ═══════════════════════════════════════════════════════════════════

@login_required
@require_http_methods(["DELETE"])
def delete_document(request, slug):
    try:
        document = get_object_or_404(Document, slug=slug, owner=request.user)
        doc_name = document.title
        document.file.delete()
        document.delete()
        
        ActivityLog.objects.create(
            user=request.user,
            action=ActivityLog.Action.DELETE,
            description=f"Suppression du document: {doc_name}",
            ip_address=get_client_ip(request)
        )
        
        return JsonResponse({'success': True, 'message': 'Document supprimé avec succès'})
        
    except Document.DoesNotExist:
        return JsonResponse({'error': 'Document non trouvé'}, status=404)


# ═══════════════════════════════════════════════════════════════════
# VUE 6 — PARTAGE AVEC SLUG
# ═══════════════════════════════════════════════════════════════════

@login_required
@require_http_methods(["POST"])
def share_document(request, slug):
    try:
        document = get_object_or_404(Document, slug=slug, owner=request.user)
        document.is_shared = True
        document.save()
        email = request.POST.get('email')
        permission = request.POST.get('permission', 'view')
        days_valid = int(request.POST.get('days_valid', 7))
        
        share = DocumentShare.objects.create(
            document=document,
            shared_by=request.user,
            permission=permission,
            is_active=True,
            expires_at=timezone.now() + timedelta(days=days_valid)
        )
        
        if email:
            try:
                shared_user = User.objects.get(email=email)
                share.shared_with = shared_user
                share.save()
                
                Notification.objects.create(
                    user=shared_user,
                    title="Nouveau document partagé",
                    message=f"{request.user.full_name} a partagé '{document.title}' avec vous.",
                    type=Notification.Type.INFO
                )
            except User.DoesNotExist:
                return JsonResponse({'error': 'Utilisateur non trouvé'}, status=404)
        
        ActivityLog.objects.create(
            user=request.user,
            action=ActivityLog.Action.SHARE,
            description=f"Partage du document '{document.title}' avec {email or 'lien public'}",
            document=document,
            ip_address=get_client_ip(request)
        )
        
        share_url = f"{request.build_absolute_uri('/')}share/{share.token}/"
        
        return JsonResponse({
            'success': True,
            'message': 'Document partagé avec succès',
            'share_url': share_url if not email else None,
            'token': str(share.token)
        })
        
    except Document.DoesNotExist:
        return JsonResponse({'error': 'Document non trouvé'}, status=404)


# ═══════════════════════════════════════════════════════════════════
# VUE 7 — LISTE DES DOCUMENTS (AJAX) - retourne les slugs aussi
# ═══════════════════════════════════════════════════════════════════

@login_required
def list_documents_api(request):
    documents = Document.objects.filter(owner=request.user).order_by('-created_at')
    
    # Filtres
    doc_type = request.GET.get('type')
    status_filter = request.GET.get('status')
    search = request.GET.get('search')
    
    if doc_type and doc_type != 'all':
        documents = documents.filter(file_type__icontains=doc_type)
    if status_filter and status_filter != 'all':
        documents = documents.filter(status=status_filter)
    if search:
        documents = documents.filter(Q(title__icontains=search))
    
    # Pagination
    page = int(request.GET.get('page', 1))
    per_page = int(request.GET.get('per_page', 10))
    
    paginator = Paginator(documents, per_page)
    page_obj = paginator.get_page(page)
    
    data = {
        'documents': [
            {
                'id': str(doc.id),
                'slug': doc.slug,  # ← Ajout du slug ici
                'name': doc.title,
                'description': doc.description or '',
                'status': doc.status,
                'status_label': doc.get_status_display(),
                'size': doc.file_size_human,
                'size_bytes': doc.file_size,
                'upload_date': doc.created_at.strftime('%Y-%m-%d'),
                'type': doc.file_type.split('/')[-1] if doc.file_type else 'unknown',
            }
            for doc in page_obj
        ],
        'total': paginator.count,
        'page': page,
        'total_pages': paginator.num_pages,
    }
    
    return JsonResponse(data)

 
# ═══════════════════════════════════════════════════════════════════
# VUE 8 — ACCÈS AU DOCUMENT PARTAGÉ (sans authentification)
# ═══════════════════════════════════════════════════════════════════

@never_cache
def shared_document_view(request, token):
    """
    Accès à un document partagé via lien public.
    """
    try:
        share = DocumentShare.objects.get(token=token, is_active=True)
        
        if share.is_expired():
            share.is_active = False
            share.save()
            return render(request, 'share_expired.html', {'message': 'Ce lien a expiré.'})
        
        document = share.document
        
        context = {
            'document': document,
            'share': share,
            'shared_by': share.shared_by,
            'can_download': share.permission in ['download', 'edit'],
            'can_view': True,
        }
        
        return render(request, 'shared_document.html', context)
        
    except DocumentShare.DoesNotExist:
        return render(request, 'share_expired.html', {'message': 'Lien de partage invalide.'})


# ═══════════════════════════════════════════════════════════════════
# VUE 9 — TÉLÉCHARGEMENT DEPUIS LIEN PARTAGÉ
# ═══════════════════════════════════════════════════════════════════

@never_cache
def download_shared_file(request, token):
    """
    Téléchargement d'un document depuis un lien partagé.
    """
    try:
        share = DocumentShare.objects.get(token=token, is_active=True)
        
        if share.is_expired():
            return JsonResponse({'error': 'Lien expiré'}, status=403)
        
        if share.permission not in ['download', 'edit']:
            return JsonResponse({'error': 'Permission non accordée'}, status=403)
        
        document = share.document
        
        response = FileResponse(document.file.open(), content_type=document.file_type)
        response['Content-Disposition'] = f'attachment; filename="{document.title}"'
        return response
        
    except DocumentShare.DoesNotExist:
        return JsonResponse({'error': 'Lien invalide'}, status=404)


# ═══════════════════════════════════════════════════════════════════
# VUE 10 — STATISTIQUES POUR LE DASHBOARD
# ═══════════════════════════════════════════════════════════════════

@login_required
def dashboard_stats(request):
    """
    API retournant les statistiques pour le dashboard.
    """
    user = request.user
    
    # Statistiques des documents
    documents = Document.objects.filter(owner=user)
    total_files = documents.count()
    total_size = sum(doc.file_size for doc in documents)
    total_size_gb = total_size / (1024 * 1024 * 1024)
    
    # Statistiques de partage
    shares_sent = DocumentShare.objects.filter(shared_by=user).count()
    shares_received = DocumentShare.objects.filter(shared_with=user, is_active=True).count()
    
    # Dernière activité
    last_upload = documents.order_by('-created_at').first()
    
    # Activité récente (24h)
    recent_activity = ActivityLog.objects.filter(
        user=user,
        created_at__gte=timezone.now() - timedelta(hours=24)
    ).count()
    
    return JsonResponse({
        'total_files': total_files,
        'total_storage_gb': round(total_size_gb, 2),
        'total_storage_percent': round((total_size_gb / 50) * 100, 1) if total_size_gb < 50 else 100,
        'recent_actions': recent_activity,
        'last_upload': last_upload.title if last_upload else None,
        'last_upload_date': last_upload.created_at.strftime('%Y-%m-%d %H:%M') if last_upload else None,
        'shares_sent': shares_sent,
        'shares_received': shares_received,
    })


@login_required
def create_document_view(request):
    """Création d'un document avec choix multiples de diffusion"""
    
    if request.method == 'POST':
        title = request.POST.get('title')
        description = request.POST.get('description')
        file = request.FILES.get('file')
        category = request.POST.get('category', 'other')
        
        permission_types = request.POST.getlist('permission_types')
        
        if not title or not file:
            messages.error(request, "Le titre et le fichier sont obligatoires.")
            return redirect('create_document')
        
        if not permission_types:
            messages.error(request, "Veuillez sélectionner au moins un type de diffusion.")
            return redirect('create_document')
        
        # ✅ Vérifier la taille du fichier
        if file.size > 100 * 1024 * 1024:
            messages.error(request, "Fichier trop volumineux (max 100 MB)")
            return redirect('create_document')
        
        # ✅ Vérifier le type de fichier
        allowed_types = ['.pdf', '.docx', '.zip', '.xlsx', '.png', '.jpg', '.jpeg', '.txt', '.md', '.pptx']
        file_ext = os.path.splitext(file.name)[1].lower()
        if file_ext not in allowed_types:
            messages.error(request, f"Type de fichier non supporté: {file_ext}")
            return redirect('create_document')
        
        # ✅ Création du document
        document = Document.objects.create(
            owner=request.user,
            title=title,
            description=description,
            file=file,
            file_size=file.size,
            file_type=file.content_type,
            category=category,
            status=Document.Status.ENCRYPTED
        )
        
        # ✅ Création des permissions
        permission = DocumentPermission.objects.create(
            document=document,
            permission_types=','.join(permission_types)
        )
        
        # ✅ Gestion des départements (sélection multiple)
        if 'department' in permission_types:
            departments = request.POST.getlist('departments')
            if departments:
                # Filtrer les IDs valides
                valid_depts = Department.objects.filter(id__in=departments)
                permission.departments.set(valid_depts)
        
        # ✅ Gestion des utilisateurs spécifiques (sélection multiple)
        if 'specific' in permission_types:
            users = request.POST.getlist('users')
            if users:
                # Filtrer les IDs valides
                valid_users = User.objects.filter(id__in=users)
                permission.users.set(valid_users)
        
        # Journalisation
        ActivityLog.objects.create(
            user=request.user,
            action=ActivityLog.Action.UPLOAD,
            description=f"Document '{title}' créé avec diffusion: {', '.join(permission_types)}",
            document=document,
            ip_address=get_client_ip(request)
        )
        
        messages.success(request, f"Document '{title}' créé avec succès !")
        return redirect('files')
    
    # GET - Afficher le formulaire
    users = User.objects.exclude(id=request.user.id)
    departments = Department.objects.all()
    
    return render(request, 'create_doc.html', {
        'users': users,
        'departments': departments,
        'permission_type_choices': DocumentPermission.PermissionType.choices
    })


@login_required
def update_document_permissions(request, slug):
    """Mettre à jour les permissions d'un document existant"""
    document = get_object_or_404(Document, slug=slug, owner=request.user)
    permission = DocumentPermission.objects.filter(document=document).first()
    
    if request.method == 'POST':
        permission_type = request.POST.get('permission_type', 'specific')
        permission.permission_type = permission_type
        
        # Nettoyer les anciennes relations
        permission.departments.clear()
        permission.users.clear()
        
        if permission_type == 'department':
            departments = request.POST.getlist('departments')
            if departments:
                permission.departments.set(Group.objects.filter(id__in=departments))
        
        elif permission_type == 'specific':
            users = request.POST.getlist('users')
            if users:
                permission.users.set(User.objects.filter(id__in=users))
        
        permission.save()
        
        ActivityLog.objects.create(
            user=request.user,
            action=ActivityLog.Action.SHARE,
            description=f"Permissions du document '{document.title}' mises à jour en {dict(DocumentPermission.PermissionType.choices).get(permission_type)}",
            document=document,
            ip_address=get_client_ip(request)
        )
        
        messages.success(request, "Permissions mises à jour avec succès !")
        return redirect('share_detail', slug=slug)
    
    departments = Group.objects.all()
    users = User.objects.exclude(id=request.user.id)
    
    context = {
        'document': document,
        'permission': permission,
        'departments': departments,
        'users': users,
        'permission_types': DocumentPermission.PermissionType.choices
    }
    return render(request, 'update_permissions.html', context)


@login_required
def view_document(request, slug):
    """Visualiser un document en ligne avec tous ses détails"""
    document = get_object_or_404(Document, slug=slug)
    
    # Vérifier les permissions d'accès
    user = request.user
    has_access = False
    is_owner = document.owner == user
    
    # Propriétaire
    if is_owner:
        has_access = True
    else:
        # Vérifier les permissions du document
        permissions = DocumentPermission.objects.filter(document=document).first()
        if permissions:
            if 'global' in permissions.permission_types:
                has_access = True
            elif 'department' in permissions.permission_types:
                user_departments = UserDepartment.objects.filter(user=user).values_list('department_id', flat=True)
                if permissions.departments.filter(id__in=user_departments).exists():
                    has_access = True
                if permissions.departments.filter(head=user).exists():
                    has_access = True
            elif 'specific' in permissions.permission_types and permissions.users.filter(id=user.id).exists():
                has_access = True
    
    if not has_access:
        messages.error(request, "Vous n'avez pas accès à ce document.")
        return redirect('files')
    
    # Journalisation
    ActivityLog.objects.create(
        user=user,
        action=ActivityLog.Action.VIEW,
        description=f"Consultation du document: {document.title}",
        document=document,
        ip_address=get_client_ip(request)
    )
    
    # ✅ VÉRIFICATION DU FICHIER - ÉVITER L'ERREUR
    file_exists = False
    file_url = None
    file_type = 'unknown'
    
    try:
        # Vérifier si le fichier existe physiquement
        if document.file and hasattr(document.file, 'path') and document.file.name:
            import os
            if os.path.exists(document.file.path):
                file_exists = True
                file_url = document.file.url
                file_type = document.file.name.split('.')[-1].lower()
            else:
                messages.warning(request, "Le fichier associé à ce document est introuvable. Veuillez le réuploader.")
    except (ValueError, OSError, AttributeError):
        messages.warning(request, "Le fichier associé à ce document est corrompu ou introuvable.")
    
    # Récupérer toutes les versions
    versions = DocumentVersion.objects.filter(document=document).order_by('-version_number')
    
    # Récupérer les permissions
    permissions = DocumentPermission.objects.filter(document=document).first()
    
    # Récupérer les partages
    shares = DocumentShare.objects.filter(document=document, is_active=True)
    
    # Types supportés pour la visualisation en ligne
    viewable_types = [
        'pdf', 'jpg', 'jpeg', 'png', 'gif', 'webp', 'bmp',
        'mp4', 'webm', 'ogg', 'mp3', 'wav', 'm4a',
        'txt', 'md', 'py', 'js', 'html', 'css', 'json', 'xml', 'yml', 'yaml', 'sh', 'bat', 'ps1'
    ]
    can_view_inline = file_exists and file_type in viewable_types
    
    context = {
        'document': document,
        'is_owner': is_owner,
        'can_view_inline': can_view_inline,
        'file_exists': file_exists,
        'file_type': file_type,
        'file_url': file_url,
        'versions': versions,
        'permissions': permissions,
        'shares': shares,
        'total_versions': versions.count(),
        'category_choices': Document.Category.choices,
        'status_choices': Document.Status.choices,
        'permission_type_choices': DocumentPermission.PermissionType.choices,
        'users': User.objects.exclude(id=user.id),
        'departments': Department.objects.all(),
    }
    return render(request, 'view_document.html', context)


@login_required
@require_http_methods(["POST"])
def update_document(request, slug):
    """Mettre à jour les informations d'un document"""
    document = get_object_or_404(Document, slug=slug, owner=request.user)
    
    # Mise à jour des champs
    title = request.POST.get('title')
    description = request.POST.get('description')
    category = request.POST.get('category')
    
    if title:
        document.title = title
    if description is not None:
        document.description = description
    if category:
        document.category = category
    
    document.save()
    
    # Mise à jour des permissions
    permission_types = request.POST.getlist('permission_types')
    if permission_types:
        permission, created = DocumentPermission.objects.get_or_create(document=document)
        permission.permission_types = ','.join(permission_types)
        
        # Gestion des départements
        if 'department' in permission_types:
            departments = request.POST.getlist('departments')
            if departments:
                permission.departments.set(Department.objects.filter(id__in=departments))
            else:
                permission.departments.clear()
        
        # Gestion des utilisateurs spécifiques
        if 'specific' in permission_types:
            users = request.POST.getlist('users')
            if users:
                permission.users.set(User.objects.filter(id__in=users))
            else:
                permission.users.clear()
        
        permission.save()
    
    ActivityLog.objects.create(
        user=request.user,
        action=ActivityLog.Action.EDIT,
        description=f"Mise à jour du document: {document.title}",
        document=document,
        ip_address=get_client_ip(request)
    )
    
    messages.success(request, "Document mis à jour avec succès.")
    return redirect('view_document', slug=document.slug)


@login_required
@require_http_methods(["POST"])
def upload_new_version(request, slug):
    """Uploader une nouvelle version d'un document"""
    import os
    
    document = get_object_or_404(Document, slug=slug, owner=request.user)
    
    new_file = request.FILES.get('new_file')
    version_note = request.POST.get('version_note', '')
    changes_summary = request.POST.get('changes_summary', '')
    
    if not new_file:
        messages.error(request, "Veuillez sélectionner un fichier.")
        return redirect('view_document', slug=document.slug)
    
    # Validation du type de fichier
    allowed_types = ['.pdf', '.docx', '.zip', '.xlsx', '.png', '.jpg', '.jpeg', '.txt', '.md', '.pptx']
    file_ext = os.path.splitext(new_file.name)[1].lower()
    if file_ext not in allowed_types:
        messages.error(request, f"Type de fichier non supporté: {file_ext}")
        return redirect('view_document', slug=document.slug)
    
    # Validation de la taille
    if new_file.size > 100 * 1024 * 1024:
        messages.error(request, "Fichier trop volumineux (max 100 MB)")
        return redirect('view_document', slug=document.slug)
    
    # Récupérer la prochaine version numéro
    last_version = document.versions.order_by('-version_number').first()
    current_version_number = (last_version.version_number if last_version else 0) + 1
    
    # ✅ Sauvegarder l'ancienne version (si elle existe)
    old_file_saved = False
    old_file_path = None
    
    try:
        if document.file and hasattr(document.file, 'path') and document.file.name:
            if os.path.exists(document.file.path):
                # Sauvegarder la version actuelle dans DocumentVersion
                DocumentVersion.objects.create(
                    document=document,
                    version_number=current_version_number,
                    file=document.file,  # Copie l'ancien fichier
                    file_size=document.file_size,
                    uploaded_by=request.user,
                    note=version_note,
                    changes_summary=changes_summary
                )
                old_file_saved = True
    except (ValueError, OSError, AttributeError) as e:
        print(f"Erreur lors de la sauvegarde de l'ancienne version: {e}")
    
    # ✅ Mettre à jour le document avec le nouveau fichier
    # Supprimer l'ancien fichier physique
    if old_file_saved and document.file:
        try:
            document.file.delete(save=False)
        except:
            pass
    
    # Assigner le nouveau fichier
    document.file = new_file
    document.file_size = new_file.size
    document.file_type = new_file.content_type or 'application/octet-stream'
    document.updated_at = timezone.now()
    document.save()  # ← Ceci sauvegarde le nouveau fichier sur le disque
    
    # Journalisation
    if old_file_saved:
        ActivityLog.objects.create(
            user=request.user,
            action=ActivityLog.Action.EDIT,
            description=f"Nouvelle version v{current_version_number + 1} du document: {document.title}",
            document=document,
            ip_address=get_client_ip(request)
        )
        messages.success(request, f"Nouvelle version du document ajoutée avec succès (v{current_version_number + 1})")
    else:
        ActivityLog.objects.create(
            user=request.user,
            action=ActivityLog.Action.EDIT,
            description=f"Mise à jour du document: {document.title}",
            document=document,
            ip_address=get_client_ip(request)
        )
        messages.success(request, f"Document mis à jour avec succès")
    
    return redirect('view_document', slug=document.slug)


@login_required
@require_http_methods(["POST"])
def delete_version(request, slug, version_id):
    """Supprimer une version d'un document"""
    document = get_object_or_404(Document, slug=slug, owner=request.user)
    version = get_object_or_404(DocumentVersion, id=version_id, document=document)
    
    # Vérifier qu'on ne supprime pas la version courante
    if document.versions.count() > 1:
        version.file.delete()
        version.delete()
        messages.success(request, f"Version v{version.version_number} supprimée avec succès.")
    else:
        messages.error(request, "Impossible de supprimer la seule version du document.")
    
    return redirect('view_document', slug=document.slug)


@login_required
def document_versions(request, slug):
    """Afficher l'historique des versions d'un document"""
    document = get_object_or_404(Document, slug=slug, owner=request.user)
    versions = DocumentVersion.objects.filter(document=document).order_by('-version_number')
    
    context = {
        'document': document,
        'versions': versions,
        'current_version': versions.first(),
    }
    return render(request, 'document_versions.html', context)


@login_required
def restore_version(request, version_id):
    """Restaurer une version antérieure"""
    version = get_object_or_404(DocumentVersion, id=version_id)
    document = version.document
    
    # Vérifier que l'utilisateur est le propriétaire
    if document.owner != request.user:
        messages.error(request, "Vous n'êtes pas autorisé à restaurer ce document.")
        return redirect('files')
    
    # Récupérer le fichier de l'ancienne version
    old_file = version.file
    
    if not old_file or not old_file.name:
        messages.error(request, "Le fichier de cette version est introuvable.")
        return redirect('document_versions', slug=document.slug)
    
    try:
        # Ouvrir le fichier de l'ancienne version
        old_file.open('rb')
        file_content = old_file.read()
        old_file.close()
        
        from django.core.files.base import ContentFile
        
        # Créer un nouveau fichier avec le contenu de l'ancienne version
        new_file = ContentFile(file_content, name=old_file.name)
        
        # Créer une nouvelle version (l'ancienne devient une version antérieure)
        current_version_number = document.versions.count() + 1
        
        # Sauvegarder la version actuelle comme historique
        DocumentVersion.objects.create(
            document=document,
            version_number=current_version_number,
            file=document.file,
            file_size=document.file_size,
            uploaded_by=request.user,
            note=f"Restauration de la version v{version.version_number}",
            changes_summary=f"Restauration d'une version antérieure (v{version.version_number})"
        )
        
        # Restaurer l'ancienne version comme version courante
        document.file = new_file
        document.file_size = new_file.size
        document.updated_at = timezone.now()
        document.save()
        
        ActivityLog.objects.create(
            user=request.user,
            action=ActivityLog.Action.EDIT,
            description=f"Restauration du document '{document.title}' à la version v{version.version_number}",
            document=document,
            ip_address=get_client_ip(request)
        )
        
        messages.success(request, f"Version v{version.version_number} restaurée avec succès.")
        
    except Exception as e:
        messages.error(request, f"Erreur lors de la restauration: {str(e)}")
    
    return redirect('document_versions', slug=document.slug)

@login_required
def backup_management(request):
    """Interface de gestion des sauvegardes (admin uniquement)"""
    if not request.user.is_admin_user:
        messages.error(request, "Accès non autorisé.")
        return redirect('dashboard')
    
    backup_dir = os.path.join(settings.BASE_DIR, 'backups')
    backups = []
    
    if os.path.exists(backup_dir):
        for item in os.listdir(backup_dir):
            if item.endswith('.zip') or (os.path.isdir(os.path.join(backup_dir, item)) and item.startswith('backup_')):
                item_path = os.path.join(backup_dir, item)
                backups.append({
                    'name': item,
                    'size': os.path.getsize(item_path) if os.path.isfile(item_path) else self.get_dir_size(item_path),
                    'modified': datetime.fromtimestamp(os.path.getmtime(item_path)),
                    'is_dir': os.path.isdir(item_path)
                })
    
    backups.sort(key=lambda x: x['modified'], reverse=True)
    
    return render(request, 'backup_management.html', {
        'backups': backups,
        'backup_dir': backup_dir
    })


def get_dir_size(path):
    total = 0
    for dirpath, dirnames, filenames in os.walk(path):
        for f in filenames:
            fp = os.path.join(dirpath, f)
            total += os.path.getsize(fp)
    return total


@login_required
def create_backup(request):
    """Déclencher une sauvegarde manuelle"""
    if not request.user.is_admin_user:
        return JsonResponse({'error': 'Non autorisé'}, status=403)
    
    from django.core.management import call_command
    import subprocess
    
    try:
        call_command('auto_backup')
        return JsonResponse({'success': True, 'message': 'Sauvegarde créée avec succès'})
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


@login_required
def download_backup(request, backup_name):
    """Télécharger une sauvegarde"""
    if not request.user.is_admin_user:
        messages.error(request, "Accès non autorisé.")
        return redirect('dashboard')
    
    backup_dir = os.path.join(settings.BASE_DIR, 'backups')
    backup_path = os.path.join(backup_dir, backup_name)
    
    if not os.path.exists(backup_path):
        messages.error(request, "Sauvegarde introuvable.")
        return redirect('backup_management')
    
    if os.path.isfile(backup_path):
        response = FileResponse(open(backup_path, 'rb'))
        response['Content-Disposition'] = f'attachment; filename="{backup_name}"'
        return response
    else:
        # Compresser le dossier
        import zipfile
        import tempfile
        
        zip_path = os.path.join(tempfile.gettempdir(), f'{backup_name}.zip')
        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
            for root, dirs, files in os.walk(backup_path):
                for file in files:
                    file_path = os.path.join(root, file)
                    arcname = os.path.relpath(file_path, backup_path)
                    zipf.write(file_path, arcname)
        
        response = FileResponse(open(zip_path, 'rb'))
        response['Content-Disposition'] = f'attachment; filename="{backup_name}.zip"'
        return response
    

@login_required
def export_audit_page(request):
    """Page d'export des journaux d'audit"""
    if not request.user.is_admin_user:
        messages.error(request, "Accès non autorisé")
        return redirect('dashboard')
    
    actions = ActivityLog.Action.choices
    
    context = {
        'actions': actions,
    }
    return render(request, 'export_audit.html', context)


@login_required
def export_audit_logs(request):
    """Export des journaux d'audit en CSV"""
    if not request.user.is_admin_user:
        messages.error(request, "Accès non autorisé")
        return redirect('dashboard')
    
    # Récupérer les filtres
    action_filter = request.GET.get('action', '')
    date_from = request.GET.get('date_from', '')
    date_to = request.GET.get('date_to', '')
    user_filter = request.GET.get('user', '')
    
    logs = ActivityLog.objects.all().order_by('-created_at')
    
    if action_filter:
        logs = logs.filter(action=action_filter)
    if date_from:
        logs = logs.filter(created_at__gte=date_from)
    if date_to:
        logs = logs.filter(created_at__lte=date_to)
    if user_filter:
        logs = logs.filter(user__email__icontains=user_filter)
    
    # Créer la réponse CSV
    response = HttpResponse(content_type='text/csv; charset=utf-8')
    response['Content-Disposition'] = 'attachment; filename="audit_logs.csv"'
    
    # Ajouter BOM pour UTF-8 (compatibilité Excel)
    response.write('\ufeff')
    
    writer = csv.writer(response, delimiter=';')
    writer.writerow(['Date', 'Utilisateur', 'Action', 'Document', 'IP Address', 'Description'])
    
    for log in logs:
        writer.writerow([
            log.created_at.strftime('%Y-%m-%d %H:%M:%S'),
            str(log.user) if log.user else 'Système',
            log.get_action_display(),
            log.document.title if log.document else '-',
            log.ip_address or '-',
            log.description or '-'
        ])
    
    return response