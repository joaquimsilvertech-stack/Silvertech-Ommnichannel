"""
Fonte unica de verdade da autorizacao dos canais WhatsApp.

Toda a logica de "quais roles podem fazer o que" vive aqui, num mapa
capability -> roles, para eliminar a duplicacao que antes existia entre
`workspaces.permissions.IsWorkspaceAdminMember` e o
`_WorkspaceWhatsAppChannelAccessMixin._get_workspace`.

Politica de produto
-------------------
- Acoes de leitura e conexao (`VIEW`, `CONNECT`) e as acoes operacionais
  (`RESTART`, `DISCONNECT`) seguem a regra historica: `{OWNER, ADMIN}`.
- `REMOVE` e destrutiva e irreversivel (apaga a instancia na Evolution e orfaniza
  as conversas para legado via `SET_NULL`); por isso e **OWNER-only** por padrao.
  Este e o unico lugar a ajustar caso o produto decida liberar `REMOVE` para
  ADMIN — basta trocar o conjunto de roles do mapa abaixo.

Superuser
---------
`request.user.is_superuser` faz **bypass de todas as capabilities**, para
suporte e diagnostico, coerente com o comportamento ja existente em todo o
subsistema de canais. Superuser nao precisa de membership no workspace.
"""
from __future__ import annotations

from enum import Enum

from django.shortcuts import get_object_or_404
from rest_framework.permissions import BasePermission

from workspaces.models import Member, Workspace


class ChannelCapability(str, Enum):
    """Acoes controladas sobre um canal WhatsApp."""

    VIEW = 'view'
    CONNECT = 'connect'
    RESTART = 'restart'
    DISCONNECT = 'disconnect'
    REMOVE = 'remove'


_ADMIN_ROLES = frozenset({Member.Role.OWNER, Member.Role.ADMIN})
_OWNER_ONLY = frozenset({Member.Role.OWNER})

# Fonte unica capability -> roles. Ajuste aqui e em nenhum outro lugar.
CHANNEL_CAPABILITY_ROLES: dict[ChannelCapability, frozenset[str]] = {
    ChannelCapability.VIEW: _ADMIN_ROLES,
    ChannelCapability.CONNECT: _ADMIN_ROLES,
    ChannelCapability.RESTART: _ADMIN_ROLES,
    ChannelCapability.DISCONNECT: _ADMIN_ROLES,
    ChannelCapability.REMOVE: _OWNER_ONLY,
}


def roles_for_capability(capability: ChannelCapability) -> frozenset[str]:
    return CHANNEL_CAPABILITY_ROLES[capability]


def user_has_workspace_role(user, workspace_id, allowed_roles) -> bool:
    """
    Unica implementacao da checagem de role: bypass de superuser + query de
    membership. Reutilizada tanto pela politica de canais quanto por
    `IsWorkspaceAdminMember`.
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


def user_has_channel_capability(user, workspace_id, capability: ChannelCapability) -> bool:
    return user_has_workspace_role(user, workspace_id, roles_for_capability(capability))


def resolve_workspace_for_capability(
    request,
    workspace_id,
    capability: ChannelCapability,
) -> Workspace:
    """
    Resolve o workspace exigindo a capability, sem vazar objeto de outro tenant:
    quem nao tem a role/membership exigida recebe 404 (nunca 403 revelando
    existencia). Superuser resolve qualquer workspace existente.
    """
    if request.user.is_superuser:
        return get_object_or_404(Workspace, id=workspace_id)
    return get_object_or_404(
        Workspace,
        id=workspace_id,
        memberships__user=request.user,
        memberships__role__in=roles_for_capability(capability),
    )


class HasChannelCapability(BasePermission):
    """
    Permission parametrizavel: a view declara a capability exigida via
    `required_channel_capability` (ou `get_required_channel_capability(request)`
    para variar por metodo, como o detalhe que serve GET=VIEW e DELETE=REMOVE).
    """

    def has_permission(self, request, view) -> bool:
        capability = self._capability_for(request, view)
        return user_has_channel_capability(
            request.user,
            view.kwargs.get('workspace_id'),
            capability,
        )

    @staticmethod
    def _capability_for(request, view) -> ChannelCapability:
        getter = getattr(view, 'get_required_channel_capability', None)
        if callable(getter):
            return getter(request)
        return getattr(view, 'required_channel_capability', ChannelCapability.VIEW)
