from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from django.apps import apps

from omnichannel.ai_service import DEFAULT_OPENAI_MODEL, generate_ai_reply
from omnichannel.factories import ConversationFactory, MessageFactory
from omnichannel.models import Message
from omnichannel.tasks import process_ai_response
from workspaces.factories import WorkspaceAIProviderConfigFactory
from workspaces.models import AIProvider


def _openai_response(content: str):
    return SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(content=content),
            ),
        ],
    )


def _openai_client(content: str):
    create = MagicMock(return_value=_openai_response(content))
    client = SimpleNamespace(
        chat=SimpleNamespace(
            completions=SimpleNamespace(create=create),
        ),
    )
    return client, create


@pytest.mark.django_db
def test_generate_ai_reply_sends_recent_history_to_openai() -> None:
    conversation = ConversationFactory()
    MessageFactory(
        conversation=conversation,
        direction=Message.Direction.INBOUND,
        body='Ola, quais sao os planos?',
    )
    MessageFactory(
        conversation=conversation,
        direction=Message.Direction.OUTBOUND,
        body='Temos planos mensais e anuais.',
    )
    client, mock_create = _openai_client('Claro, posso ajudar.')

    with patch('omnichannel.ai_service.openai.OpenAI', return_value=client) as mock_openai:
        reply = generate_ai_reply(
            conversation,
            'Prompt de sistema',
            api_key='sk-test-key',
            model_name=DEFAULT_OPENAI_MODEL,
        )

    assert reply == 'Claro, posso ajudar.'
    mock_openai.assert_called_once_with(api_key='sk-test-key')
    mock_create.assert_called_once()
    kwargs = mock_create.call_args.kwargs
    assert kwargs['model'] == DEFAULT_OPENAI_MODEL
    assert kwargs['messages'] == [
        {'role': 'system', 'content': 'Prompt de sistema'},
        {'role': 'user', 'content': 'Ola, quais sao os planos?'},
        {'role': 'assistant', 'content': 'Temos planos mensais e anuais.'},
    ]


@pytest.mark.django_db
def test_process_ai_response_creates_outbound_message_and_sends_whatsapp() -> None:
    conversation = ConversationFactory(contact__phone='5511999999999')
    WorkspaceAIProviderConfigFactory(
        workspace=conversation.workspace,
        api_key='sk-workspace-key',
        system_prompt='Prompt do tenant Silvertech',
        model_name='gpt-4o-mini',
    )
    MessageFactory(
        conversation=conversation,
        direction=Message.Direction.INBOUND,
        body='Quero atendimento por IA.',
    )
    client, mock_create = _openai_client('Resposta gerada pela IA.')

    with (
        patch('omnichannel.ai_service.openai.OpenAI', return_value=client) as mock_openai,
        patch('omnichannel.services.send_whatsapp_message') as mock_send_whatsapp,
    ):
        message_id = process_ai_response.run(str(conversation.id))

    message = Message.objects.get(id=message_id)
    assert message.conversation == conversation
    assert message.direction == Message.Direction.OUTBOUND
    assert message.status == Message.Status.SENT
    assert message.body == 'Resposta gerada pela IA.'
    mock_openai.assert_called_once_with(api_key='sk-workspace-key')
    mock_create.assert_called_once()
    assert mock_create.call_args.kwargs['messages'][0] == {
        'role': 'system',
        'content': 'Prompt do tenant Silvertech',
    }
    mock_send_whatsapp.assert_called_once_with('5511999999999', 'Resposta gerada pela IA.')


@pytest.mark.django_db
def test_process_ai_response_skips_human_handoff() -> None:
    conversation = ConversationFactory(is_human_handoff=True)

    with (
        patch('omnichannel.ai_service.openai.OpenAI') as mock_openai,
        patch('omnichannel.services.send_whatsapp_message') as mock_send_whatsapp,
    ):
        result = process_ai_response.run(str(conversation.id))

    assert result is None
    assert not Message.objects.filter(
        conversation=conversation,
        direction=Message.Direction.OUTBOUND,
    ).exists()
    mock_openai.assert_not_called()
    mock_send_whatsapp.assert_not_called()


