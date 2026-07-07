from __future__ import annotations

from unittest.mock import patch

import pytest

from omnichannel.factories import ConversationFactory, MessageFactory
from omnichannel.models import Message
from omnichannel.services import build_conversation_context_for_ai


@pytest.mark.django_db
def test_build_conversation_context_adds_single_system_message() -> None:
    conversation = ConversationFactory()
    MessageFactory(
        conversation=conversation,
        direction=Message.Direction.INBOUND,
        body='Primeira mensagem',
    )

    messages = build_conversation_context_for_ai(
        conversation,
        system_prompt='Prompt oficial',
    )

    assert messages[0] == {'role': 'system', 'content': 'Prompt oficial'}
    assert [message['role'] for message in messages].count('system') == 1


@pytest.mark.django_db
def test_build_conversation_context_omits_empty_system_prompt() -> None:
    conversation = ConversationFactory()
    MessageFactory(
        conversation=conversation,
        direction=Message.Direction.INBOUND,
        body='Mensagem sem prompt',
    )

    messages = build_conversation_context_for_ai(
        conversation,
        system_prompt='',
    )

    assert messages == [{'role': 'user', 'content': 'Mensagem sem prompt'}]


@pytest.mark.django_db
def test_build_conversation_context_preserves_history_order_and_roles() -> None:
    conversation = ConversationFactory()
    MessageFactory(
        conversation=conversation,
        direction=Message.Direction.INBOUND,
        body='Ola',
    )
    MessageFactory(
        conversation=conversation,
        direction=Message.Direction.OUTBOUND,
        body='Como posso ajudar?',
    )
    MessageFactory(
        conversation=conversation,
        direction=Message.Direction.INBOUND,
        body='Quero saber valores.',
    )

    messages = build_conversation_context_for_ai(
        conversation,
        system_prompt='Prompt oficial',
    )

    assert messages == [
        {'role': 'system', 'content': 'Prompt oficial'},
        {'role': 'user', 'content': 'Ola'},
        {'role': 'assistant', 'content': 'Como posso ajudar?'},
        {'role': 'user', 'content': 'Quero saber valores.'},
    ]


@pytest.mark.django_db
def test_build_conversation_context_does_not_consult_workspace_or_provider_config() -> None:
    conversation = ConversationFactory()
    MessageFactory(
        conversation=conversation,
        direction=Message.Direction.INBOUND,
        body='Nao consulte configuracao aqui.',
    )

    with patch('workspaces.models.WorkspaceAIProviderConfig.objects') as mock_provider_manager:
        messages = build_conversation_context_for_ai(
            conversation,
            system_prompt='Prompt direto',
        )

    assert messages[0] == {'role': 'system', 'content': 'Prompt direto'}
    assert mock_provider_manager.method_calls == []


@pytest.mark.django_db
def test_build_conversation_context_does_not_modify_prompt_content() -> None:
    conversation = ConversationFactory()
    prompt = '  Prompt com espacos preservados.  '

    messages = build_conversation_context_for_ai(
        conversation,
        system_prompt=prompt,
    )

    assert messages == [{'role': 'system', 'content': prompt}]
