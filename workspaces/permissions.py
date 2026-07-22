from __future__ import annotations

from rest_framework.permissions import BasePermission

from .authorization import user_has_workspace_role
from .models import Member


class IsWorkspaceAdminMember(BasePermission):
    """Permite acesso apenas a membros administrativos do workspace da URL."""

    allowed_roles = {Member.Role.OWNER, Member.Role.ADMIN}

    def has_permission(self, request, view) -> bool:
        # Delega a checagem de role a fonte unica em workspaces.authorization,
        # para que a logica (bypass de superuser + query de membership) exista
        # num so lugar.
        return user_has_workspace_role(
            request.user,
            view.kwargs.get('workspace_id'),
            self.allowed_roles,
        )
