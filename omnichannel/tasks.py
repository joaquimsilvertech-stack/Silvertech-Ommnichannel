from __future__ import annotations

from typing import Any

from celery import shared_task


@shared_task(name='omnichannel.process_whatsapp_webhook')
def process_whatsapp_webhook_task(payload: dict[str, Any], workspace_id: str) -> None:
    """Processa webhook WhatsApp em background (Card #027)."""
    from omnichannel.services import process_whatsapp_payload

    process_whatsapp_payload(payload, workspace_id)


@shared_task(name='omnichannel.process_ai_response')
def process_ai_response(conversation_id: str) -> str | None:
    """Gera, persiste e entrega uma resposta automatica de IA."""
    from omnichannel.ai_service import generate_ai_reply
    from omnichannel.models import Conversation, Message
    from omnichannel.services import send_whatsapp_message

    try:
        conversation = Conversation.objects.select_related(
            'contact',
            'workspace',
            'workspace__ai_config',
        ).get(id=conversation_id)
    except Conversation.DoesNotExist:
        return None

    if conversation.is_human_handoff:
        return None

    ai_config = getattr(conversation.workspace, 'ai_config', None)
    if not ai_config or not ai_config.is_active or not ai_config.openai_api_key:
        return None

    reply_text = generate_ai_reply(
        conversation=conversation,
        system_prompt=ai_config.system_prompt,
        api_key=ai_config.openai_api_key,
        model_name=ai_config.model_name,
    )
    if not reply_text:
        return None

    message = Message.objects.create(
        conversation=conversation,
        body=reply_text,
        direction=Message.Direction.OUTBOUND,
        status=Message.Status.SENT,
    )

    send_whatsapp_message(conversation.contact.phone, reply_text)
    return str(message.id)
