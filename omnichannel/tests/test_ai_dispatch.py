from __future__ import annotations

import logging
from unittest.mock import patch

import pytest

from omnichannel.factories import ConversationFactory, MessageFactory
from omnichannel.models import Message
from omnichannel.services import (
    AI_SKIP_CONVERSATION_HANDOFF,
    AI_SKIP_EMPTY_CONTENT,
    AI_SKIP_MESSAGE_FROM_ME,
    AI_SKIP_MESSAGE_NOT_INBOUND,
    AI_SKIP_MISSING_API_KEY,
    AI_SKIP_NO_ACTIVE_PROVIDER,
    AI_SKIP_NON_PROCESSABLE_CONTENT,
    AI_SKIP_UNSUPPORTED_GROUP_MESSAGE,
    AI_SKIP_UNSUPPORTED_PROVIDER,
    should_schedule_ai_response,
)
from workspaces.factories import WorkspaceAIProviderConfigFactory
from workspaces.models import AIProvider


def _decision(message: Message) -> tuple[bool, str | None]:
    return should_schedule_ai_response(
        workspace=message.conversation.workspace,
        conversation=message.conversation,
        message=message,
    )


@pytest.mark.django_db
def test_should_schedule_ai_response_for_active_supported_provider_and_text_inbound() -> None:
    conversation = ConversationFactory(is_human_handoff=False)
    WorkspaceAIProviderConfigFactory(workspace=conversation.workspace, api_key='sk-dispatch-key')
    message = MessageFactory(
        conversation=conversation,
        direction=Message.Direction.INBOUND,
        body='Ola, quero atendimento.',
    )

    should_schedule, reason_code = _decision(message)

    assert should_schedule is True
    assert reason_code is None


@pytest.mark.django_db
def test_should_schedule_ai_response_requires_active_provider() -> None:
    conversation = ConversationFactory()
    WorkspaceAIProviderConfigFactory(
        workspace=conversation.workspace,
        is_active=False,
        api_key='sk-inactive-key',
    )
    message = MessageFactory(conversation=conversation, direction=Message.Direction.INBOUND)

    should_schedule, reason_code = _decision(message)

    assert should_schedule is False
    assert reason_code == AI_SKIP_NO_ACTIVE_PROVIDER


@pytest.mark.django_db
def test_should_schedule_ai_response_rejects_unsupported_provider() -> None:
    conversation = ConversationFactory()
    WorkspaceAIProviderConfigFactory(
        workspace=conversation.workspace,
        provider=AIProvider.ANTHROPIC,
        api_key='sk-unsupported-provider-key',
    )
    message = MessageFactory(conversation=conversation, direction=Message.Direction.INBOUND)

    should_schedule, reason_code = _decision(message)

    assert should_schedule is False
    assert reason_code == AI_SKIP_UNSUPPORTED_PROVIDER


@pytest.mark.django_db
def test_should_schedule_ai_response_requires_api_key() -> None:
    conversation = ConversationFactory()
    WorkspaceAIProviderConfigFactory(workspace=conversation.workspace, api_key='')
    message = MessageFactory(conversation=conversation, direction=Message.Direction.INBOUND)

    should_schedule, reason_code = _decision(message)

    assert should_schedule is False
    assert reason_code == AI_SKIP_MISSING_API_KEY


@pytest.mark.django_db
def test_should_schedule_ai_response_rejects_handoff() -> None:
    conversation = ConversationFactory(is_human_handoff=True)
    WorkspaceAIProviderConfigFactory(workspace=conversation.workspace, api_key='sk-handoff-key')
    message = MessageFactory(conversation=conversation, direction=Message.Direction.INBOUND)

    should_schedule, reason_code = _decision(message)

    assert should_schedule is False
    assert reason_code == AI_SKIP_CONVERSATION_HANDOFF


