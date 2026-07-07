from __future__ import annotations

import logging

import openai

from .models import Conversation
from .services import build_conversation_context_for_ai

logger = logging.getLogger(__name__)

DEFAULT_OPENAI_MODEL = 'gpt-4o-mini'


def generate_ai_reply(
    conversation: Conversation,
    system_prompt: str,
    api_key: str,
    model_name: str = DEFAULT_OPENAI_MODEL,
) -> str:
    """Gera uma resposta de IA com base no historico recente da conversa."""
    messages = build_conversation_context_for_ai(
        conversation,
        system_prompt=system_prompt,
    )

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
