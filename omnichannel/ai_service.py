from __future__ import annotations

import logging

import openai

from .models import Conversation, Message

logger = logging.getLogger(__name__)

DEFAULT_OPENAI_MODEL = 'gpt-4o-mini'
RECENT_MESSAGES_LIMIT = 15


def generate_ai_reply(
    conversation: Conversation,
    system_prompt: str,
    api_key: str,
    model_name: str = DEFAULT_OPENAI_MODEL,
) -> str:
    """Gera uma resposta de IA com base no historico recente da conversa."""
    messages = _build_openai_messages(conversation, system_prompt)

    client = openai.OpenAI(api_key=api_key)
    response = client.chat.completions.create(
        model=model_name,
        messages=messages,
    )

    reply = response.choices[0].message.content
    if not reply:
        logger.warning('OpenAI retornou resposta vazia (conversation_id=%s)', conversation.id)
        return ''

    return reply.strip()


def _build_openai_messages(
    conversation: Conversation,
    system_prompt: str,
) -> list[dict[str, str]]:
    recent_messages = list(
        Message.objects.filter(conversation=conversation)
        .order_by('-created_at')[:RECENT_MESSAGES_LIMIT],
    )
    recent_messages.reverse()

    messages: list[dict[str, str]] = [
        {
            'role': 'system',
            'content': system_prompt,
        },
    ]

    for message in recent_messages:
        role = _direction_to_openai_role(message.direction)
        if role is None:
            continue

        messages.append(
            {
                'role': role,
                'content': message.body,
            },
        )

    return messages


def _direction_to_openai_role(direction: str) -> str | None:
    role_by_direction: dict[str, str] = {
        Message.Direction.INBOUND: 'user',
        Message.Direction.OUTBOUND: 'assistant',
    }
    return role_by_direction.get(direction)
