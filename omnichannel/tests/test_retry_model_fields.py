from __future__ import annotations

import pytest

from omnichannel.factories import ConversationFactory, MessageFactory
from omnichannel.models import AIProcessingRun, Message
from workspaces.factories import WorkspaceAIProviderConfigFactory


@pytest.mark.django_db
def test_ai_processing_run_retry_fields_and_defaults_are_safe() -> None:
    conversation = ConversationFactory()
    source_message = MessageFactory(
        conversation=conversation,
        direction=Message.Direction.INBOUND,
    )
    provider_config = WorkspaceAIProviderConfigFactory(workspace=conversation.workspace)

    run = AIProcessingRun.objects.create(
        workspace=conversation.workspace,
        conversation=conversation,
        source_message=source_message,
        provider_config=provider_config,
    )

    assert AIProcessingRun.Status.RETRYING == 'retrying'
    assert run.last_error_code == ''
    assert run.next_retry_at is None
    assert run.last_attempt_at is None


@pytest.mark.django_db
def test_message_delivery_retry_fields_and_defaults_are_safe() -> None:
    message = MessageFactory(
        direction=Message.Direction.OUTBOUND,
        status=Message.Status.PENDING,
    )

    assert message.send_attempt_count == 0
    assert message.last_send_attempt_at is None
    assert message.next_send_retry_at is None


def test_retry_fields_do_not_store_secrets_payload_or_duplicate_body() -> None:
    ai_run_fields = {field.name for field in AIProcessingRun._meta.get_fields()}
    message_fields = {field.name for field in Message._meta.get_fields()}

    for forbidden_name in {'api_key', 'openai_api_key', 'payload', 'raw_payload', 'headers'}:
        assert forbidden_name not in ai_run_fields
        assert forbidden_name not in message_fields

    assert 'body' not in ai_run_fields
    assert 'send_error_code' in message_fields
    assert 'last_error_code' in ai_run_fields
