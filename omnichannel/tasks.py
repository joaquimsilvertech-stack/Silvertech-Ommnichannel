from __future__ import annotations

import logging
from datetime import timedelta
from time import perf_counter
from typing import Any

from celery import shared_task
from django.db import transaction
from django.utils import timezone

from omnichannel.services import MAX_AI_PROVIDER_ATTEMPTS, MAX_OUTBOUND_DELIVERY_ATTEMPTS

logger = logging.getLogger(__name__)

OUTBOUND_DELIVERY_BUSY = 'OUTBOUND_DELIVERY_BUSY'
OUTBOUND_DELIVERY_BUSY_RETRY_SECONDS = 10


@shared_task(name='omnichannel.process_whatsapp_webhook')
def process_whatsapp_webhook_task(payload: dict[str, Any], workspace_id: str) -> None:
    """Processa webhook WhatsApp em background (Card #027)."""
    from omnichannel.services import process_whatsapp_payload

    process_whatsapp_payload(payload, workspace_id)


@shared_task(
    bind=True,
    name='omnichannel.process_evolution_channel_webhook',
    max_retries=3,
)
def process_evolution_channel_webhook_task(
    self,
    channel_id: str,
    payload: dict[str, Any],
) -> None:
    """Processa eventos do webhook seguro usando somente o canal como tenant root."""
    from uuid import UUID

    from omnichannel.evolution_event_processing import (
        EvolutionEventProcessingError,
        normalize_evolution_event_type,
        process_evolution_channel_event,
    )
    from omnichannel.models import WhatsAppChannel

    try:
        normalized_channel_id = UUID(str(channel_id))
    except (TypeError, ValueError, AttributeError):
        logger.warning(
            'Task de webhook Evolution ignorou identificador invalido',
            extra={
                'operation': 'process_evolution_channel_webhook',
                'exception_type': 'InvalidChannelId',
            },
        )
        return None

    try:
        channel = WhatsAppChannel.objects.select_related('workspace').get(
            id=normalized_channel_id,
        )
    except WhatsAppChannel.DoesNotExist:
        logger.info(
            'Task de webhook Evolution ignorou canal inexistente',
            extra={
                'channel_id': str(normalized_channel_id),
                'operation': 'process_evolution_channel_webhook',
                'exception_type': 'WhatsAppChannelDoesNotExist',
            },
        )
        return None

    if not isinstance(payload, dict):
        logger.warning(
            'Task de webhook Evolution ignorou payload invalido',
            extra={
                'channel_id': str(channel.id),
                'workspace_id': str(channel.workspace_id),
                'operation': 'process_evolution_channel_webhook',
                'event_type': 'UNSUPPORTED_EVENT',
                'exception_type': 'InvalidPayloadType',
            },
        )
        return None

    event_type = normalize_evolution_event_type(payload.get('event'))
    logger.info(
        'Task de webhook Evolution recebeu evento para processamento',
        extra={
            'channel_id': str(channel.id),
            'workspace_id': str(channel.workspace_id),
            'operation': 'process_evolution_channel_webhook',
            'event_type': event_type,
        },
    )

    try:
        process_evolution_channel_event(channel=channel, payload=payload)
    except EvolutionEventProcessingError as exc:
        logger.warning(
            'Falha controlada no processamento de evento Evolution',
            extra={
                'channel_id': str(channel.id),
                'workspace_id': str(channel.workspace_id),
                'operation': 'process_evolution_channel_webhook',
                'event_type': event_type,
                'evolution_event_id': exc.event_id or '',
                'error_code': exc.error_code,
                'retryable': exc.retryable,
                'exception_type': type(exc).__name__,
            },
        )
        if exc.retryable:
            countdown = min(5 * (2 ** int(self.request.retries)), 60)
            raise self.retry(exc=exc, countdown=countdown)
        return None
    except Exception as exc:
        logger.warning(
            'Falha inesperada na task de evento Evolution',
            extra={
                'channel_id': str(channel.id),
                'workspace_id': str(channel.workspace_id),
                'operation': 'process_evolution_channel_webhook',
                'event_type': event_type,
                'exception_type': type(exc).__name__,
            },
        )
        raise

    logger.info(
        'Task de webhook Evolution concluiu processamento',
        extra={
            'channel_id': str(channel.id),
            'workspace_id': str(channel.workspace_id),
            'operation': 'process_evolution_channel_webhook',
            'event_type': event_type,
        },
    )
    return None


