from __future__ import annotations

import logging
import uuid
from unittest.mock import MagicMock, patch

import pytest
from django.apps import apps

from omnichannel.ai.exceptions import (
    AIProviderAuthenticationError,
    AIProviderInvalidResponseError,
    AIProviderRateLimitError,
)
from omnichannel.ai.types import AIProviderResult
from omnichannel.factories import ConversationFactory, MessageFactory
from omnichannel.models import AIProcessingRun, Message
from omnichannel.tasks import process_ai_response
from workspaces.factories import WorkspaceAIProviderConfigFactory
from workspaces.models import AIProvider


def _adapter(result_text: str = 'Resposta gerada pela IA.'):
    adapter = MagicMock()
    adapter.generate_response.return_value = AIProviderResult(
        text=result_text,
        provider=AIProvider.OPENAI,
        model_name='gpt-4o-mini',
        external_id='provider-result-id',
    )
    return adapter


@pytest.mark.django_db
def test_process_ai_response_creates_outbound_message_and_sends_whatsapp() -> None:
    conversation = ConversationFactory(contact__phone='5511999999999')
    provider_config = WorkspaceAIProviderConfigFactory(
        workspace=conversation.workspace,
        api_key='sk-workspace-key',
        system_prompt='Prompt do tenant Silvertech',
        model_name='gpt-4o-mini',
        settings={'temperature': 0.2},
    )
    MessageFactory(
        conversation=conversation,
        direction=Message.Direction.INBOUND,
        body='Quero atendimento por IA.',
    )
    adapter = _adapter()

    with (
        patch('omnichannel.ai.registry.get_provider_adapter', return_value=adapter) as mock_registry,
        patch('omnichannel.services.send_whatsapp_message') as mock_send_whatsapp,
    ):
        message_id = process_ai_response.run(str(conversation.id))

    message = Message.objects.get(id=message_id)
    assert message.conversation == conversation
    assert message.direction == Message.Direction.OUTBOUND
    assert message.status == Message.Status.SENT
    assert message.body == 'Resposta gerada pela IA.'
    mock_registry.assert_called_once_with(
        provider=provider_config.provider,
        api_key='sk-workspace-key',
    )
    adapter.generate_response.assert_called_once_with(
        model_name='gpt-4o-mini',
        messages=[
            {'role': 'system', 'content': 'Prompt do tenant Silvertech'},
            {'role': 'user', 'content': 'Quero atendimento por IA.'},
        ],
        settings={'temperature': 0.2},
    )
    mock_send_whatsapp.assert_called_once_with('5511999999999', 'Resposta gerada pela IA.')


@pytest.mark.django_db
def test_process_ai_response_accepts_valid_source_message_id() -> None:
    conversation = ConversationFactory(contact__phone='5511999999999')
    WorkspaceAIProviderConfigFactory(
        workspace=conversation.workspace,
        api_key='sk-source-message-key',
        system_prompt='Prompt com mensagem fonte',
    )
    inbound = MessageFactory(
        conversation=conversation,
        direction=Message.Direction.INBOUND,
        body='Mensagem que disparou a IA.',
    )
    adapter = _adapter('Resposta com source message.')

    with (
        patch('omnichannel.ai.registry.get_provider_adapter', return_value=adapter) as mock_registry,
        patch('omnichannel.services.send_whatsapp_message') as mock_send_whatsapp,
    ):
        message_id = process_ai_response.run(
            str(conversation.id),
            source_message_id=str(inbound.id),
        )

    assert message_id is not None
    run = AIProcessingRun.objects.get(source_message=inbound)
    assert run.status == AIProcessingRun.Status.SUCCEEDED
    assert str(run.output_message_id) == message_id
    mock_registry.assert_called_once()
    mock_send_whatsapp.assert_called_once_with('5511999999999', 'Resposta com source message.')


