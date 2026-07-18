from __future__ import annotations

import logging
import re
from collections.abc import Iterable
from uuid import UUID

from django.core.cache import cache

from omnichannel.evolution_qr_cache import (
    EvolutionQRCodeCacheError,
    delete_evolution_qr_code,
    get_evolution_qr_cache_key,
    get_evolution_qr_code,
    normalize_evolution_qr_code,
)
from omnichannel.models import WhatsAppChannel

logger = logging.getLogger(__name__)

_PHONE_PATTERN = re.compile(r'^\d{8,20}$')
_PHONE_MASK_PREFIX = '********'


def mask_whatsapp_phone_number(phone_number: object) -> str | None:
    if not isinstance(phone_number, str) or not _PHONE_PATTERN.fullmatch(phone_number):
        return None
    return f'{_PHONE_MASK_PREFIX}{phone_number[-4:]}'


def get_channels_qr_availability(
    channels: Iterable[WhatsAppChannel],
) -> dict[UUID, bool]:
    channel_list = list(channels)
    result = {channel.id: False for channel in channel_list}
    keys_by_channel = {
        channel.id: get_evolution_qr_cache_key(channel.id)
        for channel in channel_list
    }
    try:
        cached_values = cache.get_many(keys_by_channel.values())
    except Exception as exc:
        _log_cache_failure(
            operation='read_whatsapp_channel_qr_availability',
            exception_type=type(exc).__name__,
        )
        return result

    for channel in channel_list:
        cached_qr = normalize_evolution_qr_code(cached_values.get(keys_by_channel[channel.id]))
        if channel.status == WhatsAppChannel.Status.WAITING_QR:
            result[channel.id] = cached_qr is not None
        elif channel.status == WhatsAppChannel.Status.CONNECTED and cached_qr is not None:
            _delete_residual_qr_best_effort(channel)
    return result


def get_channel_qr_availability(channel: WhatsAppChannel) -> bool:
    try:
        cached_qr = get_evolution_qr_code(channel.id)
    except EvolutionQRCodeCacheError as exc:
        _log_cache_failure(
            operation='read_whatsapp_channel_qr_availability',
            exception_type=type(exc).__name__,
            channel=channel,
        )
        return False

    if channel.status == WhatsAppChannel.Status.WAITING_QR:
        return cached_qr is not None
    if channel.status == WhatsAppChannel.Status.CONNECTED and cached_qr is not None:
        _delete_residual_qr_best_effort(channel)
    return False


def _delete_residual_qr_best_effort(channel: WhatsAppChannel) -> None:
    try:
        delete_evolution_qr_code(channel.id)
    except EvolutionQRCodeCacheError as exc:
        _log_cache_failure(
            operation='delete_residual_whatsapp_channel_qr',
            exception_type=type(exc).__name__,
            channel=channel,
        )


def _log_cache_failure(
    *,
    operation: str,
    exception_type: str,
    channel: WhatsAppChannel | None = None,
) -> None:
    extra = {
        'operation': operation,
        'exception_type': exception_type,
    }
    if channel is not None:
        extra.update(
            {
                'workspace_id': str(channel.workspace_id),
                'channel_id': str(channel.id),
                'status': channel.status,
            },
        )
    logger.warning('Falha segura ao consultar cache de QR do canal', extra=extra)
