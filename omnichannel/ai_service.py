from __future__ import annotations

from .ai.providers.openai import OpenAIAdapter
from .models import Conversation
from .services import build_conversation_context_for_ai

DEFAULT_OPENAI_MODEL = 'gpt-4o-mini'


def generate_ai_reply(
    conversation: Conversation,
    system_prompt: str,
    api_key: str,
    model_name: str = DEFAULT_OPENAI_MODEL,
) -> str:
    """DEPRECATED: wrapper legado; use Provider Registry nas tasks."""
    messages = build_conversation_context_for_ai(
        conversation,
        system_prompt=system_prompt,
    )
    adapter = OpenAIAdapter(api_key=api_key)
    result = adapter.generate_response(
        model_name=model_name,
        messages=messages,
        system_prompt=system_prompt,
        settings={},
    )
    return result.text
