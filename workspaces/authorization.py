"""
Checagem unica de membership + role de workspace.

Primitivo generico (sem nada de canal): bypass de superuser + query de `Member`.
Vive na app dona (`workspaces`) para que `workspaces.permissions` e a politica de
canais (`omnichannel.channel_authorization`) o reutilizem sem import circular — a
direcao de dependencia fica sempre omnichannel -> workspaces.
"""
from __future__ import annotations

from .models import Member


def user_has_workspace_role(user, workspace_id, allowed_roles) -> bool:
    """
    Unica implementacao da checagem de role: bypass de superuser + query de
    membership. Reutilizada tanto por `IsWorkspaceAdminMember` quanto pela
    politica de capabilities de canais.
    """
    if not user or not user.is_authenticated or workspace_id is None:
        return False
    if user.is_superuser:
        return True
    return Member.objects.filter(
        workspace_id=workspace_id,
        user=user,
        role__in=allowed_roles,
    ).exists()