@pytest.mark.django_db
def test_should_schedule_ai_response_rejects_outbound() -> None:
    conversation = ConversationFactory()
    WorkspaceAIProviderConfigFactory(workspace=conversation.workspace, api_key='sk-outbound-key')
    message = MessageFactory(conversation=conversation, direction=Message.Direction.OUTBOUND)

    should_schedule, reason_code = _decision(message)

    assert should_schedule is False
    assert reason_code == AI_SKIP_MESSAGE_NOT_INBOUND


@pytest.mark.django_db
def test_should_schedule_ai_response_rejects_from_me_transient_flag() -> None:
    conversation = ConversationFactory()
    WorkspaceAIProviderConfigFactory(workspace=conversation.workspace, api_key='sk-from-me-key')
    message = MessageFactory(conversation=conversation, direction=Message.Direction.INBOUND)
    message.ai_from_me = True

    should_schedule, reason_code = _decision(message)

    assert should_schedule is False
    assert reason_code == AI_SKIP_MESSAGE_FROM_ME


@pytest.mark.django_db
def test_should_schedule_ai_response_rejects_group_jid_transient_flag() -> None:
    conversation = ConversationFactory()
    WorkspaceAIProviderConfigFactory(workspace=conversation.workspace, api_key='sk-group-key')
    message = MessageFactory(conversation=conversation, direction=Message.Direction.INBOUND)
    message.ai_remote_jid = '120363000000000000@g.us'

    should_schedule, reason_code = _decision(message)

    assert should_schedule is False
    assert reason_code == AI_SKIP_UNSUPPORTED_GROUP_MESSAGE


@pytest.mark.django_db
def test_should_schedule_ai_response_rejects_empty_content() -> None:
    conversation = ConversationFactory()
    WorkspaceAIProviderConfigFactory(workspace=conversation.workspace, api_key='sk-empty-key')
    message = MessageFactory(conversation=conversation, direction=Message.Direction.INBOUND, body='   ')

    should_schedule, reason_code = _decision(message)

    assert should_schedule is False
    assert reason_code == AI_SKIP_EMPTY_CONTENT


@pytest.mark.django_db
def test_should_schedule_ai_response_rejects_non_processable_media_marker() -> None:
    conversation = ConversationFactory()
    WorkspaceAIProviderConfigFactory(workspace=conversation.workspace, api_key='sk-media-key')
    message = MessageFactory(
        conversation=conversation,
        direction=Message.Direction.INBOUND,
        body='[media]',
    )
    message.ai_message_type = 'imageMessage'

    should_schedule, reason_code = _decision(message)

    assert should_schedule is False
    assert reason_code == AI_SKIP_NON_PROCESSABLE_CONTENT


@pytest.mark.django_db
def test_dispatch_decision_does_not_call_provider_or_celery() -> None:
    conversation = ConversationFactory()
    WorkspaceAIProviderConfigFactory(workspace=conversation.workspace, api_key='sk-no-call-key')
    message = MessageFactory(conversation=conversation, direction=Message.Direction.INBOUND)

    with (
        patch('omnichannel.ai.providers.openai.openai.OpenAI') as mock_openai,
        patch('omnichannel.tasks.process_ai_response.delay') as mock_delay,
    ):
        should_schedule, reason_code = _decision(message)

    assert should_schedule is True
    assert reason_code is None
    mock_openai.assert_not_called()
    mock_delay.assert_not_called()


@pytest.mark.django_db
def test_dispatch_decision_logs_do_not_leak_api_key(caplog) -> None:
    conversation = ConversationFactory()
    secret = 'sk-dispatch-secret-key'
    WorkspaceAIProviderConfigFactory(workspace=conversation.workspace, api_key=secret)
    message = MessageFactory(conversation=conversation, direction=Message.Direction.INBOUND)
    caplog.set_level(logging.INFO)

    should_schedule, _ = _decision(message)

    assert should_schedule is True
    assert secret not in caplog.text
