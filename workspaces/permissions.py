from __future__ import annotations

from rest_framework.permissions import BasePermission

from .models import Member


class IsWorkspaceAdminMember(BasePermission):
    """Permite acesso apenas a membros administrativos do workspace da URL."""

    allowed_roles = {Member.Role.OWNER, Member.Role.ADMIN}

    def has_permission(self, request, view) -> bool:
        workspace_id = view.kwargs.get('workspace_id')
        if not request.user or not request.user.is_authenticated or workspace_id is None:
            return False

        if request.user.is_superuser:
            return True

        return Member.objects.filter(
            workspace_id=workspace_id,
            user=request.user,
            role__in=self.allowed_roles,
        ).exists()
