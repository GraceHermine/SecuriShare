from django.db import models
import uuid
import hashlib
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from django.utils.text import slugify
from authentification.models import User
 
# Create your models here.
# =============================================================
# DOCUMENT
# =============================================================
class Document(models.Model):
    """
    Document sécurisé stocké dans le vault DocuSafe.
    """
 
    class Status(models.TextChoices):
        ENCRYPTED = "encrypted", _("Chiffré")
        PENDING   = "pending",   _("En attente")
        REVOKED   = "revoked",   _("Révoqué")
 
    class Category(models.TextChoices):
        CONTRACT  = "contract",  _("Contrat")
        LEGAL     = "legal",     _("Juridique")
        FINANCIAL = "financial", _("Financier")
        HR        = "hr",        _("RH")
        TECHNICAL = "technical", _("Technique")
        OTHER     = "other",     _("Autre")
 
    id          = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    owner       = models.ForeignKey(
        User, on_delete=models.CASCADE,
        related_name="documents",
        verbose_name=_("Propriétaire")
    )
    slug = models.SlugField(
        max_length=255, 
        unique=True, 
        blank=True, 
        null=True,
        verbose_name=_("Slug")
    )
    title       = models.CharField(max_length=500, verbose_name=_("Titre"))
    description = models.TextField(null=True, blank=True, verbose_name=_("Description"))
    file        = models.FileField(upload_to='documents/%Y/%m/', verbose_name=_("Fichier"))
    file_size   = models.PositiveBigIntegerField(default=0, verbose_name=_("Taille (octets)"))
    file_type   = models.CharField(max_length=500, null=True, blank=True, verbose_name=_("Type MIME"))
 
    category    = models.CharField(
        max_length=20, choices=Category.choices,
        default=Category.OTHER, verbose_name=_("Catégorie")
    )
    status      = models.CharField(
        max_length=20, choices=Status.choices,
        default=Status.ENCRYPTED, verbose_name=_("Statut")
    )
 
    is_shared   = models.BooleanField(default=False, verbose_name=_("Partagé"))
    created_at  = models.DateTimeField(auto_now_add=True, verbose_name=_("Uploadé le"))
    updated_at  = models.DateTimeField(auto_now=True, verbose_name=_("Modifié le"))
 
    class Meta:
        verbose_name = _("Document")
        verbose_name_plural = _("Documents")
        ordering = ['-created_at']
 
    def __str__(self):
        return f"{self.title} ({self.owner.full_name})"
 
    @property
    def file_size_human(self):
        """Retourne la taille lisible (Ko, Mo, Go)."""
        size = self.file_size
        for unit in ['o', 'Ko', 'Mo', 'Go']:
            if size < 1024:
                return f"{size:.1f} {unit}"
            size /= 1024
        return f"{size:.1f} To"
    
    def create_version(self, file, user, note='', changes_summary=''):
        """Crée une nouvelle version du document"""
        
        
        # Calculer le hash du fichier
        sha256_hash = hashlib.sha256()
        for chunk in file.chunks():
            sha256_hash.update(chunk)
        file_hash = sha256_hash.hexdigest()
        
        # Sauvegarder la version actuelle
        current_version_number = (self.versions.order_by('-version_number').first().version_number if self.versions.exists() else 0) + 1
        
        DocumentVersion.objects.create(
            document=self,
            version_number=current_version_number,
            file=self.file,
            file_size=self.file_size,
            file_hash=file_hash,
            uploaded_by=user,
            note=note,
            changes_summary=changes_summary
        )
        
        # Mettre à jour le document avec le nouveau fichier
        self.file = file
        self.file_size = file.size
        self.updated_at = timezone.now()
        self.save()
 
    
    def save(self, *args, **kwargs):
        if not self.slug:
            # Générer un slug unique à partir du titre
            base_slug = slugify(self.title)
            slug = base_slug
            counter = 1
            while Document.objects.filter(slug=slug).exists():
                slug = f"{base_slug}-{counter}"
                counter += 1
            self.slug = slug
        super().save(*args, **kwargs)
 
 