@pytest.mark.django_db
def test_process_ai_response_duplicate_source_message_does_not_create_second_response() -> None:
    conversation = ConversationFactory(contact__phone='5511999999999')
    WorkspaceAIProviderConfigFactory(
        workspace=conversation.workspace,
        api_key='sk-duplicate-source-key',
    )
    inbound = MessageFactory(
        conversation=conversation,
        direction=Message.Direction.INBOUND,
        body='Responda uma unica vez.',
    )
    first_adapter = _adapter('Primeira resposta.')

    with (
        patch('omnichannel.ai.registry.get_provider_adapter', return_value=first_adapter),
        patch('omnichannel.services.send_whatsapp_message') as first_send,
    ):
        first_message_id = process_ai_response.run(
            str(conversation.id),
            source_message_id=str(inbound.id),
        )

    with (
        patch('omnichannel.ai.registry.get_provider_adapter') as second_registry,
        patch('omnichannel.services.send_whatsapp_message') as second_send,
    ):
        second_result = process_ai_response.run(
            str(conversation.id),
            source_message_id=str(inbound.id),
        )

    assert first_message_id is not None
    assert second_result is None
    assert Message.objects.filter(
        conversation=conversation,
        direction=Message.Direction.OUTBOUND,
    ).count() == 1
    assert AIProcessingRun.objects.filter(source_message=inbound).count() == 1
    first_send.assert_called_once()
    second_registry.assert_not_called()
    second_send.assert_not_called()


@pytest.mark.django_db
@pytest.mark.parametrize(
    'run_status',
    [
        AIProcessingRun.Status.RUNNING,
        AIProcessingRun.Status.SUCCEEDED,
        AIProcessingRun.Status.FAILED,
        AIProcessingRun.Status.SKIPPED,
    ],
)
def test_process_ai_response_existing_run_statuses_skip_processing(run_status: str) -> None:
    conversation = ConversationFactory(contact__phone='5511999999999')
    provider_config = WorkspaceAIProviderConfigFactory(
        workspace=conversation.workspace,
        api_key='sk-existing-run-key',
    )
    inbound = MessageFactory(conversation=conversation, direction=Message.Direction.INBOUND)
    AIProcessingRun.objects.create(
        workspace=conversation.workspace,
        conversation=conversation,
        source_message=inbound,
        provider_config=provider_config,
        status=run_status,
        attempt_count=1,
    )

    with (
        patch('omnichannel.ai.registry.get_provider_adapter') as mock_registry,
        patch('omnichannel.services.send_whatsapp_message') as mock_send_whatsapp,
    ):
        result = process_ai_response.run(
            str(conversation.id),
            source_message_id=str(inbound.id),
        )

    assert result is None
    assert not Message.objects.filter(
        conversation=conversation,
        direction=Message.Direction.OUTBOUND,
    ).exists()
    mock_registry.assert_not_called()
    mock_send_whatsapp.assert_not_called()


@pytest.mark.django_db
def test_process_ai_response_skips_human_handoff() -> None:
    conversation = ConversationFactory(is_human_handoff=True)

    with (
        patch('omnichannel.ai.registry.get_provider_adapter') as mock_registry,
        patch('omnichannel.services.send_whatsapp_message') as mock_send_whatsapp,
    ):
        result = process_ai_response.run(str(conversation.id))

    assert result is None
    assert not Message.objects.filter(
        conversation=conversation,
        direction=Message.Direction.OUTBOUND,
    ).exists()
    mock_registry.assert_not_called()
    mock_send_whatsapp.assert_not_called()


@pytest.mark.django_db
def test_process_ai_response_with_source_message_skips_human_handoff() -> None:
    conversation = ConversationFactory(is_human_handoff=True)
    WorkspaceAIProviderConfigFactory(workspace=conversation.workspace, api_key='sk-handoff-source-key')
    inbound = MessageFactory(conversation=conversation, direction=Message.Direction.INBOUND)

    with (
        patch('omnichannel.ai.registry.get_provider_adapter') as mock_registry,
        patch('omnichannel.services.send_whatsapp_message') as mock_send_whatsapp,
    ):
        result = process_ai_response.run(str(conversation.id), source_message_id=str(inbound.id))

    assert result is None
    assert not Message.objects.filter(
        conversation=conversation,
        direction=Message.Direction.OUTBOUND,
    ).exists()
    mock_registry.assert_not_called()
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
        patch('omnichannel.ai.registry.get_provider_adapter') as mock_registry,
        patch('omnichannel.services.send_whatsapp_message') as mock_send_whatsapp,
    ):
        result = process_ai_response.run(str(conversation.id))

    assert result is None
    mock_registry.assert_not_called()
    mock_send_whatsapp.assert_not_called()


