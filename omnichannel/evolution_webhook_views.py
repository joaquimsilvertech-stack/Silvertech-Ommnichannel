from __future__ import annotations

import codecs
import hashlib
import json
import logging
import secrets
import unicodedata
from typing import Any

from django.conf import settings
from django.core.cache import cache
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.throttling import SimpleRateThrottle
from rest_framework.views import APIView

from omnichannel.evolution_webhook import (
    DUMMY_WEBHOOK_SECRET,
    EVOLUTION_WEBHOOK_SECRET_HEADER,
    MAX_WEBHOOK_SECRET_HEADER_LENGTH,
    sanitize_evolution_webhook_event,
)
from omnichannel.models import WhatsAppChannel
from omnichannel.tasks import process_evolution_channel_webhook_task

logger = logging.getLogger(__name__)

INVALID_WEBHOOK_RESPONSE = {'detail': 'Webhook inválido.'}
INVALID_PAYLOAD_RESPONSE = {'detail': 'Payload inválido.'}
TEMPORARILY_UNAVAILABLE_RESPONSE = {
    'detail': 'Webhook temporariamente indisponível.',
}
RECEIVED_RESPONSE = {'status': 'received'}


class _WebhookRequestError(Exception):
    def __init__(self, status_code: int, payload: dict[str, str]) -> None:
        super().__init__('Requisicao de webhook invalida.')
        self.status_code = status_code
        self.payload = payload


class EvolutionChannelWebhookThrottle(SimpleRateThrottle):
    scope = 'evolution_channel_webhook'

    def get_cache_key(self, request: Request, view: APIView) -> str | None:
        if request.method != 'POST':
            return None
        webhook_public_id = str(view.kwargs.get('webhook_public_id', '')).lower()
        ident = self.get_ident(request)
        return self.cache_format % {
            'scope': self.scope,
            'ident': f'{webhook_public_id}:{ident}',
        }