@pytest.mark.django_db
def test_process_ai_response_skips_inactive_provider_config() -> None:
    conversation = ConversationFactory()
    WorkspaceAIProviderConfigFactory(
        workspace=conversation.workspace,
        is_active=False,
        api_key='sk-workspace-key',
    )

    with (
        patch('omnichannel.ai_service.openai.OpenAI') as mock_openai,
        patch('omnichannel.services.send_whatsapp_message') as mock_send_whatsapp,
    ):
        result = process_ai_response.run(str(conversation.id))

    assert result is None
    mock_openai.assert_not_called()
    mock_send_whatsapp.assert_not_called()


@pytest.mark.django_db
def test_process_ai_response_uses_only_current_workspace_provider_config() -> None:
    other_conversation = ConversationFactory()
    conversation = ConversationFactory(contact__phone='5511888888888')
    WorkspaceAIProviderConfigFactory(
        workspace=other_conversation.workspace,
        api_key='sk-other-workspace-key',
        system_prompt='Prompt errado',
    )
    WorkspaceAIProviderConfigFactory(
        workspace=conversation.workspace,
        api_key='sk-current-workspace-key',
        system_prompt='Prompt correto',
    )
    MessageFactory(
        conversation=conversation,
        direction=Message.Direction.INBOUND,
        body='Responder pelo workspace correto.',
    )
    client, mock_create = _openai_client('Resposta do workspace correto.')

    with (
        patch('omnichannel.ai_service.openai.OpenAI', return_value=client) as mock_openai,
        patch('omnichannel.services.send_whatsapp_message') as mock_send_whatsapp,
    ):
        message_id = process_ai_response.run(str(conversation.id))

    assert message_id is not None
    mock_openai.assert_called_once_with(api_key='sk-current-workspace-key')
    assert mock_create.call_args.kwargs['messages'][0] == {
        'role': 'system',
        'content': 'Prompt correto',
    }
    mock_send_whatsapp.assert_called_once_with('5511888888888', 'Resposta do workspace correto.')


@pytest.mark.django_db
def test_process_ai_response_ignores_non_openai_provider_for_now() -> None:
    conversation = ConversationFactory()
    WorkspaceAIProviderConfigFactory(
        workspace=conversation.workspace,
        provider=AIProvider.ANTHROPIC,
        api_key='sk-anthropic-test-key',
    )

    with (
        patch('omnichannel.ai_service.openai.OpenAI') as mock_openai,
        patch('omnichannel.services.send_whatsapp_message') as mock_send_whatsapp,
    ):
        result = process_ai_response.run(str(conversation.id))

    assert result is None
    mock_openai.assert_not_called()
    mock_send_whatsapp.assert_not_called()


@pytest.mark.django_db
def test_process_ai_response_ignores_divergent_legacy_provider_config() -> None:
    conversation = ConversationFactory(contact__phone='5511777777777')
    LegacyWorkspaceAIConfig = apps.get_model('workspaces', 'WorkspaceAIConfig')
    LegacyWorkspaceAIConfig.objects.create(
        workspace=conversation.workspace,
        is_active=True,
        openai_api_key='sk-legacy-key',
        system_prompt='Prompt legado que nao deve ser usado',
        model_name='legacy-model',
    )
    WorkspaceAIProviderConfigFactory(
        workspace=conversation.workspace,
        api_key='sk-provider-key',
        system_prompt='Prompt provider atual',
        model_name='gpt-4o-mini',
    )
    MessageFactory(
        conversation=conversation,
        direction=Message.Direction.INBOUND,
        body='Use somente provider config.',
    )
    client, mock_create = _openai_client('Resposta via provider config.')

    with (
        patch('omnichannel.ai_service.openai.OpenAI', return_value=client) as mock_openai,
        patch('omnichannel.services.send_whatsapp_message') as mock_send_whatsapp,
    ):
        message_id = process_ai_response.run(str(conversation.id))

    assert message_id is not None
    mock_openai.assert_called_once_with(api_key='sk-provider-key')
    assert mock_create.call_args.kwargs['model'] == 'gpt-4o-mini'
    assert mock_create.call_args.kwargs['messages'][0] == {
        'role': 'system',
        'content': 'Prompt provider atual',
    }
    mock_send_whatsapp.assert_called_once_with('5511777777777', 'Resposta via provider config.')
