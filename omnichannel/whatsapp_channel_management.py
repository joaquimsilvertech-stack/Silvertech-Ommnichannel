"""
Acoes de gestao do canal WhatsApp: reiniciar, desconectar e remover.

Sincronas (no request, como o provisionamento), idempotentes onde faz sentido e
com contrato de erro seguro reutilizando o padrao do provisionamento
(`SAFE_*` + `error_code` sanitizado, sem vazar payload/stack da Evolution).
"""
from __future__ import annotations

import logging

from django.db import transaction
from django.utils import timezone

from omnichannel.evolution import EvolutionAPIError, get_evolution_client
from omnichannel.models import WhatsAppChannel
from omnichannel.whatsapp_channel_provisioning import _sanitize_error_code

logger = logging.getLogger(__name__)

SAFE_MANAGEMENT_ERROR_MESSAGE = 'Nao foi possivel executar a acao no canal WhatsApp.'

# Estados em que uma acao de gestao operacional (restart/disconnect) e proibida:
# o canal esta no meio de um ciclo de vida que nao pode ser interrompido.
_BLOCKED_MANAGEMENT_STATES = frozenset(
    {WhatsAppChannel.Status.PROVISIONING, WhatsAppChannel.Status.DELETING},
)


class WhatsAppChannelManagementError(Exception):
    """Falha segura de gestao, sem credenciais ou detalhe externo."""

    def __init__(self, *, error_code: str, http_status: int = 502) -> None:
        super().__init__(SAFE_MANAGEMENT_ERROR_MESSAGE)
        self.error_code = _sanitize_error_code(error_code)
        self.http_status = http_status


def restart_whatsapp_channel(*, channel: WhatsAppChannel, client=None) -> WhatsAppChannel:
    """Reinicia a instancia e move o canal para um estado transitorio coerente."""
    _guard_not_in_lifecycle(channel, operation='restart')
    resolved_client = client or get_evolution_client()
    try:
        resolved_client.restart_instance(instance_name=channel.instance_name)
    except EvolutionAPIError as exc:
        raise _safe_error(channel, operation='restart', exc=exc) from exc

    channel.status = WhatsAppChannel.Status.RECONNECTING
    channel.last_connection_update_at = timezone.now()
    channel.save()
    return channel


def disconnect_whatsapp_channel(*, channel: WhatsAppChannel, client=None) -> WhatsAppChannel:
    """
    Desconecta a instancia. Idempotente: canal ja `DISCONNECTED` retorna sem
    chamar a Evolution.
    """
    if channel.status == WhatsAppChannel.Status.DISCONNECTED:
        return channel

    _guard_not_in_lifecycle(channel, operation='disconnect')
    resolved_client = client or get_evolution_client()
    try:
        resolved_client.logout_instance(instance_name=channel.instance_name)
    except EvolutionAPIError as exc:
        raise _safe_error(channel, operation='disconnect', exc=exc) from exc

    channel.status = WhatsAppChannel.Status.DISCONNECTED
    channel.phone_number = ''
    channel.connected_at = None
    channel.last_connection_update_at = timezone.now()
    channel.save()
    return channel


def remove_whatsapp_channel(*, channel: WhatsAppChannel, client=None) -> None:
    """
    Remove o canal. A limpeza remota e best-effort: uma falha na Evolution e
    registrada mas **nao** bloqueia a remocao local, para nunca deixar o canal
    preso em `DELETING`. Conversas viram legado (`SET_NULL`); eventos de webhook
    caem por `CASCADE`.
    """
    resolved_client = client or get_evolution_client()

    channel.status = WhatsAppChannel.Status.DELETING
    channel.save()

    try:
        resolved_client.delete_instance(instance_name=channel.instance_name)
    except Exception as exc:
        logger.warning(
            'Remocao remota da instancia Evolution falhou; prosseguindo com remocao local',
            extra={
                'workspace_id': str(channel.workspace_id),
                'channel_id': str(channel.id),
                'operation': 'remove_whatsapp_channel',
                'status': channel.status,
                'error_code': 'EVOLUTION_REMOTE_DELETE_FAILED',
                'exception_type': type(exc).__name__,
            },
        )

    with transaction.atomic():
        channel.delete()


def _guard_not_in_lifecycle(channel: WhatsAppChannel, *, operation: str) -> None:
    if channel.status in _BLOCKED_MANAGEMENT_STATES:
        raise WhatsAppChannelManagementError(
            error_code='CHANNEL_STATE_CONFLICT',
            http_status=409,
        )


def _safe_error(
    channel: WhatsAppChannel,
    *,
    operation: str,
    exc: EvolutionAPIError,
) -> WhatsAppChannelManagementError:
    logger.warning(
        'Acao de gestao do canal falhou na Evolution',
        extra={
            'workspace_id': str(channel.workspace_id),
            'channel_id': str(channel.id),
            'operation': operation,
            'status': channel.status,
            'error_code': _sanitize_error_code(exc.error_code),
            'exception_type': type(exc).__name__,
        },
    )
    return WhatsAppChannelManagementError(error_code=exc.error_code, http_status=502)