# =============================================================
# PARTAGE DE DOCUMENT
# =============================================================
class DocumentShare(models.Model):
    """
    Partage d'un document avec un autre utilisateur ou via lien temporaire.
    """
 
    class Permission(models.TextChoices):
        VIEW     = "view",     _("Lecture seule")
        DOWNLOAD = "download", _("Téléchargement")
        EDIT     = "edit",     _("Édition")
 
    document   = models.ForeignKey(
        Document, on_delete=models.CASCADE,
        related_name="shares", verbose_name=_("Document")
    )
    shared_by  = models.ForeignKey(
        User, on_delete=models.CASCADE,
        related_name="shares_sent",
        verbose_name=_("Partagé par")
    )
    shared_with = models.ForeignKey(
        User, on_delete=models.CASCADE,
        related_name="shares_received",
        null=True, blank=True,
        verbose_name=_("Partagé avec")
    )
    permission  = models.CharField(
        max_length=10, choices=Permission.choices,
        default=Permission.VIEW, verbose_name=_("Permission")
    )
    # Lien temporaire
    token       = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    expires_at  = models.DateTimeField(null=True, blank=True, verbose_name=_("Expire le"))
    is_active   = models.BooleanField(default=True, verbose_name=_("Actif"))
 
    created_at  = models.DateTimeField(auto_now_add=True, verbose_name=_("Partagé le"))
 
    class Meta:
        verbose_name = _("Partage")
        verbose_name_plural = _("Partages")
        ordering = ['-created_at']
 
    def is_expired(self):
        if self.expires_at is None:
            return False
        return timezone.now() > self.expires_at
 
    def __str__(self):
        target = self.shared_with or f"lien ({self.token})"
        return f"{self.document.title} → {target}"
 
 
# =============================================================
# VERSION DE DOCUMENT
# =============================================================
class DocumentVersion(models.Model):
    document = models.ForeignKey(Document, on_delete=models.CASCADE, related_name="versions")
    version_number = models.PositiveIntegerField()
    file = models.FileField(upload_to='documents/versions/%Y/%m/')
    file_size = models.PositiveBigIntegerField(default=0)
    file_hash = models.CharField(max_length=64, blank=True, null=True, verbose_name=_("Hash SHA-256"))
    uploaded_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name="document_versions")
    note = models.TextField(null=True, blank=True, verbose_name=_("Note de version"))
    changes_summary = models.TextField(null=True, blank=True, verbose_name=_("Résumé des changements"))
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        verbose_name = _("Version de document")
        verbose_name_plural = _("Versions de document")
        ordering = ['-version_number']
        unique_together = ('document', 'version_number')
    
    def __str__(self):
        return f"{self.document.title} — v{self.version_number}"


# Ajoutez une méthode dans Document


 
# =============================================================
# JOURNAL D'ACTIVITÉ
# =============================================================
class ActivityLog(models.Model):
    """
    Trace toutes les actions importantes effectuées sur le système.
    """
 
    class Action(models.TextChoices):
        LOGIN         = "login",          _("Connexion")
        LOGOUT        = "logout",         _("Déconnexion")
        UPLOAD        = "upload",         _("Upload document")
        DOWNLOAD      = "download",       _("Téléchargement")
        SHARE         = "share",          _("Partage")
        DELETE        = "delete",         _("Suppression")
        VIEW          = "view",           _("Consultation")
        EDIT          = "edit",           _("Modification")
        PASSWORD_RESET = "password_reset", _("Réinitialisation MDP")
        MFA_ENABLED   = "mfa_enabled",    _("MFA activé")
        MFA_DISABLED  = "mfa_disabled",   _("MFA désactivé")
 
    user       = models.ForeignKey(
        User, on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name="activity_logs",
        verbose_name=_("Utilisateur")
    )
    action     = models.CharField(max_length=30, choices=Action.choices, verbose_name=_("Action"))
    description = models.TextField(null=True, blank=True, verbose_name=_("Détail"))
    document   = models.ForeignKey(
        Document, on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name="activity_logs",
        verbose_name=_("Document concerné")
    )
    ip_address = models.GenericIPAddressField(null=True, blank=True, verbose_name=_("IP"))
    created_at = models.DateTimeField(auto_now_add=True, verbose_name=_("Date"))
 
    class Meta:
        verbose_name = _("Journal d'activité")
        verbose_name_plural = _("Journal d'activité")
        ordering = ['-created_at']
 
    def __str__(self):
        user_str = str(self.user) if self.user else "Anonyme"
        return f"{user_str} — {self.get_action_display()} — {self.created_at:%d/%m/%Y %H:%M}"
 
 
