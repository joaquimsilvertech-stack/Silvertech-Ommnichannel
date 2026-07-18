from __future__ import annotations

import re
import secrets
import unicodedata
from urllib.parse import urlsplit
from uuid import UUID

from django.conf import settings
from django.urls import reverse

from omnichannel.models import WhatsAppChannel

EVOLUTION_WEBHOOK_SECRET_HEADER = 'X-SilverTech-Webhook-Secret'
EVOLUTION_CHANNEL_WEBHOOK_EVENTS = (
    'QRCODE_UPDATED',
    'CONNECTION_UPDATE',
    'MESSAGES_UPSERT',
    'MESSAGES_UPDATE',
    'SEND_MESSAGE',
)
WEBHOOK_SECRET_ENTROPY_BYTES = 32
MAX_WEBHOOK_SECRET_HEADER_LENGTH = 512
DUMMY_WEBHOOK_SECRET = 'silvertech-webhook-authentication-dummy-value'


class EvolutionWebhookConfigurationError(Exception):
    """Erro seguro de configuracao da URL publica do webhook."""

    def __init__(self, error_code: str) -> None:
        super().__init__('Configuracao publica do webhook invalida.')
        self.error_code = error_code


def generate_webhook_secret() -> str:
    """Gera um segredo individual com pelo menos 256 bits de entropia."""
    secret = secrets.token_urlsafe(WEBHOOK_SECRET_ENTROPY_BYTES)
    max_length = WhatsAppChannel._meta.get_field('webhook_secret').max_length
    if (
        not secret
        or max_length is not None and len(secret) > max_length
        or any(unicodedata.category(character) == 'Cc' for character in secret)
    ):
        raise RuntimeError('Nao foi possivel gerar um segredo de webhook valido.')
    return secret


def build_evolution_channel_webhook_url(*, webhook_public_id: UUID) -> str:
    """Constroi a URL exclusivamente a partir da configuracao confiavel."""
    configured_value = getattr(settings, 'EVOLUTION_WEBHOOK_PUBLIC_BASE_URL', '')
    if not isinstance(configured_value, str) or not configured_value.strip():
        raise EvolutionWebhookConfigurationError(
            'WEBHOOK_PUBLIC_BASE_URL_NOT_CONFIGURED',
        )

    base_url = configured_value.strip()
    if (
        base_url != configured_value
        or any(character.isspace() for character in base_url)
        or any(unicodedata.category(character) == 'Cc' for character in base_url)
    ):
        raise EvolutionWebhookConfigurationError('WEBHOOK_PUBLIC_BASE_URL_INVALID')

    try:
        parsed = urlsplit(base_url)
        parsed_port = parsed.port
    except (TypeError, ValueError):
        raise EvolutionWebhookConfigurationError(
            'WEBHOOK_PUBLIC_BASE_URL_INVALID',
        ) from None

    if (
        parsed.scheme.lower() not in {'http', 'https'}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or parsed_port is not None and not 1 <= parsed_port <= 65535
    ):
        raise EvolutionWebhookConfigurationError('WEBHOOK_PUBLIC_BASE_URL_INVALID')

    if getattr(settings, 'IS_PRODUCTION', False) and parsed.scheme.lower() != 'https':
        raise EvolutionWebhookConfigurationError(
            'WEBHOOK_PUBLIC_BASE_URL_HTTPS_REQUIRED',
        )

    route = reverse(
        'evolution-channel-webhook',
        kwargs={'webhook_public_id': webhook_public_id},
    )
    return f'{base_url.rstrip("/")}{route}'


def sanitize_evolution_webhook_event(value: object) -> str:
    """Permite em logs somente eventos conhecidos do contrato configurado."""
    if not isinstance(value, str):
        return 'UNKNOWN_EVENT'
    normalized = re.sub(r'[^A-Z0-9_]+', '_', value.upper()).strip('_')[:64]
    if normalized in EVOLUTION_CHANNEL_WEBHOOK_EVENTS:
        return normalized
    return 'UNSUPPORTED_EVENT'