@shared_task(bind=True, name='omnichannel.process_ai_response', max_retries=MAX_AI_PROVIDER_ATTEMPTS)
def process_ai_response(
    self,
    conversation_id: str,
    source_message_id: str | None = None,
    ai_processing_run_id: str | None = None,
) -> str | None:
    """Gera e persiste uma resposta automatica de IA; delivery fica em task separada."""
    from omnichannel.ai.exceptions import (
        AIProviderAuthenticationError,
        AIProviderError,
        AIProviderInvalidRequestError,
        AIProviderInvalidResponseError,
        AIProviderRateLimitError,
        AIProviderTimeoutError,
        AIProviderUnavailableError,
        UnsupportedAIProviderError,
    )
    from omnichannel.ai.registry import get_provider_adapter, is_provider_supported
    from omnichannel.models import AIObservabilityEvent, Conversation, Message
    from omnichannel.observability import (
        calculate_latency_ms,
        record_ai_observability_event_safe,
    )
    from omnichannel.services import (
        AI_SKIP_RECIPIENT_SELF,
        AI_SKIP_RECIPIENT_UNRESOLVED,
        AI_RETRY_BASE_SECONDS,
        MAX_AI_PROVIDER_ATTEMPTS,
        build_conversation_context_for_ai,
        calculate_exponential_backoff,
        can_retry_ai_processing,
        claim_ai_processing_run,
        create_pending_ai_message,
        get_retryable_ai_processing_run,
        is_message_processable_for_ai,
        is_retryable_ai_provider_error,
        map_ai_provider_exception_to_error_code,
        mark_ai_processing_attempt_started,
        mark_ai_processing_failed,
        mark_ai_processing_retrying,
        mark_ai_processing_succeeded,
        schedule_outbound_message_after_commit,
    )
    from omnichannel.whatsapp_recipient_validation import (
        RECIPIENT_IS_CHANNEL_PHONE,
        validate_conversation_whatsapp_recipient,
    )
    from workspaces.models import WorkspaceAIProviderConfig

    ai_processing_run = None
    source_message = None

    try:
        conversation = Conversation.objects.select_related(
            'contact',
            'workspace',
            'whatsapp_channel',
        ).get(id=conversation_id)
    except Conversation.DoesNotExist:
        return None

    recipient_validation = validate_conversation_whatsapp_recipient(conversation)
    if not recipient_validation.is_valid:
        _log_ai_task_skip(
            'Task de IA ignorada: destinatario WhatsApp nao resolvido',
            conversation=conversation,
            source_message_id=source_message_id,
            reason_code=(
                AI_SKIP_RECIPIENT_SELF
                if recipient_validation.status == RECIPIENT_IS_CHANNEL_PHONE
                else AI_SKIP_RECIPIENT_UNRESOLVED
            ),
        )
        return None

    if conversation.is_human_handoff:
        _log_ai_task_skip(
            'Task de IA ignorada: conversa em handoff',
            conversation=conversation,
            source_message_id=source_message_id,
            reason_code='CONVERSATION_HANDOFF',
        )
        return None

    if source_message_id is not None:
        try:
            source_message = Message.objects.select_related(
                'conversation',
                'conversation__workspace',
            ).get(id=source_message_id)
        except Message.DoesNotExist:
            _log_ai_task_skip(
                'Task de IA ignorada: mensagem fonte inexistente',
                conversation=conversation,
                source_message_id=source_message_id,
                reason_code='SOURCE_MESSAGE_NOT_FOUND',
            )
            return None

        if source_message.conversation_id != conversation.id:
            _log_ai_task_skip(
                'Task de IA ignorada: mensagem fonte de outra conversa',
                conversation=conversation,
                source_message_id=source_message_id,
                reason_code='SOURCE_MESSAGE_CONVERSATION_MISMATCH',
            )
            return None

        if source_message.conversation.workspace_id != conversation.workspace_id:
            _log_ai_task_skip(
                'Task de IA ignorada: mensagem fonte de outro workspace',
                conversation=conversation,
                source_message_id=source_message_id,
                reason_code='SOURCE_MESSAGE_WORKSPACE_MISMATCH',
            )
            return None

        if source_message.direction != Message.Direction.INBOUND:
            _log_ai_task_skip(
                'Task de IA ignorada: mensagem fonte nao inbound',
                conversation=conversation,
                source_message_id=source_message_id,
                reason_code='SOURCE_MESSAGE_NOT_INBOUND',
            )
            return None

        is_processable, reason_code = is_message_processable_for_ai(source_message)
        if not is_processable:
            _log_ai_task_skip(
                'Task de IA ignorada: mensagem fonte nao processavel',
                conversation=conversation,
                source_message_id=source_message_id,
                reason_code=reason_code or 'SOURCE_MESSAGE_NOT_PROCESSABLE',
            )
            return None

    provider_config = (
        WorkspaceAIProviderConfig.objects.filter(
            workspace=conversation.workspace,
            is_active=True,
        )
        .only('api_key', 'provider', 'system_prompt', 'model_name', 'settings')
        .first()
    )
    if not provider_config:
        _log_ai_task_skip(
            'Task de IA ignorada: provider ativo ausente',
            conversation=conversation,
            source_message_id=source_message_id,
            reason_code='NO_ACTIVE_PROVIDER',
        )
        return None

    if not provider_config.api_key:
        _log_ai_task_skip(
            'Task de IA ignorada: credencial ausente',
            conversation=conversation,
            source_message_id=source_message_id,
            reason_code='MISSING_API_KEY',
        )
        return None

    if not is_provider_supported(provider_config.provider):
        _log_ai_task_skip(
            'Task de IA ignorada: provider sem adapter ativo',
            conversation=conversation,
            source_message_id=source_message_id,
            reason_code='UNSUPPORTED_PROVIDER',
        )
        return None

    if source_message is not None:
        if ai_processing_run_id is not None:
            ai_processing_run = get_retryable_ai_processing_run(
                run_id=ai_processing_run_id,
                source_message=source_message,
            )
            if ai_processing_run is None:
                _log_ai_task_skip(
                    'Task de IA ignorada: retry de run invalido',
                    conversation=conversation,
                    source_message_id=source_message_id,
                    reason_code='AI_PROCESSING_RETRY_RUN_INVALID',
                )
                return None
        else:
            ai_processing_run, claim_reason_code = claim_ai_processing_run(
                source_message=source_message,
                provider_config=provider_config,
            )
            if ai_processing_run is None:
                _log_ai_task_skip(
                    'Task de IA ignorada: processamento idempotente existente',
                    conversation=conversation,
                    source_message_id=source_message_id,
                    reason_code=claim_reason_code or 'AI_PROCESSING_ALREADY_EXISTS',
                )
                return None

    messages = build_conversation_context_for_ai(
        conversation,
        system_prompt=provider_config.system_prompt,
    )

    if ai_processing_run is not None:
        ai_processing_run = mark_ai_processing_attempt_started(run=ai_processing_run)
    provider_started_at = perf_counter()
    record_ai_observability_event_safe(
        workspace=conversation.workspace,
        event_type=AIObservabilityEvent.EventType.AI_PROVIDER_ATTEMPT,
        status=AIObservabilityEvent.Status.PENDING,
        provider_config=provider_config,
        conversation=conversation,
        source_message=source_message,
        ai_processing_run=ai_processing_run,
        provider=provider_config.provider,
        model_name=provider_config.model_name,
        attempt_count=(
            ai_processing_run.attempt_count
            if ai_processing_run is not None
            else None
        ),
        metadata={'source': 'process_ai_response'},
    )

    try:
        adapter = get_provider_adapter(
            provider=provider_config.provider,
            api_key=provider_config.api_key,
        )
        result = adapter.generate_response(
            model_name=provider_config.model_name,
            messages=messages,
            settings=provider_config.settings or {},
        )
    except UnsupportedAIProviderError as exc:
        error_code = map_ai_provider_exception_to_error_code(exc)
        latency_ms = calculate_latency_ms(provider_started_at)
        _log_ai_provider_skip(
            'Provider de IA nao suportado para task',
            conversation=conversation,
            provider_config=provider_config,
            exc=exc,
        )
        if ai_processing_run is not None:
            ai_processing_run = mark_ai_processing_failed(
                run=ai_processing_run,
                error_code=error_code,
            )
        record_ai_observability_event_safe(
            workspace=conversation.workspace,
            event_type=AIObservabilityEvent.EventType.AI_PROVIDER_FAILED,
            status=AIObservabilityEvent.Status.FAILED,
            provider_config=provider_config,
            conversation=conversation,
            source_message=source_message,
            ai_processing_run=ai_processing_run,
            provider=provider_config.provider,
            model_name=provider_config.model_name,
            error_code=error_code,
            latency_ms=latency_ms,
            attempt_count=(
                ai_processing_run.attempt_count
                if ai_processing_run is not None
                else None
            ),
            metadata={'source': 'process_ai_response'},
        )
        return None
    except (
        AIProviderAuthenticationError,
        AIProviderInvalidRequestError,
        AIProviderInvalidResponseError,
        AIProviderRateLimitError,
        AIProviderTimeoutError,
        AIProviderUnavailableError,
        AIProviderError,
    ) as exc:
        error_code = map_ai_provider_exception_to_error_code(exc)
        latency_ms = calculate_latency_ms(provider_started_at)
        _log_ai_provider_skip(
            'Falha operacional ao gerar resposta de IA',
            conversation=conversation,
            provider_config=provider_config,
            exc=exc,
        )
        if ai_processing_run is not None and is_retryable_ai_provider_error(exc):
            if can_retry_ai_processing(
                run=ai_processing_run,
                max_attempts=MAX_AI_PROVIDER_ATTEMPTS,
            ):
                countdown = calculate_exponential_backoff(
                    ai_processing_run.attempt_count,
                    base_seconds=AI_RETRY_BASE_SECONDS,
                )
                next_retry_at = timezone.now() + timedelta(seconds=countdown)
                ai_processing_run = mark_ai_processing_retrying(
                    run=ai_processing_run,
                    error_code=error_code,
                    next_retry_at=next_retry_at,
                )
                record_ai_observability_event_safe(
                    workspace=conversation.workspace,
                    event_type=AIObservabilityEvent.EventType.AI_PROVIDER_RETRYING,
                    status=AIObservabilityEvent.Status.RETRYING,
                    provider_config=provider_config,
                    conversation=conversation,
                    source_message=source_message,
                    ai_processing_run=ai_processing_run,
                    provider=provider_config.provider,
                    model_name=provider_config.model_name,
                    error_code=error_code,
                    latency_ms=latency_ms,
                    attempt_count=ai_processing_run.attempt_count,
                    metadata={
                        'source': 'process_ai_response',
                        'retry_countdown': countdown,
                        'is_retryable': True,
                    },
                )
                logger.info(
                    'Retry de provider de IA agendado',
                    extra={
                        'workspace_id': str(conversation.workspace_id),
                        'conversation_id': str(conversation.id),
                        'source_message_id': str(source_message_id or ''),
                        'ai_processing_run_id': str(ai_processing_run.id),
                        'error_code': error_code,
                        'attempt_count': ai_processing_run.attempt_count,
                        'retry_countdown': countdown,
                        'exception_type': type(exc).__name__,
                    },
                )
                raise self.retry(
                    exc=exc,
                    countdown=countdown,
                    kwargs={
                        'conversation_id': str(conversation.id),
                        'source_message_id': str(source_message.id),
                        'ai_processing_run_id': str(ai_processing_run.id),
                    },
                )

        if ai_processing_run is not None:
            ai_processing_run = mark_ai_processing_failed(
                run=ai_processing_run,
                error_code=error_code,
            )
        record_ai_observability_event_safe(
            workspace=conversation.workspace,
            event_type=AIObservabilityEvent.EventType.AI_PROVIDER_FAILED,
            status=AIObservabilityEvent.Status.FAILED,
            provider_config=provider_config,
            conversation=conversation,
            source_message=source_message,
            ai_processing_run=ai_processing_run,
            provider=provider_config.provider,
            model_name=provider_config.model_name,
            error_code=error_code,
            latency_ms=latency_ms,
            attempt_count=(
                ai_processing_run.attempt_count
                if ai_processing_run is not None
                else None
            ),
            metadata={
                'source': 'process_ai_response',
                'is_retryable': is_retryable_ai_provider_error(exc),
            },
        )
        return None

    with transaction.atomic():
        message = create_pending_ai_message(
            conversation=conversation,
            body=result.text,
        )
        if ai_processing_run is not None:
            ai_processing_run = mark_ai_processing_succeeded(
                run=ai_processing_run,
                output_message=message,
            )
        schedule_outbound_message_after_commit(message=message)

    record_ai_observability_event_safe(
        workspace=conversation.workspace,
        event_type=AIObservabilityEvent.EventType.AI_PROVIDER_SUCCESS,
        status=AIObservabilityEvent.Status.SUCCESS,
        provider_config=provider_config,
        conversation=conversation,
        source_message=source_message,
        output_message=message,
        ai_processing_run=ai_processing_run,
        provider=provider_config.provider,
        model_name=provider_config.model_name,
        latency_ms=calculate_latency_ms(provider_started_at),
        attempt_count=(
            ai_processing_run.attempt_count
            if ai_processing_run is not None
            else None
        ),
        metadata={'source': 'process_ai_response'},
    )

    return str(message.id)