# =============================================================
# NOTIFICATION
# =============================================================
class Notification(models.Model):
 
    class Type(models.TextChoices):
        INFO    = "info",    _("Information")
        SUCCESS = "success", _("Succès")
        WARNING = "warning", _("Avertissement")
        DANGER  = "danger",  _("Alerte")
 
    user       = models.ForeignKey(
        User, on_delete=models.CASCADE,
        related_name="notifications",
        verbose_name=_("Destinataire")
    )
    title      = models.CharField(max_length=255, verbose_name=_("Titre"))
    message    = models.TextField(verbose_name=_("Message"))
    type       = models.CharField(
        max_length=10, choices=Type.choices,
        default=Type.INFO, verbose_name=_("Type")
    )
    is_read    = models.BooleanField(default=False, verbose_name=_("Lu"))
    created_at = models.DateTimeField(auto_now_add=True, verbose_name=_("Envoyé le"))
 
    class Meta:
        verbose_name = _("Notification")
        verbose_name_plural = _("Notifications")
        ordering = ['-created_at']
 
    def __str__(self):
        return f"[{self.get_type_display()}] {self.title} → {self.user}"
 
 
# =============================================================
# DEMANDE D'ACCÈS
# =============================================================
class AccessRequest(models.Model):
 
    class Status(models.TextChoices):
        PENDING  = "pending",  _("En attente")
        APPROVED = "approved", _("Approuvée")
        REJECTED = "rejected", _("Rejetée")
 
    requester  = models.ForeignKey(
        User, on_delete=models.CASCADE,
        related_name="access_requests_sent",
        verbose_name=_("Demandeur")
    )
    document   = models.ForeignKey(
        Document, on_delete=models.CASCADE,
        related_name="access_requests",
        verbose_name=_("Document")
    )
    message    = models.TextField(null=True, blank=True, verbose_name=_("Message"))
    status     = models.CharField(
        max_length=10, choices=Status.choices,
        default=Status.PENDING, verbose_name=_("Statut")
    )
    reviewed_by = models.ForeignKey(
        User, on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name="access_requests_reviewed",
        verbose_name=_("Traité par")
    )
    reviewed_at = models.DateTimeField(null=True, blank=True, verbose_name=_("Traité le"))
    created_at  = models.DateTimeField(auto_now_add=True, verbose_name=_("Créé le"))
 
    class Meta:
        verbose_name = _("Demande d'accès")
        verbose_name_plural = _("Demandes d'accès")
        ordering = ['-created_at']
 
    def __str__(self):
        return f"{self.requester} → {self.document.title} [{self.get_status_display()}]"
 
 
# =============================================================
# TICKET SUPPORT
# =============================================================
class SupportTicket(models.Model):
 
    class Priority(models.TextChoices):
        LOW    = "low",    _("Faible")
        MEDIUM = "medium", _("Normale")
        HIGH   = "high",   _("Haute")
        URGENT = "urgent", _("Urgente")
 
    class Status(models.TextChoices):
        OPEN        = "open",        _("Ouvert")
        IN_PROGRESS = "in_progress", _("En cours")
        RESOLVED    = "resolved",    _("Résolu")
        CLOSED      = "closed",      _("Fermé")
 
    user       = models.ForeignKey(
        User, on_delete=models.CASCADE,
        related_name="support_tickets",
        verbose_name=_("Utilisateur")
    )
    subject    = models.CharField(max_length=255, verbose_name=_("Sujet"))
    message    = models.TextField(verbose_name=_("Message"))
    priority   = models.CharField(
        max_length=10, choices=Priority.choices,
        default=Priority.MEDIUM, verbose_name=_("Priorité")
    )
    status     = models.CharField(
        max_length=15, choices=Status.choices,
        default=Status.OPEN, verbose_name=_("Statut")
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name=_("Créé le"))
    updated_at = models.DateTimeField(auto_now=True, verbose_name=_("Mis à jour le"))
 
    class Meta:
        verbose_name = _("Ticket support")
        verbose_name_plural = _("Tickets support")
        ordering = ['-created_at']
 
    def __str__(self):
        return f"[{self.get_priority_display()}] {self.subject} — {self.user}"
 
