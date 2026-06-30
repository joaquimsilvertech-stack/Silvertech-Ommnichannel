from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

from .models import AuditLog, CustomUser


@admin.register(CustomUser)
class CustomUserAdmin(BaseUserAdmin):
    """Admin alinhado a login por e-mail (sem campo username)."""

    ordering = ('email',)
    list_display = ('email', 'first_name', 'last_name', 'role', 'is_staff', 'is_active')
    list_filter = ('is_staff', 'is_superuser', 'is_active', 'role')
    search_fields = ('email', 'first_name', 'last_name')

    fieldsets = (
        (None, {'fields': ('email', 'password')}),
        ('Permissões', {'fields': ('is_active', 'is_staff', 'is_superuser', 'groups', 'user_permissions')}),
        ('Datas importantes', {'fields': ('last_login', 'date_joined')}),
        ('Perfil', {'fields': ('first_name', 'last_name', 'role')}),
    )
    add_fieldsets = (
        (
            None,
            {
                'classes': ('wide',),
                'fields': ('email', 'password1', 'password2', 'role', 'is_staff', 'is_superuser'),
            },
        ),
    )


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ('created_at', 'workspace', 'actor', 'action', 'model_name', 'object_id')
    list_filter = ('action', 'model_name', 'created_at')
    search_fields = ('object_id', 'object_repr', 'actor__email', 'workspace__name')
    readonly_fields = (
        'id',
        'workspace',
        'actor',
        'action',
        'model_name',
        'object_id',
        'object_repr',
        'before',
        'after',
        'changes',
        'ip_address',
        'user_agent',
        'request_id',
        'created_at',
        'updated_at',
    )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