@shared_task(
    bind=True,
    name='omnichannel.send_outbound_whatsapp_message',
    max_retries=MAX_OUTBOUND_DELIVERY_ATTEMPTS,
)
def send_outbound_whatsapp_message(
    self,
    message_id: str,
    whatsapp_channel_id: str | None = None,
) -> str | None:
    """Entrega uma Message OUTBOUND existente pela Evolution com retry isolado."""
    from uuid import UUID

    from django.core.exceptions import ValidationError

    from omnichannel.evolution import EvolutionAPIError
    from omnichannel.models import AIObservabilityEvent, Message
    from omnichannel.observability import (
        calculate_latency_ms,
        record_ai_observability_event_safe,
    )
    from omnichannel.outbound_routing import (
        OutboundWhatsAppRoutingError,
        resolve_outbound_whatsapp_route,
    )
    from omnichannel.outbound_delivery_lock import (
        OutboundDeliveryLockError,
        acquire_outbound_delivery_lock,
    )
    from omnichannel.whatsapp_recipient_validation import (
        validate_conversation_whatsapp_recipient,
        validate_whatsapp_recipient,
    )
    from omnichannel.services import (
        claim_message_delivery_attempt,
        extract_evolution_message_external_id,
        map_evolution_exception_to_error_code,
        mark_message_as_sent,
        send_whatsapp_message,
    )

    try:
        normalized_message_id = UUID(str(message_id))
    except (AttributeError, TypeError, ValueError):
        return None

    if not Message.objects.only('id').filter(id=normalized_message_id).exists():
        return None

    try:
        lock_context = acquire_outbound_delivery_lock(normalized_message_id)
        with lock_context as delivery_lock:
            if not delivery_lock.acquired:
                try:
                    send_outbound_whatsapp_message.apply_async(
                        args=(str(normalized_message_id), whatsapp_channel_id),
                        countdown=OUTBOUND_DELIVERY_BUSY_RETRY_SECONDS,
                    )
                except Exception as exc:
                    logger.warning(
                        'Falha ao reagendar delivery outbound em contencao',
                        extra={
                            'message_id': str(normalized_message_id),
                            'whatsapp_channel_id': str(whatsapp_channel_id or ''),
                            'error_code': OUTBOUND_DELIVERY_BUSY,
                            'exception_type': type(exc).__name__,
                            'lock_acquired': False,
                        },
                    )
                else:
                    logger.info(
                        'Delivery outbound reagendado por contencao',
                        extra={
                            'message_id': str(normalized_message_id),
                            'whatsapp_channel_id': str(whatsapp_channel_id or ''),
                            'error_code': OUTBOUND_DELIVERY_BUSY,
                            'retry_countdown': OUTBOUND_DELIVERY_BUSY_RETRY_SECONDS,
                            'lock_acquired': False,
                        },
                    )
                return None

            try:
                message = Message.objects.select_related(
                    'conversation',
                    'conversation__contact',
                    'conversation__workspace',
                    'conversation__whatsapp_channel',
                ).get(id=normalized_message_id)
            except (Message.DoesNotExist, TypeError, ValueError, ValidationError):
                return None

            if message.direction != Message.Direction.OUTBOUND:
                return None

            if message.status in {
                Message.Status.SENT,
                Message.Status.DELIVERED,
                Message.Status.READ,
            }:
                return str(message.id)

            if message.status != Message.Status.PENDING:
                return None

            persisted_channel_id = message.conversation.whatsapp_channel_id
            expected_channel_id = (
                str(whatsapp_channel_id)
                if whatsapp_channel_id is not None
                else str(persisted_channel_id) if persisted_channel_id is not None else None
            )
            recipient_validation = validate_conversation_whatsapp_recipient(
                message.conversation,
            )
            if not recipient_validation.is_valid:
                local_error = OutboundWhatsAppRoutingError(
                    recipient_validation.internal_error_code,
                    retryable=False,
                )
                return _handle_outbound_delivery_failure(
                    task=self,
                    message=message,
                    exc=local_error,
                    error_code=recipient_validation.internal_error_code,
                    retryable=False,
                    expected_channel_id=expected_channel_id,
                    delivery_started_at=perf_counter(),
                )

            message = claim_message_delivery_attempt(message_id=message.id)
            if message is None:
                current_status = Message.objects.values_list('status', flat=True).get(
                    id=normalized_message_id,
                )
                if current_status in {
                    Message.Status.SENT,
                    Message.Status.DELIVERED,
                    Message.Status.READ,
                }:
                    return str(normalized_message_id)
                return None

            record_ai_observability_event_safe(
                workspace=message.conversation.workspace,
                event_type=AIObservabilityEvent.EventType.OUTBOUND_DELIVERY_ATTEMPT,
                status=AIObservabilityEvent.Status.PENDING,
                conversation=message.conversation,
                whatsapp_channel=message.conversation.whatsapp_channel,
                output_message=message,
                attempt_count=message.send_attempt_count,
                metadata={
                    'source': 'outbound_delivery',
                    'delivery_status': message.status,
                },
            )
            delivery_started_at = perf_counter()

            try:
                route = resolve_outbound_whatsapp_route(
                    message=message,
                    expected_channel_id=expected_channel_id,
                )
            except OutboundWhatsAppRoutingError as exc:
                return _handle_outbound_delivery_failure(
                    task=self,
                    message=message,
                    exc=exc,
                    error_code=exc.error_code,
                    retryable=exc.retryable,
                    expected_channel_id=(
                        str(persisted_channel_id)
                        if persisted_channel_id is not None
                        else None
                    ),
                    delivery_started_at=delivery_started_at,
                )

            expected_channel_id = str(route.channel.id)
            recipient_validation = validate_whatsapp_recipient(
                recipient=route.contact.phone,
                channel_phone_number=route.channel.phone_number,
            )
            if not recipient_validation.is_valid:
                local_error = OutboundWhatsAppRoutingError(
                    recipient_validation.internal_error_code,
                    retryable=False,
                )
                return _handle_outbound_delivery_failure(
                    task=self,
                    message=message,
                    exc=local_error,
                    error_code=recipient_validation.internal_error_code,
                    retryable=False,
                    expected_channel_id=expected_channel_id,
                    delivery_started_at=delivery_started_at,
                )
            try:
                evolution_response = send_whatsapp_message(
                    channel=route.channel,
                    phone=recipient_validation.canonical_phone,
                    text=message.body,
                )
                external_id = extract_evolution_message_external_id(evolution_response)
            except EvolutionAPIError as exc:
                return _handle_outbound_delivery_failure(
                    task=self,
                    message=message,
                    exc=exc,
                    error_code=map_evolution_exception_to_error_code(exc),
                    retryable=bool(exc.retryable),
                    expected_channel_id=expected_channel_id,
                    delivery_started_at=delivery_started_at,
                )
            except Exception as exc:
                return _handle_outbound_delivery_failure(
                    task=self,
                    message=message,
                    exc=exc,
                    error_code=map_evolution_exception_to_error_code(exc),
                    retryable=False,
                    expected_channel_id=expected_channel_id,
                    delivery_started_at=delivery_started_at,
                )

            message = mark_message_as_sent(message=message, external_id=external_id)
            record_ai_observability_event_safe(
                workspace=message.conversation.workspace,
                event_type=AIObservabilityEvent.EventType.OUTBOUND_DELIVERY_SUCCESS,
                status=AIObservabilityEvent.Status.SUCCESS,
                conversation=message.conversation,
                whatsapp_channel=message.conversation.whatsapp_channel,
                output_message=message,
                latency_ms=calculate_latency_ms(delivery_started_at),
                attempt_count=message.send_attempt_count,
                metadata={
                    'source': 'outbound_delivery',
                    'delivery_status': message.status,
                },
            )
            logger.info(
                'Mensagem outbound enviada pela Evolution API',
                extra={
                    'workspace_id': str(message.conversation.workspace_id),
                    'conversation_id': str(message.conversation_id),
                    'message_id': str(message.id),
                    'whatsapp_channel_id': str(route.channel.id),
                    'attempt_count': message.send_attempt_count,
                    'status': message.status,
                    'latency_ms': calculate_latency_ms(delivery_started_at),
                },
            )
            return str(message.id)
    except OutboundDeliveryLockError as exc:
        logger.warning(
            'Delivery outbound nao adquiriu lock PostgreSQL',
            extra={
                'message_id': str(normalized_message_id),
                'whatsapp_channel_id': str(whatsapp_channel_id or ''),
                'error_code': 'OUTBOUND_DELIVERY_LOCK_UNAVAILABLE',
                'exception_type': type(exc).__name__,
            },
        )
        return None