# =============================================================
# DÉPARTEMENT
# =============================================================
class Department(models.Model):
    name = models.CharField(max_length=100, unique=True, verbose_name=_("Nom"))
    code = models.CharField(max_length=20, unique=True, blank=True, verbose_name=_("Code"))
    description = models.TextField(blank=True, null=True, verbose_name=_("Description"))
    head = models.ForeignKey(
        'authentification.User', 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True,
        related_name="departments_managed",
        verbose_name=_("Responsable")
    )
    parent = models.ForeignKey(
        'self', 
        on_delete=models.CASCADE, 
        null=True, 
        blank=True,
        related_name="children",
        verbose_name=_("Département parent")
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        verbose_name = _("Département")
        verbose_name_plural = _("Départements")
        ordering = ['name']
    
    def __str__(self):
        return self.name
    
    def save(self, *args, **kwargs):
        if not self.code:
            self.code = slugify(self.name).upper()[:20]
        super().save(*args, **kwargs)


# =============================================================
# UTILISATEUR - DÉPARTEMENT
# =============================================================
class UserDepartment(models.Model):

    class Role(models.TextChoices):
        MEMBER = "member", _("Membre")
        MANAGER = "manager", _("Manager")
        DIRECTOR = "director", _("Directeur")
    
    user = models.ForeignKey(
        'authentification.User', 
        on_delete=models.CASCADE,
        related_name="departments",
        verbose_name=_("Utilisateur")
    )
    department = models.ForeignKey(
        Department, 
        on_delete=models.CASCADE,
        related_name="members",
        verbose_name=_("Département")
    )
    role = models.CharField(
        max_length=10, 
        choices=Role.choices,
        default=Role.MEMBER,
        verbose_name=_("Rôle")
    )
    joined_at = models.DateTimeField(auto_now_add=True, verbose_name=_("Date d'arrivée"))
    
    class Meta:
        verbose_name = _("Département utilisateur")
        verbose_name_plural = _("Départements utilisateurs")
        unique_together = ('user', 'department')
    
    def __str__(self):
        return f"{self.user.full_name} - {self.department.name} ({self.get_role_display()})"


# =============================================================
# PERMISSION DE DOCUMENT (corrigée)
# =============================================================
class DocumentPermission(models.Model):
    """
    Permissions avancées pour les documents 
    - Plusieurs types de diffusion peuvent être combinés
    """
    
    class PermissionType(models.TextChoices):
        GLOBAL = "global", _("Global - Tout le monde")
        DEPARTMENT = "department", _("Département - Limité à certains services")
        SPECIFIC = "specific", _("Spécifique - Personnes précises")
    
    document = models.ForeignKey(
        Document, 
        on_delete=models.CASCADE, 
        related_name="permissions",
        verbose_name=_("Document")
    )
    # Stocke les types sélectionnés sous forme de chaîne (ex: "global,department")
    permission_types = models.CharField(
        max_length=100,
        blank=True,
        default='',
        verbose_name=_("Types de diffusion")
    )
    departments = models.ManyToManyField(
        Department,  # Utilisez Department au lieu de Group
        blank=True, 
        related_name="documents_allowed",
        verbose_name=_("Départements concernés")
    )
    users = models.ManyToManyField(
        'authentification.User', 
        blank=True, 
        related_name="documents_shared",
        verbose_name=_("Utilisateurs concernés")
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name=_("Créé le"))
    updated_at = models.DateTimeField(auto_now=True, verbose_name=_("Modifié le"))
    
    class Meta:
        verbose_name = _("Permission de document")
        verbose_name_plural = _("Permissions de documents")
        ordering = ['-created_at']
    
    def __str__(self):
        return f"{self.document.title} - {self.permission_types}"
    
    def has_global(self):
        return 'global' in self.permission_types
    
    def has_department(self):
        return 'department' in self.permission_types
    
    def has_specific(self):
        return 'specific' in self.permission_types


# =============================================================
# CLÉ DE CHIFFREMENT DE DOCUMENT
# =============================================================
class DocumentEncryptionKey(models.Model):
    """
    Stocke les clés de chiffrement pour chaque document
    (À chiffrer avec la clé publique RSA en production)
    """
    document = models.OneToOneField(
        Document, 
        on_delete=models.CASCADE, 
        related_name="encryption_key",
        verbose_name=_("Document")
    )
    encryption_key = models.TextField(verbose_name=_("Clé de chiffrement (JWK)"))
    encryption_iv = models.TextField(verbose_name=_("Vecteur d'initialisation"))
    algorithm = models.CharField(max_length=50, default='AES-256-GCM', verbose_name=_("Algorithme"))
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        verbose_name = _("Clé de chiffrement")
        verbose_name_plural = _("Clés de chiffrement")
    
    def __str__(self):
        return f"Clé pour {self.document.title}"