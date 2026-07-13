from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

import requests
from celery import shared_task
from django.db import transaction
from django.utils import timezone

from omnichannel.services import MAX_AI_PROVIDER_ATTEMPTS, MAX_OUTBOUND_DELIVERY_ATTEMPTS

logger = logging.getLogger(__name__)


@shared_task(name='omnichannel.process_whatsapp_webhook')
def process_whatsapp_webhook_task(payload: dict[str, Any], workspace_id: str) -> None:
    """Processa webhook WhatsApp em background (Card #027)."""
    from omnichannel.services import process_whatsapp_payload

    process_whatsapp_payload(payload, workspace_id)


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
    from omnichannel.models import Conversation, Message
    from omnichannel.services import (
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
    )
    from workspaces.models import WorkspaceAIProviderConfig

    ai_processing_run = None
    source_message = None

    try:
        conversation = Conversation.objects.select_related(
            'contact',
            'workspace',
        ).get(id=conversation_id)
    except Conversation.DoesNotExist:
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
        _log_ai_provider_skip(
            'Provider de IA nao suportado para task',
            conversation=conversation,
            provider_config=provider_config,
            exc=exc,
        )
        if ai_processing_run is not None:
            mark_ai_processing_failed(
                run=ai_processing_run,
                error_code=map_ai_provider_exception_to_error_code(exc),
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
                mark_ai_processing_retrying(
                    run=ai_processing_run,
                    error_code=map_ai_provider_exception_to_error_code(exc),
                    next_retry_at=next_retry_at,
                )
                logger.info(
                    'Retry de provider de IA agendado',
                    extra={
                        'workspace_id': str(conversation.workspace_id),
                        'conversation_id': str(conversation.id),
                        'source_message_id': str(source_message_id or ''),
                        'ai_processing_run_id': str(ai_processing_run.id),
                        'error_code': map_ai_provider_exception_to_error_code(exc),
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
            mark_ai_processing_failed(
                run=ai_processing_run,
                error_code=map_ai_provider_exception_to_error_code(exc),
            )
        return None

    with transaction.atomic():
        message = create_pending_ai_message(
            conversation=conversation,
            body=result.text,
        )
        if ai_processing_run is not None:
            mark_ai_processing_succeeded(
                run=ai_processing_run,
                output_message=message,
            )
        transaction.on_commit(
            lambda message_id=str(message.id): send_outbound_whatsapp_message.delay(message_id),
        )

    return str(message.id)


@shared_task(
    bind=True,
    name='omnichannel.send_outbound_whatsapp_message',
    max_retries=MAX_OUTBOUND_DELIVERY_ATTEMPTS,
)
def send_outbound_whatsapp_message(self, message_id: str) -> str | None:
    """Entrega uma Message OUTBOUND existente pela Evolution com retry isolado."""
    from omnichannel.models import Message
    from omnichannel.services import (
        OUTBOUND_RETRY_BASE_SECONDS,
        calculate_exponential_backoff,
        can_retry_message_delivery,
        extract_evolution_message_external_id,
        map_evolution_exception_to_error_code,
        mark_message_as_failed,
        mark_message_as_sent,
        mark_message_delivery_attempt_started,
        mark_message_delivery_retrying,
        send_whatsapp_message,
    )

    try:
        message = Message.objects.select_related(
            'conversation',
            'conversation__contact',
            'conversation__workspace',
        ).get(id=message_id)
    except Message.DoesNotExist:
        return None

    if message.direction != Message.Direction.OUTBOUND:
        return None

    if message.status == Message.Status.SENT:
        return str(message.id)

    if message.status != Message.Status.PENDING:
        return None

    message = mark_message_delivery_attempt_started(message=message)

    try:
        evolution_response = send_whatsapp_message(
            message.conversation.contact.phone,
            message.body,
        )
        external_id = extract_evolution_message_external_id(evolution_response)
    except Exception as exc:
        error_code = map_evolution_exception_to_error_code(exc)
        retryable = isinstance(
            exc,
            (
                requests.exceptions.Timeout,
                requests.exceptions.ConnectionError,
                requests.exceptions.RequestException,
            ),
        )
        if retryable and can_retry_message_delivery(message=message):
            countdown = calculate_exponential_backoff(
                message.send_attempt_count,
                base_seconds=OUTBOUND_RETRY_BASE_SECONDS,
            )
            next_retry_at = timezone.now() + timedelta(seconds=countdown)
            mark_message_delivery_retrying(
                message=message,
                error_code=error_code,
                next_retry_at=next_retry_at,
            )
            _log_message_send_failure(
                conversation=message.conversation,
                message=message,
                error_code=error_code,
                exc=exc,
                status='retrying',
                retry_countdown=countdown,
                attempt_count=message.send_attempt_count,
            )
            raise self.retry(exc=exc, countdown=countdown)

        mark_message_as_failed(message=message, error_code=error_code)
        _log_message_send_failure(
            conversation=message.conversation,
            message=message,
            error_code=error_code,
            exc=exc,
            status='failed',
            attempt_count=message.send_attempt_count,
        )
        return str(message.id)

    mark_message_as_sent(message=message, external_id=external_id)
    return str(message.id)


def _log_ai_task_skip(
    message: str,
    *,
    conversation,
    source_message_id: str | None,
    reason_code: str,
) -> None:
    logger.info(
        message,
        extra={
            'workspace_id': str(conversation.workspace_id),
            'conversation_id': str(conversation.id),
            'source_message_id': str(source_message_id or ''),
            'reason_code': reason_code,
        },
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
            'status': status,
            'error_code': error_code,
            'attempt_count': attempt_count,
            'retry_countdown': retry_countdown,
            'exception_type': type(exc).__name__,
        },
    )