def _handle_outbound_delivery_failure(
    *,
    task,
    message,
    exc: Exception,
    error_code: str,
    retryable: bool,
    expected_channel_id: str | None,
    delivery_started_at: float,
) -> str | None:
    from omnichannel.models import AIObservabilityEvent, Message
    from omnichannel.observability import (
        calculate_latency_ms,
        record_ai_observability_event_safe,
    )
    from omnichannel.services import (
        OUTBOUND_RETRY_BASE_SECONDS,
        calculate_exponential_backoff,
        can_retry_message_delivery,
        mark_message_as_failed,
        mark_message_delivery_retrying,
    )

    if retryable and can_retry_message_delivery(message=message):
        countdown = calculate_exponential_backoff(
            message.send_attempt_count,
            base_seconds=OUTBOUND_RETRY_BASE_SECONDS,
        )
        next_retry_at = timezone.now() + timedelta(seconds=countdown)
        message = mark_message_delivery_retrying(
            message=message,
            error_code=error_code,
            next_retry_at=next_retry_at,
        )
        if message.status != Message.Status.PENDING:
            if message.status in {
                Message.Status.SENT,
                Message.Status.DELIVERED,
                Message.Status.READ,
            }:
                return str(message.id)
            return None

        record_ai_observability_event_safe(
            workspace=message.conversation.workspace,
            event_type=AIObservabilityEvent.EventType.OUTBOUND_DELIVERY_RETRYING,
            status=AIObservabilityEvent.Status.RETRYING,
            conversation=message.conversation,
            whatsapp_channel=message.conversation.whatsapp_channel,
            output_message=message,
            error_code=error_code,
            latency_ms=calculate_latency_ms(delivery_started_at),
            attempt_count=message.send_attempt_count,
            metadata={
                'source': 'outbound_delivery',
                'retry_countdown': countdown,
                'is_retryable': True,
                'delivery_status': message.status,
            },
        )
        _log_message_send_failure(
            conversation=message.conversation,
            message=message,
            whatsapp_channel_id=expected_channel_id,
            error_code=error_code,
            exc=exc,
            status='retrying',
            retry_countdown=countdown,
            attempt_count=message.send_attempt_count,
        )
        retry_args = (str(message.id), expected_channel_id)
        raise task.retry(
            args=retry_args,
            exc=exc,
            countdown=countdown,
        )

    message = mark_message_as_failed(message=message, error_code=error_code)
    if message.status != Message.Status.FAILED:
        if message.status in {
            Message.Status.SENT,
            Message.Status.DELIVERED,
            Message.Status.READ,
        }:
            return str(message.id)
        return None

    record_ai_observability_event_safe(
        workspace=message.conversation.workspace,
        event_type=AIObservabilityEvent.EventType.OUTBOUND_DELIVERY_FAILED,
        status=AIObservabilityEvent.Status.FAILED,
        conversation=message.conversation,
        whatsapp_channel=message.conversation.whatsapp_channel,
        output_message=message,
        error_code=error_code,
        latency_ms=calculate_latency_ms(delivery_started_at),
        attempt_count=message.send_attempt_count,
        metadata={
            'source': 'outbound_delivery',
            'is_retryable': retryable,
            'delivery_status': message.status,
        },
    )
    _log_message_send_failure(
        conversation=message.conversation,
        message=message,
        whatsapp_channel_id=expected_channel_id,
        error_code=error_code,
        exc=exc,
        status='failed',
        attempt_count=message.send_attempt_count,
    )
    return str(message.id)


