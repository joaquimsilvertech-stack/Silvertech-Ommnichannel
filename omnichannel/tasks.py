from __future__ import annotations

import logging
from typing import Any

from celery import shared_task

logger = logging.getLogger(__name__)


@shared_task(name='omnichannel.process_whatsapp_webhook')
def process_whatsapp_webhook_task(payload: dict[str, Any], workspace_id: str) -> None:
    """Processa webhook WhatsApp em background (Card #027)."""
    from omnichannel.services import process_whatsapp_payload

    process_whatsapp_payload(payload, workspace_id)


@shared_task(name='omnichannel.process_ai_response')
def process_ai_response(conversation_id: str) -> str | None:
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
    from omnichannel.ai.registry import get_provider_adapter
    from omnichannel.models import Conversation, Message
    from omnichannel.services import build_conversation_context_for_ai, send_whatsapp_message
    from workspaces.models import WorkspaceAIProviderConfig

    try:
        conversation = Conversation.objects.select_related(
            'contact',
            'workspace',
        ).get(id=conversation_id)
    except Conversation.DoesNotExist:
        return None

    if conversation.is_human_handoff:
        return None

    provider_config = (
        WorkspaceAIProviderConfig.objects.filter(
            workspace=conversation.workspace,
            is_active=True,
        )
        .only('api_key', 'provider', 'system_prompt', 'model_name', 'settings')
        .first()
    )
    if not provider_config or not provider_config.api_key:
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
            system_prompt=provider_config.system_prompt,
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
        return None

    message = Message.objects.create(
        conversation=conversation,
        body=result.text,
        direction=Message.Direction.OUTBOUND,
        status=Message.Status.SENT,
    )

    send_whatsapp_message(conversation.contact.phone, result.text)
    return str(message.id)


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
