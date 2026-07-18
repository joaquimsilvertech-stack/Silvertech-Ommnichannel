from __future__ import annotations

import re
import unicodedata
from uuid import UUID

from django.conf import settings
from django.core.cache import cache

MAX_EVOLUTION_QR_CODE_LENGTH = 262_144
_RAW_BASE64_PATTERN = re.compile(r'^[A-Za-z0-9+/=_-]+$')
_DATA_URI_PATTERN = re.compile(
    r'^data:image/(?:png|jpeg|jpg|webp);base64,[A-Za-z0-9+/=_-]+$',
    re.IGNORECASE,
)


class EvolutionQRCodeCacheError(Exception):
    """Falha operacional segura no cache temporario do QR."""

    def __init__(self, error_code: str) -> None:
        super().__init__('Evolution QR cache operation failed.')
        self.error_code = error_code


def get_evolution_qr_cache_key(channel_id: UUID | str) -> str:
    """Gera uma chave sem Workspace, telefone, instancia ou outros dados sensiveis."""
    return f'evolution-qr:{channel_id}'


def normalize_evolution_qr_code(value: object) -> str | None:
    if not isinstance(value, str) or not value or len(value) > MAX_EVOLUTION_QR_CODE_LENGTH:
        return None
    if any(unicodedata.category(character) == 'Cc' for character in value):
        return None
    if value != value.strip():
        return None
    if _DATA_URI_PATTERN.fullmatch(value) or _RAW_BASE64_PATTERN.fullmatch(value):
        return value
    return None


def store_evolution_qr_code(channel_id: UUID | str, qr_code: object) -> None:
    normalized_qr = normalize_evolution_qr_code(qr_code)
    if normalized_qr is None:
        raise EvolutionQRCodeCacheError('INVALID_QR_CODE')

    ttl = getattr(settings, 'EVOLUTION_QR_TTL_SECONDS', None)
    if isinstance(ttl, bool) or not isinstance(ttl, int) or ttl <= 0:
        raise EvolutionQRCodeCacheError('INVALID_QR_CACHE_TTL')

    try:
        cache.set(
            get_evolution_qr_cache_key(channel_id),
            normalized_qr,
            timeout=ttl,
        )
    except Exception as exc:
        raise EvolutionQRCodeCacheError('QR_CACHE_UNAVAILABLE') from exc


def get_evolution_qr_code(channel_id: UUID | str) -> str | None:
    try:
        value = cache.get(get_evolution_qr_cache_key(channel_id))
    except Exception as exc:
        raise EvolutionQRCodeCacheError('QR_CACHE_UNAVAILABLE') from exc
    return normalize_evolution_qr_code(value)


def delete_evolution_qr_code(channel_id: UUID | str) -> None:
    try:
        cache.delete(get_evolution_qr_cache_key(channel_id))
    except Exception as exc:
        raise EvolutionQRCodeCacheError('QR_CACHE_UNAVAILABLE') from exc