@pytest.mark.django_db
def test_process_ai_response_skips_missing_source_message() -> None:
    conversation = ConversationFactory()
    WorkspaceAIProviderConfigFactory(workspace=conversation.workspace, api_key='sk-missing-source-key')

    with (
        patch('omnichannel.ai.registry.get_provider_adapter') as mock_registry,
        patch('omnichannel.services.send_whatsapp_message') as mock_send_whatsapp,
    ):
        result = process_ai_response.run(
            str(conversation.id),
            source_message_id=str(uuid.uuid4()),
        )

    assert result is None
    assert not AIProcessingRun.objects.exists()
    mock_registry.assert_not_called()
    mock_send_whatsapp.assert_not_called()


@pytest.mark.django_db
def test_process_ai_response_skips_source_message_from_other_conversation() -> None:
    conversation = ConversationFactory()
    other_conversation = ConversationFactory()
    WorkspaceAIProviderConfigFactory(workspace=conversation.workspace, api_key='sk-other-source-key')
    source_message = MessageFactory(
        conversation=other_conversation,
        direction=Message.Direction.INBOUND,
    )

    with (
        patch('omnichannel.ai.registry.get_provider_adapter') as mock_registry,
        patch('omnichannel.services.send_whatsapp_message') as mock_send_whatsapp,
    ):
        result = process_ai_response.run(
            str(conversation.id),
            source_message_id=str(source_message.id),
        )

    assert result is None
    assert not AIProcessingRun.objects.exists()
    mock_registry.assert_not_called()
    mock_send_whatsapp.assert_not_called()


@pytest.mark.django_db
def test_process_ai_response_skips_outbound_source_message() -> None:
    conversation = ConversationFactory()
    WorkspaceAIProviderConfigFactory(workspace=conversation.workspace, api_key='sk-outbound-source-key')
    source_message = MessageFactory(
        conversation=conversation,
        direction=Message.Direction.OUTBOUND,
        body='Outbound nao pode disparar IA.',
    )

    with (
        patch('omnichannel.ai.registry.get_provider_adapter') as mock_registry,
        patch('omnichannel.services.send_whatsapp_message') as mock_send_whatsapp,
    ):
        result = process_ai_response.run(
            str(conversation.id),
            source_message_id=str(source_message.id),
        )

    assert result is None
    assert not AIProcessingRun.objects.exists()
    assert not Message.objects.filter(
        conversation=conversation,
        direction=Message.Direction.OUTBOUND,
    ).exclude(id=source_message.id).exists()
    mock_registry.assert_not_called()
    mock_send_whatsapp.assert_not_called()


@pytest.mark.django_db
def test_process_ai_response_skips_empty_source_message() -> None:
    conversation = ConversationFactory()
    WorkspaceAIProviderConfigFactory(workspace=conversation.workspace, api_key='sk-empty-source-key')
    source_message = MessageFactory(
        conversation=conversation,
        direction=Message.Direction.INBOUND,
        body=' ',
    )

    with (
        patch('omnichannel.ai.registry.get_provider_adapter') as mock_registry,
        patch('omnichannel.services.send_whatsapp_message') as mock_send_whatsapp,
    ):
        result = process_ai_response.run(
            str(conversation.id),
            source_message_id=str(source_message.id),
        )

    assert result is None
    assert not AIProcessingRun.objects.exists()
    mock_registry.assert_not_called()
    mock_send_whatsapp.assert_not_called()


@pytest.mark.django_db
def test_process_ai_response_skips_missing_provider_with_source_message() -> None:
    conversation = ConversationFactory()
    source_message = MessageFactory(conversation=conversation, direction=Message.Direction.INBOUND)

    with (
        patch('omnichannel.ai.registry.get_provider_adapter') as mock_registry,
        patch('omnichannel.services.send_whatsapp_message') as mock_send_whatsapp,
    ):
        result = process_ai_response.run(
            str(conversation.id),
            source_message_id=str(source_message.id),
        )

    assert result is None
    assert not AIProcessingRun.objects.exists()
    mock_registry.assert_not_called()
    mock_send_whatsapp.assert_not_called()


