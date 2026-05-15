from django.contrib import admin

from .models import AccessRequest, ActivityLog, Department, Document, DocumentShare, DocumentVersion, Notification, SupportTicket, UserDepartment

# Register your models here.
@admin.register(Document)
class DocumentAdmin(admin.ModelAdmin):
    list_display  = ('title', 'owner', 'category', 'status', 'is_shared', 'created_at')
    list_filter   = ('category', 'status', 'is_shared')
    search_fields = ('title', 'owner__email', 'owner__nom')
    readonly_fields = ('id', 'created_at', 'updated_at')
 
 
@admin.register(DocumentShare)
class DocumentShareAdmin(admin.ModelAdmin):
    list_display  = ('document', 'shared_by', 'shared_with', 'permission', 'is_active', 'expires_at')
    list_filter   = ('permission', 'is_active')
    readonly_fields = ('token', 'created_at')
 
 
@admin.register(DocumentVersion)
class DocumentVersionAdmin(admin.ModelAdmin):
    list_display  = ('document', 'version_number', 'uploaded_by', 'file_size', 'created_at')
    readonly_fields = ('created_at',)
 
 
@admin.register(ActivityLog)
class ActivityLogAdmin(admin.ModelAdmin):
    list_display  = ('user', 'action', 'document', 'ip_address', 'created_at')
    list_filter   = ('action',)
    search_fields = ('user__email',)
    readonly_fields = ('created_at',)
 
 
@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display  = ('user', 'title', 'type', 'is_read', 'created_at')
    list_filter   = ('type', 'is_read')
 
 
@admin.register(AccessRequest)
class AccessRequestAdmin(admin.ModelAdmin):
    list_display  = ('requester', 'document', 'status', 'reviewed_by', 'created_at')
    list_filter   = ('status',)
 
 
@admin.register(SupportTicket)
class SupportTicketAdmin(admin.ModelAdmin):
    list_display  = ('subject', 'user', 'priority', 'status', 'created_at')
    list_filter   = ('priority', 'status')
    search_fields = ('subject', 'user__email')


@admin.register(Department)
class DepartmentAdmin(admin.ModelAdmin):
    list_display = ('name', 'code', 'head', 'created_at')
    search_fields = ('name', 'code')

@admin.register(UserDepartment)
class UserDepartmentAdmin(admin.ModelAdmin):
    list_display = ('user', 'department', 'role', 'joined_at')
    list_filter = ('department', 'role')