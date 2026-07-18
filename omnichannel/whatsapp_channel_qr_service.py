from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from omnichannel.evolution import (
    BaseEvolutionClient,
    EvolutionAPIError,
    EvolutionAuthenticationError,
    EvolutionConfigurationError,
    EvolutionConnectionError,
    EvolutionInvalidRequestError,
    EvolutionInvalidResponseError,
    EvolutionNotFoundError,
    EvolutionRateLimitError,
    EvolutionTimeoutError,
    EvolutionUnavailableError,
    EvolutionUnexpectedResponseError,
    get_evolution_client,
)
from omnichannel.evolution.exceptions import EvolutionConflictError
from omnichannel.evolution_qr_cache import (
    EvolutionQRCodeCacheError,
    delete_evolution_qr_code,
    extract_evolution_qr_code,
    get_evolution_qr_code,
    get_qr_code_format,
    store_evolution_qr_code,
)
from omnichannel.models import WhatsAppChannel

logger = logging.getLogger(__name__)

SAFE_QR_ERROR_DETAIL = 'N\u00e3o foi poss\u00edvel obter o QR Code.'
SAFE_QR_CACHE_ERROR_DETAIL = 'QR Code temporariamente indispon\u00edvel.'


@dataclass(frozen=True, slots=True)
class WhatsAppChannelQRCodeResult:
    channel_id: UUID
    status: str
    has_qr_code: bool
    qr_code: str | None
    qr_format: str | None
    source: str | None = None


class WhatsAppChannelQRCodeError(Exception):
    def __init__(self, *, error_code: str, http_status: int, detail: str) -> None:
        super().__init__('WhatsApp channel QR read failed.')
        self.error_code = _sanitize_error_code(error_code)
        self.http_status = http_status
        self.detail = detail


def get_whatsapp_channel_qr_code(
    *,
    channel: WhatsAppChannel,
    client: BaseEvolutionClient | None = None,
) -> WhatsAppChannelQRCodeResult:
    if channel.status != WhatsAppChannel.Status.WAITING_QR:
        if channel.status == WhatsAppChannel.Status.CONNECTED:
            _delete_qr_best_effort(channel=channel, operation='delete_connected_residual_qr')
        return _empty_result(channel_id=channel.id, status=channel.status)

    try:
        cached_qr = get_evolution_qr_code(channel.id)
    except EvolutionQRCodeCacheError as exc:
        _raise_cache_error(channel=channel, exc=exc, operation='read_qr_cache')

    if cached_qr is not None:
        current_status = _get_current_status(channel)
        if current_status != WhatsAppChannel.Status.WAITING_QR:
            _delete_qr_best_effort(channel=channel, operation='delete_stale_cached_qr')
            return _empty_result(channel_id=channel.id, status=current_status or channel.status)
        _log_qr_result(channel=channel, source='cache', cache_hit=True)
        return _available_result(channel=channel, status=current_status, qr_code=cached_qr, source='cache')

    status_before_remote = _get_current_status(channel)
    if status_before_remote != WhatsAppChannel.Status.WAITING_QR:
        if status_before_remote == WhatsAppChannel.Status.CONNECTED:
            _delete_qr_best_effort(
                channel=channel,
                operation='delete_connected_residual_qr_before_fallback',
            )
        return _empty_result(
            channel_id=channel.id,
            status=status_before_remote or channel.status,
        )

    try:
        resolved_client = client if client is not None else get_evolution_client()
        remote_response = resolved_client.get_qr_code(instance_name=channel.instance_name)
    except EvolutionAPIError as exc:
        _raise_evolution_error(channel=channel, exc=exc)
    except Exception as exc:
        _log_qr_failure(
            channel=channel,
            operation='get_evolution_qr_code',
            error_code='EVOLUTION_REQUEST_ERROR',
            exception_type=type(exc).__name__,
            remote_fallback_attempted=True,
        )
        raise WhatsAppChannelQRCodeError(
            error_code='EVOLUTION_REQUEST_ERROR',
            http_status=502,
            detail=SAFE_QR_ERROR_DETAIL,
        ) from None

    remote_qr = extract_evolution_qr_code(remote_response)
    if remote_qr is None:
        current_status = _get_current_status(channel) or channel.status
        _log_qr_result(
            channel=channel,
            source='evolution',
            cache_hit=False,
            remote_fallback_attempted=True,
            has_qr_code=False,
        )
        return _empty_result(channel_id=channel.id, status=current_status)

    status_before_cache = _get_current_status(channel)
    if status_before_cache != WhatsAppChannel.Status.WAITING_QR:
        _delete_qr_best_effort(channel=channel, operation='delete_remote_qr_after_state_change')
        return _empty_result(
            channel_id=channel.id,
            status=status_before_cache or channel.status,
        )

    try:
        store_evolution_qr_code(channel.id, remote_qr)
    except EvolutionQRCodeCacheError as exc:
        _raise_cache_error(channel=channel, exc=exc, operation='store_remote_qr_cache')

    status_after_cache = _get_current_status(channel)
    if status_after_cache != WhatsAppChannel.Status.WAITING_QR:
        _delete_qr_best_effort(channel=channel, operation='delete_cached_qr_after_state_change')
        return _empty_result(
            channel_id=channel.id,
            status=status_after_cache or channel.status,
        )

    _log_qr_result(
        channel=channel,
        source='evolution',
        cache_hit=False,
        remote_fallback_attempted=True,
    )
    return _available_result(
        channel=channel,
        status=status_after_cache,
        qr_code=remote_qr,
        source='evolution',
    )


