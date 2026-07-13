from __future__ import annotations

import logging
from typing import Any

from celery import shared_task
import requests

logger = logging.getLogger(__name__)


@shared_task(name='omnichannel.process_whatsapp_webhook')
def process_whatsapp_webhook_task(payload: dict[str, Any], workspace_id: str) -> None:
    """Processa webhook WhatsApp em background (Card #027)."""
    from omnichannel.services import process_whatsapp_payload

    process_whatsapp_payload(payload, workspace_id)


@shared_task(name='omnichannel.process_ai_response')
def process_ai_response(
    conversation_id: str,
    source_message_id: str | None = None,
) -> str | None:
    """Gera, persiste e entrega uma resposta automatica de IA."""
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
    from django.db import transaction

    from omnichannel.ai.registry import get_provider_adapter, is_provider_supported
    from omnichannel.models import Conversation, Message
    from omnichannel.services import (
        EVOLUTION_INVALID_RESPONSE,
        EVOLUTION_REQUEST_ERROR,
        EVOLUTION_TIMEOUT,
        EVOLUTION_UNKNOWN_ERROR,
        build_conversation_context_for_ai,
        claim_ai_processing_run,
        create_pending_ai_message,
        extract_evolution_message_external_id,
        is_message_processable_for_ai,
        mark_ai_processing_failed,
        mark_ai_processing_succeeded,
        mark_message_as_failed,
        mark_message_as_sent,
        send_whatsapp_message,
    )
    from workspaces.models import WorkspaceAIProviderConfig

    ai_processing_run = None

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

    if source_message_id is not None:
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
                error_code='UNSUPPORTED_PROVIDER',
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
        if ai_processing_run is not None:
            mark_ai_processing_failed(
                run=ai_processing_run,
                error_code=type(exc).__name__,
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

    try:
        evolution_response = send_whatsapp_message(conversation.contact.phone, result.text)
        external_id = extract_evolution_message_external_id(evolution_response)
    except requests.exceptions.Timeout as exc:
        _log_message_send_failure(
            conversation=conversation,
            message=message,
            error_code=EVOLUTION_TIMEOUT,
            exc=exc,
        )
        mark_message_as_failed(message=message, error_code=EVOLUTION_TIMEOUT)
        return str(message.id)
    except requests.exceptions.RequestException as exc:
        _log_message_send_failure(
            conversation=conversation,
            message=message,
            error_code=EVOLUTION_REQUEST_ERROR,
            exc=exc,
        )
        mark_message_as_failed(message=message, error_code=EVOLUTION_REQUEST_ERROR)
        return str(message.id)
    except ValueError as exc:
        _log_message_send_failure(
            conversation=conversation,
            message=message,
            error_code=EVOLUTION_INVALID_RESPONSE,
            exc=exc,
        )
        mark_message_as_failed(message=message, error_code=EVOLUTION_INVALID_RESPONSE)
        return str(message.id)
    except Exception as exc:
        _log_message_send_failure(
            conversation=conversation,
            message=message,
            error_code=EVOLUTION_UNKNOWN_ERROR,
            exc=exc,
        )
        mark_message_as_failed(message=message, error_code=EVOLUTION_UNKNOWN_ERROR)
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
) -> None:
    logger.warning(
        'Falha ao enviar mensagem outbound pela Evolution API',
        extra={
            'workspace_id': str(conversation.workspace_id),
            'conversation_id': str(conversation.id),
            'message_id': str(message.id),
            'status': 'failed',
            'error_code': error_code,
            'exception_type': type(exc).__name__,
        },
    )
