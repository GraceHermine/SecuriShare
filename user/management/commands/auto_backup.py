# user/management/commands/auto_backup.py
import os
import shutil
import hashlib
import json
from datetime import datetime
from django.core.management.base import BaseCommand
from django.conf import settings
from user.models import Document, DocumentShare, DocumentVersion
from django.utils import timezone

class Command(BaseCommand):
    help = 'Sauvegarde automatique des documents et de la base de données'

    def add_arguments(self, parser):
        parser.add_argument('--backup-dir', type=str, help='Répertoire de sauvegarde')
        parser.add_argument('--compress', action='store_true', help='Compresser les sauvegardes')
        parser.add_argument('--keep-days', type=int, default=30, help='Nombre de jours de conservation')

    def handle(self, *args, **options):
        backup_dir = options.get('backup_dir') or os.path.join(settings.BASE_DIR, 'backups')
        compress = options.get('compress', True)
        keep_days = options.get('keep_days', 30)
        
        # Créer le répertoire de backup
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        backup_path = os.path.join(backup_dir, f'backup_{timestamp}')
        os.makedirs(backup_path, exist_ok=True)
        
        self.stdout.write(f"[{timestamp}] Début de la sauvegarde...")
        
        # 1. Sauvegarde des documents
        self.backup_documents(backup_path)
        
        # 2. Sauvegarde des métadonnées
        self.backup_metadata(backup_path)
        
        # 3. Sauvegarde de la base de données (SQL)
        self.backup_database(backup_path)
        
        # 4. Nettoyage des anciennes sauvegardes
        self.cleanup_old_backups(backup_dir, keep_days)
        
        # 5. Compression si demandé
        if compress:
            self.compress_backup(backup_dir, timestamp)
        
        # 6. Création du manifeste
        self.create_manifest(backup_path, timestamp)
        
        self.stdout.write(self.style.SUCCESS(f"Sauvegarde terminée: {backup_path}"))

    def backup_documents(self, backup_path):
        """Sauvegarde des fichiers documents"""
        documents_dir = os.path.join(backup_path, 'documents')
        os.makedirs(documents_dir, exist_ok=True)
        
        documents = Document.objects.all()
        count = 0
        
        for doc in documents:
            if doc.file and os.path.exists(doc.file.path):
                backup_file = os.path.join(documents_dir, f"{doc.slug}_{os.path.basename(doc.file.name)}")
                shutil.copy2(doc.file.path, backup_file)
                count += 1
        
        self.stdout.write(f"  - {count} documents sauvegardés")

    def backup_metadata(self, backup_path):
        """Sauvegarde des métadonnées en JSON"""
        metadata = {
            'documents': [],
            'shares': [],
            'activity_logs': [],
            'backup_date': timezone.now().isoformat(),
            'version': '1.0'
        }
        
        for doc in Document.objects.all():
            doc_data = {
                'id': str(doc.id),
                'slug': doc.slug,
                'title': doc.title,
                'description': doc.description,
                'owner_email': doc.owner.email,
                'owner_name': doc.owner.full_name,
                'category': doc.category,
                'status': doc.status,
                'is_shared': doc.is_shared,
                'created_at': doc.created_at.isoformat(),
                'updated_at': doc.updated_at.isoformat(),
                'file_name': os.path.basename(doc.file.name) if doc.file else None,
                'file_size': doc.file_size,
                'file_type': doc.file_type,
            }
            metadata['documents'].append(doc_data)
        
        for share in DocumentShare.objects.filter(is_active=True):
            share_data = {
                'document_title': share.document.title,
                'shared_by': share.shared_by.email,
                'shared_with': share.shared_with.email if share.shared_with else None,
                'permission': share.permission,
                'token': str(share.token),
                'expires_at': share.expires_at.isoformat() if share.expires_at else None,
                'created_at': share.created_at.isoformat(),
            }
            metadata['shares'].append(share_data)
        
        with open(os.path.join(backup_path, 'metadata.json'), 'w', encoding='utf-8') as f:
            json.dump(metadata, f, indent=2, ensure_ascii=False)
        
        self.stdout.write("  - Métadonnées sauvegardées")

    def backup_database(self, backup_path):
        """Sauvegarde de la base de données via dump"""
        db_path = settings.DATABASES['default']['NAME']
        
        if db_path.endswith('.sqlite3'):
            # SQLite - simple copie
            shutil.copy2(db_path, os.path.join(backup_path, 'database.sqlite3'))
            self.stdout.write("  - Base de données SQLite sauvegardée")
        
        elif 'postgresql' in db_path or 'postgres' in db_path:
            # PostgreSQL
            import subprocess
            db_name = settings.DATABASES['default']['NAME']
            db_user = settings.DATABASES['default']['USER']
            db_host = settings.DATABASES['default'].get('HOST', 'localhost')
            db_port = settings.DATABASES['default'].get('PORT', '5432')
            
            dump_path = os.path.join(backup_path, 'database.sql')
            
            try:
                subprocess.run([
                    'pg_dump', '-h', db_host, '-p', db_port, '-U', db_user,
                    '-f', dump_path, db_name
                ], check=True, capture_output=True)
                self.stdout.write("  - Base de données PostgreSQL sauvegardée")
            except Exception as e:
                self.stdout.write(self.style.ERROR(f"  - Erreur PostgreSQL: {e}"))

    def cleanup_old_backups(self, backup_dir, keep_days):
        """Supprimer les sauvegardes trop anciennes"""
        import time
        now = time.time()
        count = 0
        
        for item in os.listdir(backup_dir):
            item_path = os.path.join(backup_dir, item)
            if os.path.isdir(item_path) and item.startswith('backup_'):
                try:
                    # Extraire la date du nom
                    date_str = item.replace('backup_', '')
                    item_time = datetime.strptime(date_str, '%Y%m%d_%H%M%S').timestamp()
                    
                    if now - item_time > keep_days * 86400:
                        shutil.rmtree(item_path)
                        count += 1
                except:
                    pass
        
        if count > 0:
            self.stdout.write(f"  - {count} anciennes sauvegardes supprimées")

    def compress_backup(self, backup_dir, timestamp):
        """Compresser la sauvegarde en ZIP"""
        import zipfile
        
        backup_path = os.path.join(backup_dir, f'backup_{timestamp}')
        zip_path = os.path.join(backup_dir, f'backup_{timestamp}.zip')
        
        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
            for root, dirs, files in os.walk(backup_path):
                for file in files:
                    file_path = os.path.join(root, file)
                    arcname = os.path.relpath(file_path, backup_path)
                    zipf.write(file_path, arcname)
        
        # Supprimer le dossier non compressé
        shutil.rmtree(backup_path)
        self.stdout.write(f"  - Sauvegarde compressée: backup_{timestamp}.zip")

    def create_manifest(self, backup_path, timestamp):
        """Créer un fichier manifeste"""
        manifest = {
            'backup_id': timestamp,
            'created_at': timezone.now().isoformat(),
            'type': 'automatic_backup',
            'status': 'completed',
            'files_count': len(os.listdir(backup_path)) if os.path.exists(backup_path) else 0
        }
        
        with open(os.path.join(backup_path, 'manifest.json'), 'w') as f:
            json.dump(manifest, f, indent=2)