def _get_current_status(channel: WhatsAppChannel) -> str | None:
    return (
        WhatsAppChannel.objects.filter(
            id=channel.id,
            workspace_id=channel.workspace_id,
        )
        .values_list('status', flat=True)
        .first()
    )


def _available_result(
    *,
    channel: WhatsAppChannel,
    status: str,
    qr_code: str,
    source: str,
) -> WhatsAppChannelQRCodeResult:
    return WhatsAppChannelQRCodeResult(
        channel_id=channel.id,
        status=status,
        has_qr_code=True,
        qr_code=qr_code,
        qr_format=get_qr_code_format(qr_code),
        source=source,
    )


def _empty_result(*, channel_id: UUID, status: str) -> WhatsAppChannelQRCodeResult:
    return WhatsAppChannelQRCodeResult(
        channel_id=channel_id,
        status=status,
        has_qr_code=False,
        qr_code=None,
        qr_format=None,
    )


def _delete_qr_best_effort(*, channel: WhatsAppChannel, operation: str) -> None:
    try:
        delete_evolution_qr_code(channel.id)
    except EvolutionQRCodeCacheError as exc:
        _log_qr_failure(
            channel=channel,
            operation=operation,
            error_code=exc.error_code,
            exception_type=type(exc).__name__,
        )


def _raise_cache_error(
    *,
    channel: WhatsAppChannel,
    exc: EvolutionQRCodeCacheError,
    operation: str,
) -> None:
    _log_qr_failure(
        channel=channel,
        operation=operation,
        error_code='QR_CACHE_UNAVAILABLE',
        exception_type=type(exc).__name__,
    )
    raise WhatsAppChannelQRCodeError(
        error_code='QR_CACHE_UNAVAILABLE',
        http_status=503,
        detail=SAFE_QR_CACHE_ERROR_DETAIL,
    ) from None


def _raise_evolution_error(*, channel: WhatsAppChannel, exc: EvolutionAPIError) -> None:
    if isinstance(exc, EvolutionTimeoutError):
        http_status = 504
    elif isinstance(
        exc,
        (
            EvolutionAuthenticationError,
            EvolutionConfigurationError,
            EvolutionConnectionError,
            EvolutionRateLimitError,
            EvolutionUnavailableError,
        ),
    ):
        http_status = 503
    elif isinstance(
        exc,
        (
            EvolutionConflictError,
            EvolutionInvalidRequestError,
            EvolutionInvalidResponseError,
            EvolutionNotFoundError,
            EvolutionUnexpectedResponseError,
        ),
    ):
        http_status = 502
    else:
        http_status = 502
    error_code = _sanitize_error_code(getattr(exc, 'error_code', 'EVOLUTION_REQUEST_ERROR'))
    _log_qr_failure(
        channel=channel,
        operation='get_evolution_qr_code',
        error_code=error_code,
        exception_type=type(exc).__name__,
        remote_fallback_attempted=True,
    )
    raise WhatsAppChannelQRCodeError(
        error_code=error_code,
        http_status=http_status,
        detail=SAFE_QR_ERROR_DETAIL,
    ) from None


def _log_qr_result(
    *,
    channel: WhatsAppChannel,
    source: str,
    cache_hit: bool,
    remote_fallback_attempted: bool = False,
    has_qr_code: bool = True,
) -> None:
    logger.info(
        'Consulta segura de QR do canal concluida',
        extra={
            'workspace_id': str(channel.workspace_id),
            'channel_id': str(channel.id),
            'operation': 'get_whatsapp_channel_qr_code',
            'status': channel.status,
            'has_qr_code': has_qr_code,
            'qr_source': source,
            'cache_hit': cache_hit,
            'remote_fallback_attempted': remote_fallback_attempted,
        },
    )


def _log_qr_failure(
    *,
    channel: WhatsAppChannel,
    operation: str,
    error_code: str,
    exception_type: str,
    remote_fallback_attempted: bool = False,
) -> None:
    logger.warning(
        'Falha segura na consulta de QR do canal',
        extra={
            'workspace_id': str(channel.workspace_id),
            'channel_id': str(channel.id),
            'operation': operation,
            'status': channel.status,
            'error_code': _sanitize_error_code(error_code),
            'exception_type': exception_type,
            'remote_fallback_attempted': remote_fallback_attempted,
        },
    )


def _sanitize_error_code(value: Any) -> str:
    normalized = re.sub(r'[^A-Z0-9]+', '_', str(value or 'EVOLUTION_REQUEST_ERROR').upper())
    return normalized.strip('_')[:64] or 'EVOLUTION_REQUEST_ERROR'
