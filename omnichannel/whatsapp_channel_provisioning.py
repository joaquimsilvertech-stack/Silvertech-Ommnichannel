from __future__ import annotations

import logging
import re
import unicodedata
import uuid
from dataclasses import dataclass
from time import perf_counter
from typing import Any
from uuid import UUID

from django.db import IntegrityError, transaction

from omnichannel.evolution import (
    BaseEvolutionClient,
    EvolutionAPIError,
    EvolutionAuthenticationError,
    EvolutionConfigurationError,
    EvolutionConflictError,
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
from omnichannel.evolution_webhook import (
    EVOLUTION_CHANNEL_WEBHOOK_EVENTS,
    EVOLUTION_WEBHOOK_SECRET_HEADER,
    EvolutionWebhookConfigurationError,
    build_evolution_channel_webhook_url,
    generate_webhook_secret,
)
from omnichannel.models import AIObservabilityEvent, WhatsAppChannel
from omnichannel.observability import (
    PROVISIONING_ERROR_REASON,
    calculate_latency_ms,
    record_channel_observability_event_safe,
)
from workspaces.models import Workspace

logger = logging.getLogger(__name__)

MAX_INSTANCE_NAME_GENERATION_ATTEMPTS = 5
INSTANCE_NAME_PREFIX = 'st_'
EVOLUTION_INTEGRATION = 'WHATSAPP-BAILEYS'
SAFE_PROVISIONING_ERROR_MESSAGE = 'Nao foi possivel provisionar o canal WhatsApp.'


@dataclass(frozen=True, slots=True)
class WhatsAppChannelProvisioningResult:
    channel: WhatsAppChannel
    created: bool
    remote_instance_created: bool
    idempotent_reuse: bool


class WhatsAppChannelProvisioningError(Exception):
    """Falha operacional segura, sem payloads ou credenciais externas."""

    def __init__(
        self,
        *,
        error_code: str,
        channel_id: UUID | None = None,
        retryable: bool = False,
        http_status: int = 502,
    ) -> None:
        super().__init__(SAFE_PROVISIONING_ERROR_MESSAGE)
        self.error_code = _sanitize_error_code(error_code)
        self.channel_id = channel_id
        self.retryable = retryable
        self.http_status = http_status


@dataclass(frozen=True, slots=True)
class _ChannelReservation:
    channel: WhatsAppChannel
    created: bool


def provision_whatsapp_channel(
    *,
    workspace: Workspace,
    channel_name: str,
    client: BaseEvolutionClient | None = None,
) -> WhatsAppChannelProvisioningResult:
    """Provisiona uma instancia remota sem manter lock durante o HTTP."""
    provisioning_started_at = perf_counter()
    normalized_name = _normalize_channel_name(channel_name)
    reservation = _reserve_local_channel(
        workspace=workspace,
        channel_name=normalized_name,
    )
    channel = reservation.channel

    if not reservation.created:
        logger.info(
            'Provisionamento de canal reutilizado por idempotencia',
            extra={
                'workspace_id': str(channel.workspace_id),
                'channel_id': str(channel.id),
                'instance_name': channel.instance_name,
                'operation': 'provision_whatsapp_channel',
                'status': channel.status,
            },
        )
        return WhatsAppChannelProvisioningResult(
            channel=channel,
            created=False,
            remote_instance_created=False,
            idempotent_reuse=True,
        )

    record_channel_observability_event_safe(
        workspace=channel.workspace,
        channel=channel,
        event_type=AIObservabilityEvent.EventType.CHANNEL_CREATED,
        status=AIObservabilityEvent.Status.SUCCESS,
        metadata={'action': 'provision'},
    )

    try:
        webhook_url = build_evolution_channel_webhook_url(
            webhook_public_id=channel.webhook_public_id,
        )
    except EvolutionWebhookConfigurationError as exc:
        error_code = _sanitize_error_code(exc.error_code)
        _mark_channel_error_safely(channel=channel, error_code=error_code)
        logger.warning(
            'Configuracao publica do webhook Evolution invalida',
            extra={
                'workspace_id': str(channel.workspace_id),
                'channel_id': str(channel.id),
                'instance_name': channel.instance_name,
                'operation': 'build_evolution_webhook_url',
                'status': WhatsAppChannel.Status.ERROR,
                'error_code': error_code,
                'exception_type': type(exc).__name__,
                'remote_cleanup_attempted': False,
                'remote_cleanup_succeeded': False,
            },
        )
        raise WhatsAppChannelProvisioningError(
            error_code=error_code,
            channel_id=channel.id,
            http_status=503,
        ) from None

    resolved_client = client
    try:
        if resolved_client is None:
            resolved_client = get_evolution_client()
        response = resolved_client.create_instance(
            instance_name=channel.instance_name,
            qrcode=True,
            integration=EVOLUTION_INTEGRATION,
        )
    except EvolutionAPIError as exc:
        _raise_remote_provisioning_error(
            channel=channel,
            client=resolved_client,
            exc=exc,
        )
    except Exception as exc:
        _mark_channel_error_safely(channel=channel, error_code='EVOLUTION_UNKNOWN_ERROR')
        logger.warning(
            'Falha inesperada ao criar instancia Evolution',
            extra={
                'workspace_id': str(channel.workspace_id),
                'channel_id': str(channel.id),
                'instance_name': channel.instance_name,
                'operation': 'create_instance',
                'status': WhatsAppChannel.Status.ERROR,
                'error_code': 'EVOLUTION_UNKNOWN_ERROR',
                'exception_type': type(exc).__name__,
                'remote_cleanup_attempted': False,
                'remote_cleanup_succeeded': False,
            },
        )
        raise WhatsAppChannelProvisioningError(
            error_code='EVOLUTION_UNKNOWN_ERROR',
            channel_id=channel.id,
            http_status=502,
        ) from None

    record_channel_observability_event_safe(
        workspace=channel.workspace,
        channel=channel,
        event_type=AIObservabilityEvent.EventType.CHANNEL_PROVISIONED,
        status=AIObservabilityEvent.Status.SUCCESS,
        metadata={'action': 'provision'},
    )

    try:
        resolved_client.configure_webhook(
            instance_name=channel.instance_name,
            url=webhook_url,
            events=list(EVOLUTION_CHANNEL_WEBHOOK_EVENTS),
            enabled=True,
            webhook_by_events=False,
            headers={
                EVOLUTION_WEBHOOK_SECRET_HEADER: channel.webhook_secret,
            },
        )
    except EvolutionAPIError as exc:
        _raise_post_creation_error(
            channel=channel,
            client=resolved_client,
            error_code=exc.error_code,
            retryable=bool(exc.retryable),
            http_status=_evolution_error_http_status(exc),
            operation='configure_webhook',
            exception_type=type(exc).__name__,
        )
    except Exception as exc:
        _raise_post_creation_error(
            channel=channel,
            client=resolved_client,
            error_code='EVOLUTION_WEBHOOK_CONFIGURATION_FAILED',
            retryable=False,
            http_status=502,
            operation='configure_webhook',
            exception_type=type(exc).__name__,
        )

    record_channel_observability_event_safe(
        workspace=channel.workspace,
        channel=channel,
        event_type=AIObservabilityEvent.EventType.CHANNEL_WEBHOOK_CONFIGURED,
        status=AIObservabilityEvent.Status.SUCCESS,
        metadata={'action': 'provision'},
    )

    try:
        instance_id, instance_token = _extract_safe_instance_credentials(response)
        finalized_channel = _finalize_local_channel(
            channel=channel,
            instance_id=instance_id,
            instance_token=instance_token,
        )
    except Exception as exc:
        cleanup_attempted, cleanup_succeeded = _attempt_remote_cleanup(
            client=resolved_client,
            channel=channel,
        )
        if isinstance(exc, (EvolutionAPIError, WhatsAppChannelProvisioningError)):
            error_code = _sanitize_error_code(exc.error_code)
        else:
            error_code = 'CHANNEL_FINALIZATION_FAILED'
        _mark_channel_error_safely(channel=channel, error_code=error_code)
        logger.warning(
            'Falha ao finalizar provisionamento local do canal',
            extra={
                'workspace_id': str(channel.workspace_id),
                'channel_id': str(channel.id),
                'instance_name': channel.instance_name,
                'operation': 'finalize_whatsapp_channel',
                'status': WhatsAppChannel.Status.ERROR,
                'error_code': error_code,
                'exception_type': type(exc).__name__,
                'remote_cleanup_attempted': cleanup_attempted,
                'remote_cleanup_succeeded': cleanup_succeeded,
            },
        )
        raise WhatsAppChannelProvisioningError(
            error_code=error_code,
            channel_id=channel.id,
            http_status=(
                exc.http_status
                if isinstance(exc, WhatsAppChannelProvisioningError)
                else 502 if isinstance(exc, EvolutionAPIError) else 500
            ),
        ) from None

    record_channel_observability_event_safe(
        workspace=finalized_channel.workspace,
        channel=finalized_channel,
        event_type=AIObservabilityEvent.EventType.CHANNEL_QR_GENERATED,
        status=AIObservabilityEvent.Status.SUCCESS,
        latency_ms=calculate_latency_ms(provisioning_started_at),
        metadata={'action': 'provision'},
    )

    logger.info(
        'Canal WhatsApp provisionado na Evolution',
        extra={
            'workspace_id': str(finalized_channel.workspace_id),
            'channel_id': str(finalized_channel.id),
            'instance_name': finalized_channel.instance_name,
            'operation': 'provision_whatsapp_channel',
            'status': finalized_channel.status,
        },
    )
    return WhatsAppChannelProvisioningResult(
        channel=finalized_channel,
        created=True,
        remote_instance_created=True,
        idempotent_reuse=False,
    )


def _reserve_local_channel(
    *,
    workspace: Workspace,
    channel_name: str,
) -> _ChannelReservation:
    with transaction.atomic():
        try:
            locked_workspace = Workspace.objects.select_for_update().get(pk=workspace.pk)
        except Workspace.DoesNotExist:
            raise WhatsAppChannelProvisioningError(
                error_code='WORKSPACE_NOT_FOUND',
                http_status=404,
            ) from None

        existing = WhatsAppChannel.objects.filter(
            workspace=locked_workspace,
            name=channel_name,
        ).first()
        if existing is not None:
            return _ChannelReservation(channel=existing, created=False)

        for _ in range(MAX_INSTANCE_NAME_GENERATION_ATTEMPTS):
            instance_name = _generate_instance_name()
            try:
                webhook_secret = generate_webhook_secret()
            except Exception as exc:
                logger.warning(
                    'Falha ao gerar segredo individual do webhook',
                    extra={
                        'workspace_id': str(locked_workspace.id),
                        'operation': 'generate_webhook_secret',
                        'error_code': 'WEBHOOK_SECRET_GENERATION_FAILED',
                        'exception_type': type(exc).__name__,
                    },
                )
                raise WhatsAppChannelProvisioningError(
                    error_code='WEBHOOK_SECRET_GENERATION_FAILED',
                    http_status=500,
                ) from None
            try:
                with transaction.atomic():
                    channel = WhatsAppChannel.objects.create(
                        workspace=locked_workspace,
                        provider=WhatsAppChannel.Provider.EVOLUTION,
                        name=channel_name,
                        instance_name=instance_name,
                        instance_id='',
                        instance_token='',
                        webhook_secret=webhook_secret,
                        status=WhatsAppChannel.Status.PROVISIONING,
                        phone_number='',
                        connected_at=None,
                        last_connection_update_at=None,
                        last_error_code='',
                    )
            except IntegrityError:
                existing = WhatsAppChannel.objects.filter(
                    workspace=locked_workspace,
                    name=channel_name,
                ).first()
                if existing is not None:
                    return _ChannelReservation(channel=existing, created=False)
                continue
            return _ChannelReservation(channel=channel, created=True)

    raise WhatsAppChannelProvisioningError(
        error_code='INSTANCE_NAME_GENERATION_FAILED',
        http_status=503,
    )


def _finalize_local_channel(
    *,
    channel: WhatsAppChannel,
    instance_id: str,
    instance_token: str,
) -> WhatsAppChannel:
    with transaction.atomic():
        try:
            locked_channel = WhatsAppChannel.objects.select_for_update().get(pk=channel.pk)
        except WhatsAppChannel.DoesNotExist:
            raise WhatsAppChannelProvisioningError(
                error_code='CHANNEL_NOT_FOUND_DURING_FINALIZATION',
                channel_id=channel.id,
                http_status=500,
            ) from None

        if (
            locked_channel.workspace_id != channel.workspace_id
            or locked_channel.instance_name != channel.instance_name
            or locked_channel.status != WhatsAppChannel.Status.PROVISIONING
        ):
            raise WhatsAppChannelProvisioningError(
                error_code='CHANNEL_STATE_CONFLICT',
                channel_id=channel.id,
                http_status=409,
            )

        locked_channel.instance_id = instance_id
        locked_channel.instance_token = instance_token
        locked_channel.status = WhatsAppChannel.Status.WAITING_QR
        locked_channel.last_error_code = ''
        locked_channel.save(
            update_fields=[
                'instance_id',
                'instance_token',
                'status',
                'last_error_code',
                'updated_at',
            ],
        )
        return locked_channel


def _raise_remote_provisioning_error(
    *,
    channel: WhatsAppChannel,
    client: BaseEvolutionClient | None,
    exc: EvolutionAPIError,
) -> None:
    error_code = _sanitize_error_code(exc.error_code)
    cleanup_attempted = False
    cleanup_succeeded = False
    if client is not None and _should_attempt_remote_cleanup(exc):
        cleanup_attempted, cleanup_succeeded = _attempt_remote_cleanup(
            client=client,
            channel=channel,
        )

    _mark_channel_error_safely(channel=channel, error_code=error_code)
    logger.warning(
        'Falha ao provisionar instancia Evolution',
        extra={
            'workspace_id': str(channel.workspace_id),
            'channel_id': str(channel.id),
            'instance_name': channel.instance_name,
            'operation': 'create_instance',
            'status': WhatsAppChannel.Status.ERROR,
            'error_code': error_code,
            'exception_type': type(exc).__name__,
            'remote_cleanup_attempted': cleanup_attempted,
            'remote_cleanup_succeeded': cleanup_succeeded,
        },
    )
    raise WhatsAppChannelProvisioningError(
        error_code=error_code,
        channel_id=channel.id,
        retryable=bool(exc.retryable),
        http_status=_evolution_error_http_status(exc),
    ) from None


def _raise_post_creation_error(
    *,
    channel: WhatsAppChannel,
    client: BaseEvolutionClient,
    error_code: str,
    retryable: bool,
    http_status: int,
    operation: str,
    exception_type: str,
) -> None:
    safe_error_code = _sanitize_error_code(error_code)
    cleanup_attempted, cleanup_succeeded = _attempt_remote_cleanup(
        client=client,
        channel=channel,
    )
    _mark_channel_error_safely(channel=channel, error_code=safe_error_code)
    logger.warning(
        'Falha posterior a criacao da instancia Evolution',
        extra={
            'workspace_id': str(channel.workspace_id),
            'channel_id': str(channel.id),
            'instance_name': channel.instance_name,
            'operation': operation,
            'status': WhatsAppChannel.Status.ERROR,
            'error_code': safe_error_code,
            'exception_type': exception_type,
            'remote_cleanup_attempted': cleanup_attempted,
            'remote_cleanup_succeeded': cleanup_succeeded,
        },
    )
    raise WhatsAppChannelProvisioningError(
        error_code=safe_error_code,
        channel_id=channel.id,
        retryable=retryable,
        http_status=http_status,
    ) from None


def _attempt_remote_cleanup(
    *,
    client: BaseEvolutionClient,
    channel: WhatsAppChannel,
) -> tuple[bool, bool]:
    try:
        client.delete_instance(instance_name=channel.instance_name)
    except Exception as exc:
        logger.warning(
            'Cleanup remoto da instancia Evolution falhou',
            extra={
                'workspace_id': str(channel.workspace_id),
                'channel_id': str(channel.id),
                'instance_name': channel.instance_name,
                'operation': 'delete_instance_cleanup',
                'status': channel.status,
                'error_code': 'EVOLUTION_REMOTE_CLEANUP_FAILED',
                'exception_type': type(exc).__name__,
                'remote_cleanup_attempted': True,
                'remote_cleanup_succeeded': False,
            },
        )
        return True, False

    logger.info(
        'Cleanup remoto da instancia Evolution concluido',
        extra={
            'workspace_id': str(channel.workspace_id),
            'channel_id': str(channel.id),
            'instance_name': channel.instance_name,
            'operation': 'delete_instance_cleanup',
            'status': channel.status,
            'remote_cleanup_attempted': True,
            'remote_cleanup_succeeded': True,
        },
    )
    return True, True


def _mark_channel_error_safely(*, channel: WhatsAppChannel, error_code: str) -> None:
    safe_error_code = _sanitize_error_code(error_code)
    try:
        with transaction.atomic():
            locked_channel = WhatsAppChannel.objects.select_for_update().filter(
                pk=channel.pk,
                workspace_id=channel.workspace_id,
                instance_name=channel.instance_name,
            ).first()
            if (
                locked_channel is None
                or locked_channel.status != WhatsAppChannel.Status.PROVISIONING
            ):
                return
            locked_channel.status = WhatsAppChannel.Status.ERROR
            locked_channel.last_error_code = safe_error_code
            locked_channel.save(
                update_fields=['status', 'last_error_code', 'updated_at'],
            )
        record_channel_observability_event_safe(
            workspace=locked_channel.workspace,
            channel=locked_channel,
            event_type=AIObservabilityEvent.EventType.CHANNEL_ERROR,
            status=AIObservabilityEvent.Status.FAILED,
            reason_code=PROVISIONING_ERROR_REASON,
            error_code=safe_error_code,
            metadata={'action': 'provision'},
        )
    except Exception as exc:
        logger.warning(
            'Falha ao marcar canal WhatsApp como erro',
            extra={
                'workspace_id': str(channel.workspace_id),
                'channel_id': str(channel.id),
                'instance_name': channel.instance_name,
                'operation': 'mark_whatsapp_channel_error',
                'status': channel.status,
                'error_code': safe_error_code,
                'exception_type': type(exc).__name__,
            },
        )


def _extract_safe_instance_credentials(response: dict[str, Any]) -> tuple[str, str]:
    if not isinstance(response, dict):
        raise EvolutionInvalidResponseError(operation='create_instance')

    instance_payload = response.get('instance')
    hash_payload = response.get('hash')
    instance = instance_payload if isinstance(instance_payload, dict) else {}
    token_hash = hash_payload if isinstance(hash_payload, dict) else {}

    instance_id = _safe_external_string(
        instance.get('instanceId') or instance.get('id'),
        max_length=WhatsAppChannel._meta.get_field('instance_id').max_length,
    )
    instance_token = _safe_external_string(
        token_hash.get('apikey'),
        max_length=WhatsAppChannel._meta.get_field('instance_token').max_length,
    )
    return instance_id, instance_token


def _safe_external_string(value: Any, *, max_length: int | None) -> str:
    if value is None:
        return ''
    if not isinstance(value, str):
        raise EvolutionInvalidResponseError(operation='create_instance')
    normalized = value.strip()
    if (
        any(unicodedata.category(character) == 'Cc' for character in normalized)
        or max_length is not None and len(normalized) > max_length
    ):
        raise EvolutionInvalidResponseError(operation='create_instance')
    return normalized


def _normalize_channel_name(channel_name: str) -> str:
    if not isinstance(channel_name, str):
        raise WhatsAppChannelProvisioningError(
            error_code='INVALID_CHANNEL_NAME',
            http_status=400,
        )
    if any(unicodedata.category(character) == 'Cc' for character in channel_name):
        raise WhatsAppChannelProvisioningError(
            error_code='INVALID_CHANNEL_NAME',
            http_status=400,
        )
    normalized = ' '.join(channel_name.split())
    max_length = WhatsAppChannel._meta.get_field('name').max_length
    if not normalized or max_length is not None and len(normalized) > max_length:
        raise WhatsAppChannelProvisioningError(
            error_code='INVALID_CHANNEL_NAME',
            http_status=400,
        )
    return normalized


def _generate_instance_name() -> str:
    return f'{INSTANCE_NAME_PREFIX}{uuid.uuid4().hex}'


def _sanitize_error_code(error_code: Any) -> str:
    normalized = re.sub(r'[^A-Z0-9_]+', '_', str(error_code or '').upper()).strip('_')
    if not normalized:
        normalized = 'EVOLUTION_REQUEST_ERROR'
    max_length = WhatsAppChannel._meta.get_field('last_error_code').max_length or 128
    return normalized[:max_length]


def _should_attempt_remote_cleanup(exc: EvolutionAPIError) -> bool:
    if isinstance(
        exc,
        (
            EvolutionTimeoutError,
            EvolutionConnectionError,
            EvolutionUnavailableError,
        ),
    ):
        return True
    return type(exc) is EvolutionAPIError and bool(exc.retryable)


def _evolution_error_http_status(exc: EvolutionAPIError) -> int:
    if isinstance(exc, EvolutionTimeoutError):
        return 504
    if isinstance(exc, EvolutionConflictError):
        return 409
    if isinstance(
        exc,
        (
            EvolutionConfigurationError,
            EvolutionAuthenticationError,
            EvolutionConnectionError,
            EvolutionUnavailableError,
            EvolutionRateLimitError,
        ),
    ):
        return 503
    if isinstance(
        exc,
        (
            EvolutionInvalidRequestError,
            EvolutionNotFoundError,
            EvolutionInvalidResponseError,
            EvolutionUnexpectedResponseError,
        ),
    ):
        return 502
    return 502