@pytest.mark.django_db
def test_process_ai_response_skips_missing_api_key_with_source_message() -> None:
    conversation = ConversationFactory()
    WorkspaceAIProviderConfigFactory(workspace=conversation.workspace, api_key='')
    source_message = MessageFactory(conversation=conversation, direction=Message.Direction.INBOUND)

    with (
        patch('omnichannel.ai.registry.get_provider_adapter') as mock_registry,
        patch('omnichannel.services.send_whatsapp_message') as mock_send_whatsapp,
    ):
        result = process_ai_response.run(
            str(conversation.id),
            source_message_id=str(source_message.id),
        )

    assert result is None
    assert not AIProcessingRun.objects.exists()
    mock_registry.assert_not_called()
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
    adapter = _adapter('Resposta do workspace correto.')

    with (
        patch('omnichannel.ai.registry.get_provider_adapter', return_value=adapter) as mock_registry,
        patch('omnichannel.services.send_whatsapp_message') as mock_send_whatsapp,
    ):
        message_id = process_ai_response.run(str(conversation.id))

    assert message_id is not None
    mock_registry.assert_called_once_with(
        provider=AIProvider.OPENAI,
        api_key='sk-current-workspace-key',
    )
    assert adapter.generate_response.call_args.kwargs['messages'][0] == {
        'role': 'system',
        'content': 'Prompt correto',
    }
    mock_send_whatsapp.assert_called_once_with('5511888888888', 'Resposta do workspace correto.')


@pytest.mark.django_db
def test_process_ai_response_ignores_workspace_ai_system_prompt() -> None:
    conversation = ConversationFactory(contact__phone='5511666666666')
    conversation.workspace.ai_system_prompt = 'PROMPT_LEGADO_WORKSPACE'
    conversation.workspace.save(update_fields=['ai_system_prompt'])
    WorkspaceAIProviderConfigFactory(
        workspace=conversation.workspace,
        api_key='sk-provider-official-key',
        system_prompt='PROMPT_OFICIAL_PROVIDER',
    )
    MessageFactory(
        conversation=conversation,
        direction=Message.Direction.INBOUND,
        body='Use o prompt oficial.',
    )
    adapter = _adapter('Resposta com prompt oficial.')

    with (
        patch('omnichannel.ai.registry.get_provider_adapter', return_value=adapter),
        patch('omnichannel.services.send_whatsapp_message') as mock_send_whatsapp,
    ):
        message_id = process_ai_response.run(str(conversation.id))

    assert message_id is not None
    messages = adapter.generate_response.call_args.kwargs['messages']
    assert messages[0] == {'role': 'system', 'content': 'PROMPT_OFICIAL_PROVIDER'}
    assert 'PROMPT_LEGADO_WORKSPACE' not in str(messages)
    mock_send_whatsapp.assert_called_once_with('5511666666666', 'Resposta com prompt oficial.')


@pytest.mark.django_db
def test_process_ai_response_unsupported_provider_does_not_create_or_send(caplog) -> None:
    conversation = ConversationFactory()
    WorkspaceAIProviderConfigFactory(
        workspace=conversation.workspace,
        provider=AIProvider.ANTHROPIC,
        api_key='sk-anthropic-test-key',
    )

    with (
        caplog.at_level(logging.WARNING),
        patch('omnichannel.services.send_whatsapp_message') as mock_send_whatsapp,
    ):
        result = process_ai_response.run(str(conversation.id))

    assert result is None
    assert not Message.objects.filter(
        conversation=conversation,
        direction=Message.Direction.OUTBOUND,
    ).exists()
    mock_send_whatsapp.assert_not_called()
    assert 'sk-anthropic-test-key' not in caplog.text


@pytest.mark.django_db
def test_process_ai_response_ignores_divergent_legacy_provider_config() -> None:
    conversation = ConversationFactory(contact__phone='5511777777777')
    conversation.workspace.ai_system_prompt = 'PROMPT_LEGADO_WORKSPACE'
    conversation.workspace.save(update_fields=['ai_system_prompt'])
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
    adapter = _adapter('Resposta via provider config.')

    with (
        patch('omnichannel.ai.registry.get_provider_adapter', return_value=adapter) as mock_registry,
        patch('omnichannel.services.send_whatsapp_message') as mock_send_whatsapp,
    ):
        message_id = process_ai_response.run(str(conversation.id))

    assert message_id is not None
    mock_registry.assert_called_once_with(provider=AIProvider.OPENAI, api_key='sk-provider-key')
    assert adapter.generate_response.call_args.kwargs['model_name'] == 'gpt-4o-mini'
    messages = adapter.generate_response.call_args.kwargs['messages']
    assert messages[0] == {
        'role': 'system',
        'content': 'Prompt provider atual',
    }
    assert 'Prompt legado que nao deve ser usado' not in str(messages)
    assert 'PROMPT_LEGADO_WORKSPACE' not in str(messages)
    mock_send_whatsapp.assert_called_once_with('5511777777777', 'Resposta via provider config.')


