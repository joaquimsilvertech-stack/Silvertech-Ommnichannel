from django.contrib import admin

from .models import Member, Workspace, WorkspaceAIProviderConfig, WorkspaceInvite


@admin.register(Workspace)
class WorkspaceAdmin(admin.ModelAdmin):
    list_display = ('name', 'slug', 'created_at')
    search_fields = ('name', 'slug')
    prepopulated_fields = {'slug': ('name',)}


@admin.register(Member)
class MemberAdmin(admin.ModelAdmin):
    list_display = ('workspace', 'user', 'role', 'created_at')
    list_filter = ('role',)
    search_fields = ('workspace__name', 'user__email')


@admin.register(WorkspaceInvite)
class WorkspaceInviteAdmin(admin.ModelAdmin):
    list_display = ('email', 'workspace', 'role', 'accepted', 'expires_at', 'created_at')
    list_filter = ('accepted', 'role')
    search_fields = ('email', 'workspace__name', 'token')
    readonly_fields = ('token', 'invited_by', 'created_at', 'updated_at')


@admin.register(WorkspaceAIProviderConfig)
class WorkspaceAIProviderConfigAdmin(admin.ModelAdmin):
    list_display = ('workspace', 'provider', 'model_name', 'is_active', 'created_at', 'updated_at')
    list_filter = ('provider', 'is_active')
    search_fields = ('workspace__name', 'workspace__slug', 'model_name')
    readonly_fields = ('created_at', 'updated_at')
    exclude = ('api_key',)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def has_view_permission(self, request, obj=None):
        return request.user.is_staff