def _log_ai_task_skip(
    message: str,
    *,
    conversation,
    source_message_id: str | None,
    reason_code: str,
) -> None:
    from omnichannel.models import AIObservabilityEvent
    from omnichannel.observability import record_ai_observability_event_safe

    logger.info(
        message,
        extra={
            'workspace_id': str(conversation.workspace_id),
            'conversation_id': str(conversation.id),
            'source_message_id': str(source_message_id or ''),
            'reason_code': reason_code,
        },
    )
    record_ai_observability_event_safe(
        workspace=conversation.workspace,
        event_type=AIObservabilityEvent.EventType.AI_SKIPPED,
        status=AIObservabilityEvent.Status.SKIPPED,
        conversation=conversation,
        reason_code=reason_code,
        metadata={'source': 'process_ai_response'},
    )


def _log_ai_provider_skip(
    message: str,
    *,
    conversation,
    provider_config,
    exc: Exception,
) -> None:
    logger.warning(
        message,
        extra={
            'workspace_id': str(conversation.workspace_id),
            'conversation_id': str(conversation.id),
            'provider': provider_config.provider,
            'model_name': provider_config.model_name,
            'exception_type': type(exc).__name__,
        },
    )


def _log_message_send_failure(
    *,
    conversation,
    message,
    whatsapp_channel_id: str | None,
    error_code: str,
    exc: Exception,
    status: str,
    attempt_count: int | None = None,
    retry_countdown: int | None = None,
) -> None:
    logger.warning(
        'Falha ao enviar mensagem outbound pela Evolution API',
        extra={
            'workspace_id': str(conversation.workspace_id),
            'conversation_id': str(conversation.id),
            'message_id': str(message.id),
            'whatsapp_channel_id': str(whatsapp_channel_id or ''),
            'status': status,
            'error_code': error_code,
            'attempt_count': attempt_count,
            'retry_countdown': retry_countdown,
            'exception_type': type(exc).__name__,
        },
    )
