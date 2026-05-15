from django.urls import path
from . import views


urlpatterns = [
  # Dans urls.py du dossier principal ou de l'application
    # ── Espace utilisateur ────────────────────────────────
    path('dashboard/', views.dashboard_view, name='dashboard'),
    path('files/', views.files_view, name='files'),

    # ── Endpoints avec SLUG  ───────────────────
    path('api/upload/', views.upload_document, name='api_upload'),
    path('api/download/<slug:slug>/', views.download_document, name='api_download'),
    path('api/delete/<slug:slug>/', views.delete_document, name='api_delete'),
    path('api/documents/', views.list_documents_api, name='api_documents'),
    path('api/share/<slug:slug>/', views.share_document, name='api_share'),
    path('api/stats/', views.dashboard_stats, name='api_stats'),
    
    # ── Liens de partage   ───────────────────────────
    path('share/<uuid:token>/', views.shared_document_view, name='shared_document'),
    path('share/<uuid:token>/download/', views.download_shared_file, name='shared_download'),
    path('export-audit/', views.export_audit_page, name='export_audit'),
    path('export-audit/csv/', views.export_audit_logs, name='export_audit_logs'),
    path('create/', views.create_document_view, name='create_document'),
    path('permissions/<slug:slug>/', views.update_document_permissions, name='update_permissions'),
    path('view/<slug:slug>/', views.view_document, name='view_document'),
    path('view/<slug:slug>/update/', views.update_document, name='update_document'),
    path('view/<slug:slug>/upload-version/', views.upload_new_version, name='upload_version'),
    path('view/<slug:slug>/delete-version/<int:version_id>/', views.delete_version, name='delete_version'),
]