@pytest.mark.django_db
def test_process_ai_response_with_empty_provider_prompt_does_not_send_empty_system_message() -> None:
    conversation = ConversationFactory(contact__phone='5511555555555')
    WorkspaceAIProviderConfigFactory(
        workspace=conversation.workspace,
        api_key='sk-empty-prompt-key',
        system_prompt='',
    )
    MessageFactory(
        conversation=conversation,
        direction=Message.Direction.INBOUND,
        body='Sem prompt de sistema.',
    )
    adapter = _adapter('Resposta sem system prompt.')

    with (
        patch('omnichannel.ai.registry.get_provider_adapter', return_value=adapter),
        patch('omnichannel.services.send_whatsapp_message') as mock_send_whatsapp,
    ):
        message_id = process_ai_response.run(str(conversation.id))

    assert message_id is not None
    assert adapter.generate_response.call_args.kwargs['messages'] == [
        {'role': 'user', 'content': 'Sem prompt de sistema.'},
    ]
    mock_send_whatsapp.assert_called_once_with('5511555555555', 'Resposta sem system prompt.')


@pytest.mark.django_db
@pytest.mark.parametrize(
    'provider_exception',
    [
        AIProviderAuthenticationError('auth'),
        AIProviderRateLimitError('rate-limit'),
        AIProviderInvalidResponseError('empty'),
    ],
)
def test_process_ai_response_provider_errors_do_not_create_or_send(provider_exception, caplog) -> None:
    conversation = ConversationFactory()
    WorkspaceAIProviderConfigFactory(
        workspace=conversation.workspace,
        api_key='sk-provider-error-key',
    )
    adapter = _adapter()
    adapter.generate_response.side_effect = provider_exception

    with (
        caplog.at_level(logging.WARNING),
        patch('omnichannel.ai.registry.get_provider_adapter', return_value=adapter),
        patch('omnichannel.services.send_whatsapp_message') as mock_send_whatsapp,
    ):
        result = process_ai_response.run(str(conversation.id))

    assert result is None
    assert not Message.objects.filter(
        conversation=conversation,
        direction=Message.Direction.OUTBOUND,
    ).exists()
    mock_send_whatsapp.assert_not_called()
    assert 'sk-provider-error-key' not in caplog.text


@pytest.mark.django_db
def test_process_ai_response_provider_error_marks_run_failed_without_outbound_or_evolution(caplog) -> None:
    conversation = ConversationFactory()
    WorkspaceAIProviderConfigFactory(
        workspace=conversation.workspace,
        api_key='sk-source-provider-error-key',
    )
    inbound = MessageFactory(
        conversation=conversation,
        direction=Message.Direction.INBOUND,
        body='Mensagem com erro do provider.',
    )
    adapter = _adapter()
    adapter.generate_response.side_effect = AIProviderRateLimitError('rate-limit raw detail')
    caplog.set_level(logging.WARNING)

    with (
        patch('omnichannel.ai.registry.get_provider_adapter', return_value=adapter),
        patch('omnichannel.services.send_whatsapp_message') as mock_send_whatsapp,
    ):
        result = process_ai_response.run(
            str(conversation.id),
            source_message_id=str(inbound.id),
        )

    assert result is None
    run = AIProcessingRun.objects.get(source_message=inbound)
    assert run.status == AIProcessingRun.Status.FAILED
    assert run.error_code == 'AIPROVIDERRATELIMITERROR'
    assert not Message.objects.filter(
        conversation=conversation,
        direction=Message.Direction.OUTBOUND,
    ).exists()
    mock_send_whatsapp.assert_not_called()
    assert 'sk-source-provider-error-key' not in caplog.text
    assert 'Mensagem com erro do provider.' not in caplog.text


@pytest.mark.django_db
def test_process_ai_response_without_source_message_id_does_not_create_run() -> None:
    conversation = ConversationFactory(contact__phone='5511999999999')
    WorkspaceAIProviderConfigFactory(
        workspace=conversation.workspace,
        api_key='sk-no-source-run-key',
    )
    MessageFactory(
        conversation=conversation,
        direction=Message.Direction.INBOUND,
        body='Fluxo retrocompativel.',
    )
    adapter = _adapter('Resposta sem run.')

    with (
        patch('omnichannel.ai.registry.get_provider_adapter', return_value=adapter),
        patch('omnichannel.services.send_whatsapp_message'),
    ):
        message_id = process_ai_response.run(str(conversation.id))

    assert message_id is not None
    assert not AIProcessingRun.objects.exists()