class EvolutionChannelWebhookView(APIView):
    authentication_classes: list[type] = []
    permission_classes = [AllowAny]
    throttle_classes = [EvolutionChannelWebhookThrottle]
    http_method_names = ['post', 'options']

    def post(self, request: Request, webhook_public_id) -> Response:
        try:
            payload = _read_limited_json_object(request)
        except _WebhookRequestError as exc:
            return Response(exc.payload, status=exc.status_code)

        try:
            channel = WhatsAppChannel.objects.select_related('workspace').filter(
                webhook_public_id=webhook_public_id,
            ).first()
        except Exception as exc:
            _log_operational_failure(
                operation='resolve_webhook_channel',
                exception_type=type(exc).__name__,
            )
            return Response(
                TEMPORARILY_UNAVAILABLE_RESPONSE,
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        provided_secret = request.headers.get(EVOLUTION_WEBHOOK_SECRET_HEADER, '')
        authenticated = _authenticate_channel_secret(
            channel=channel,
            provided_secret=provided_secret,
        )
        if not authenticated or channel is None:
            logger.warning(
                'Tentativa de webhook Evolution rejeitada',
                extra={
                    'operation': 'authenticate_evolution_channel_webhook',
                    'error_code': 'WEBHOOK_AUTH_FAILED',
                },
            )
            return Response(
                INVALID_WEBHOOK_RESPONSE,
                status=status.HTTP_404_NOT_FOUND,
            )

        if not _payload_instance_matches_channel(payload=payload, channel=channel):
            return Response(
                INVALID_PAYLOAD_RESPONSE,
                status=status.HTTP_400_BAD_REQUEST,
            )

        cache_key = _build_deduplication_cache_key(
            channel_id=str(channel.id),
            payload=payload,
        )
        dedup_ttl = _positive_integer_setting(
            'EVOLUTION_WEBHOOK_DEDUP_TTL_SECONDS',
        )
        if dedup_ttl is None:
            return Response(
                TEMPORARILY_UNAVAILABLE_RESPONSE,
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        try:
            reserved = cache.add(cache_key, '1', timeout=dedup_ttl)
        except Exception as exc:
            _log_authenticated_failure(
                channel=channel,
                operation='reserve_webhook_deduplication',
                exception_type=type(exc).__name__,
            )
            return Response(
                TEMPORARILY_UNAVAILABLE_RESPONSE,
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        event_type = sanitize_evolution_webhook_event(payload.get('event'))
        if not reserved:
            logger.info(
                'Webhook Evolution duplicado reconhecido',
                extra={
                    'channel_id': str(channel.id),
                    'workspace_id': str(channel.workspace_id),
                    'operation': 'receive_evolution_channel_webhook',
                    'event_type': event_type,
                    'duplicate': True,
                    'queue_succeeded': False,
                },
            )
            return Response(RECEIVED_RESPONSE, status=status.HTTP_200_OK)

        try:
            process_evolution_channel_webhook_task.delay(
                str(channel.id),
                payload,
            )
        except Exception as exc:
            try:
                cache.delete(cache_key)
            except Exception as cache_exc:
                _log_authenticated_failure(
                    channel=channel,
                    operation='release_webhook_deduplication',
                    exception_type=type(cache_exc).__name__,
                )
            _log_authenticated_failure(
                channel=channel,
                operation='enqueue_evolution_channel_webhook',
                exception_type=type(exc).__name__,
            )
            return Response(
                TEMPORARILY_UNAVAILABLE_RESPONSE,
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        logger.info(
            'Webhook Evolution autenticado e enfileirado',
            extra={
                'channel_id': str(channel.id),
                'workspace_id': str(channel.workspace_id),
                'operation': 'receive_evolution_channel_webhook',
                'event_type': event_type,
                'duplicate': False,
                'queue_succeeded': True,
            },
        )
        return Response(RECEIVED_RESPONSE, status=status.HTTP_200_OK)


def _read_limited_json_object(request: Request) -> dict[str, Any]:
    max_body_bytes = _positive_integer_setting('EVOLUTION_WEBHOOK_MAX_BODY_BYTES')
    if max_body_bytes is None:
        raise _WebhookRequestError(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            TEMPORARILY_UNAVAILABLE_RESPONSE,
        )

    encoding = _validate_json_content_type(request)
    raw_content_length = request.META.get('CONTENT_LENGTH', '')
    if raw_content_length not in (None, ''):
        try:
            content_length = int(raw_content_length)
        except (TypeError, ValueError):
            raise _invalid_payload_error() from None
        if content_length < 0:
            raise _invalid_payload_error()
        if content_length > max_body_bytes:
            raise _payload_too_large_error()

    try:
        body = request.body
    except Exception:
        raise _invalid_payload_error() from None
    if not isinstance(body, bytes) or not body:
        raise _invalid_payload_error()
    if len(body) > max_body_bytes:
        raise _payload_too_large_error()

    try:
        payload = json.loads(body.decode(encoding))
    except (LookupError, UnicodeDecodeError, json.JSONDecodeError):
        raise _invalid_payload_error() from None
    if not isinstance(payload, dict):
        raise _invalid_payload_error()
    return payload


def _validate_json_content_type(request: Request) -> str:
    raw_content_type = request.META.get('CONTENT_TYPE', '')
    if not isinstance(raw_content_type, str):
        raise _unsupported_media_type_error()
    parts = [part.strip() for part in raw_content_type.split(';')]
    if not parts or parts[0].lower() != 'application/json':
        raise _unsupported_media_type_error()

    encoding = 'utf-8'
    charset_seen = False
    for parameter in parts[1:]:
        if not parameter or '=' not in parameter:
            raise _unsupported_media_type_error()
        key, value = parameter.split('=', maxsplit=1)
        value = value.strip().strip('"')
        if key.strip().lower() != 'charset' or charset_seen or not value:
            raise _unsupported_media_type_error()
        if any(unicodedata.category(character) == 'Cc' for character in value):
            raise _unsupported_media_type_error()
        try:
            encoding = codecs.lookup(value).name
        except LookupError:
            raise _unsupported_media_type_error() from None
        charset_seen = True
    return encoding


def _authenticate_channel_secret(
    *,
    channel: WhatsAppChannel | None,
    provided_secret: object,
) -> bool:
    header_is_valid = (
        isinstance(provided_secret, str)
        and bool(provided_secret)
        and len(provided_secret) <= MAX_WEBHOOK_SECRET_HEADER_LENGTH
        and not any(
            unicodedata.category(character) == 'Cc'
            for character in provided_secret
        )
    )
    expected_secret = (
        channel.webhook_secret
        if channel is not None and channel.webhook_secret
        else DUMMY_WEBHOOK_SECRET
    )
    digest_source = provided_secret if header_is_valid else DUMMY_WEBHOOK_SECRET
    provided_digest = hashlib.sha256(digest_source.encode('utf-8')).digest()
    expected_digest = hashlib.sha256(expected_secret.encode('utf-8')).digest()
    matches = secrets.compare_digest(provided_digest, expected_digest)
    return bool(
        channel is not None
        and channel.webhook_secret
        and header_is_valid
        and matches
    )


def _payload_instance_matches_channel(
    *,
    payload: dict[str, Any],
    channel: WhatsAppChannel,
) -> bool:
    if 'instance' not in payload:
        return True
    instance_name = payload.get('instance')
    return (
        isinstance(instance_name, str)
        and bool(instance_name)
        and instance_name == channel.instance_name
    )


def _build_deduplication_cache_key(
    *,
    channel_id: str,
    payload: dict[str, Any],
) -> str:
    canonical_payload = json.dumps(
        payload,
        sort_keys=True,
        separators=(',', ':'),
        ensure_ascii=False,
    ).encode('utf-8')
    digest = hashlib.sha256(canonical_payload).hexdigest()
    return f'evolution-webhook:{channel_id}:{digest}'


def _positive_integer_setting(name: str) -> int | None:
    value = getattr(settings, name, None)
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        _log_operational_failure(
            operation='validate_evolution_webhook_setting',
            exception_type='InvalidPositiveIntegerSetting',
        )
        return None
    return value


def _invalid_payload_error() -> _WebhookRequestError:
    return _WebhookRequestError(
        status.HTTP_400_BAD_REQUEST,
        INVALID_PAYLOAD_RESPONSE,
    )


def _payload_too_large_error() -> _WebhookRequestError:
    return _WebhookRequestError(
        status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
        {'detail': 'Payload muito grande.'},
    )


def _unsupported_media_type_error() -> _WebhookRequestError:
    return _WebhookRequestError(
        status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
        {'detail': 'Content-Type não suportado.'},
    )


def _log_operational_failure(*, operation: str, exception_type: str) -> None:
    logger.warning(
        'Falha operacional no webhook Evolution',
        extra={
            'operation': operation,
            'exception_type': exception_type,
        },
    )


def _log_authenticated_failure(
    *,
    channel: WhatsAppChannel,
    operation: str,
    exception_type: str,
) -> None:
    logger.warning(
        'Falha operacional no webhook Evolution autenticado',
        extra={
            'channel_id': str(channel.id),
            'workspace_id': str(channel.workspace_id),
            'operation': operation,
            'exception_type': exception_type,
        },
    )
