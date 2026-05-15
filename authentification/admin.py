from django.contrib import admin

# Register your models here.
# from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.utils.translation import gettext_lazy as _
from .models import (
    User, PasswordResetCode, LoginAttempt,
    # Document, DocumentShare, DocumentVersion,
    # ActivityLog, Notification, AccessRequest, SupportTicket
)


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    list_display  = ('email', 'full_name', 'role', 'statut', 'mfa_enabled', 'created_at')
    list_filter   = ('role', 'statut', 'mfa_enabled', 'genre')
    search_fields = ('email', 'nom', 'prenom', 'numero')
    ordering      = ('-created_at',)

    fieldsets = (
        (_("Connexion"),       {'fields': ('email', 'password')}),
        (_("Identité"),        {'fields': ('nom', 'prenom', 'genre', 'datenaiss', 'photo')}),
        (_("Contact"),         {'fields': ('numero', 'adresse')}),
        (_("Rôle & statut"),   {'fields': ('role', 'statut', 'is_active', 'is_staff', 'is_superuser')}),
        (_("Sécurité MFA"),    {'fields': ('mfa_enabled', 'mfa_secret')}),
        (_("Permissions"),     {'fields': ('groups', 'user_permissions')}),
        (_("Dates"),           {'fields': ('last_login', 'created_at', 'last_updated_at')}),
    )
    add_fieldsets = (
        (None, {
            'classes': ('wide',),
            'fields': ('email', 'nom', 'prenom', 'password1', 'password2', 'role'),
        }),
    )
    readonly_fields = ('created_at', 'last_updated_at', 'last_login')


@admin.register(PasswordResetCode)
class PasswordResetCodeAdmin(admin.ModelAdmin):
    list_display  = ('email', 'code', 'used', 'created_at')
    list_filter   = ('used',)
    search_fields = ('email',)
    readonly_fields = ('token', 'created_at')


@admin.register(LoginAttempt)
class LoginAttemptAdmin(admin.ModelAdmin):
    list_display  = ('email', 'ip_address', 'success', 'created_at')
    list_filter   = ('success',)
    search_fields = ('email', 'ip_address')
    readonly_fields = ('created_at',)


# @admin.register(Document)
# class DocumentAdmin(admin.ModelAdmin):
#     list_display  = ('title', 'owner', 'category', 'status', 'is_shared', 'created_at')
#     list_filter   = ('category', 'status', 'is_shared')
#     search_fields = ('title', 'owner__email', 'owner__nom')
#     readonly_fields = ('id', 'created_at', 'updated_at')


# @admin.register(DocumentShare)
# class DocumentShareAdmin(admin.ModelAdmin):
#     list_display  = ('document', 'shared_by', 'shared_with', 'permission', 'is_active', 'expires_at')
#     list_filter   = ('permission', 'is_active')
#     readonly_fields = ('token', 'created_at')


# @admin.register(DocumentVersion)
# class DocumentVersionAdmin(admin.ModelAdmin):
#     list_display  = ('document', 'version_number', 'uploaded_by', 'file_size', 'created_at')
#     readonly_fields = ('created_at',)


# @admin.register(ActivityLog)
# class ActivityLogAdmin(admin.ModelAdmin):
#     list_display  = ('user', 'action', 'document', 'ip_address', 'created_at')
#     list_filter   = ('action',)
#     search_fields = ('user__email',)
#     readonly_fields = ('created_at',)


# @admin.register(Notification)
# class NotificationAdmin(admin.ModelAdmin):
#     list_display  = ('user', 'title', 'type', 'is_read', 'created_at')
#     list_filter   = ('type', 'is_read')


# @admin.register(AccessRequest)
# class AccessRequestAdmin(admin.ModelAdmin):
#     list_display  = ('requester', 'document', 'status', 'reviewed_by', 'created_at')
#     list_filter   = ('status',)


# @admin.register(SupportTicket)
# class SupportTicketAdmin(admin.ModelAdmin):
#     list_display  = ('subject', 'user', 'priority', 'status', 'created_at')
#     list_filter   = ('priority', 'status')
#     search_fields = ('subject', 'user__email')