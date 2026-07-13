from __future__ import annotations

import pytest
from django.db import IntegrityError

from omnichannel.factories import ConversationFactory, MessageFactory
from omnichannel.models import AIProcessingRun, Message
from workspaces.factories import WorkspaceAIProviderConfigFactory


@pytest.mark.django_db
def test_ai_processing_run_can_be_created_for_inbound_source_message() -> None:
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
        status=AIProcessingRun.Status.RUNNING,
        attempt_count=1,
    )

    assert run.workspace == conversation.workspace
    assert run.conversation == conversation
    assert run.source_message == source_message
    assert run.provider_config == provider_config
    assert run.output_message is None


@pytest.mark.django_db
def test_ai_processing_run_allows_only_one_run_per_source_message() -> None:
    conversation = ConversationFactory()
    source_message = MessageFactory(conversation=conversation)
    provider_config = WorkspaceAIProviderConfigFactory(workspace=conversation.workspace)
    AIProcessingRun.objects.create(
        workspace=conversation.workspace,
        conversation=conversation,
        source_message=source_message,
        provider_config=provider_config,
    )

    with pytest.raises(IntegrityError):
        AIProcessingRun.objects.create(
            workspace=conversation.workspace,
            conversation=conversation,
            source_message=source_message,
            provider_config=provider_config,
        )


@pytest.mark.django_db
def test_ai_processing_run_accepts_optional_output_message() -> None:
    conversation = ConversationFactory()
    source_message = MessageFactory(conversation=conversation)
    provider_config = WorkspaceAIProviderConfigFactory(workspace=conversation.workspace)
    output_message = MessageFactory(
        conversation=conversation,
        direction=Message.Direction.OUTBOUND,
    )

    run = AIProcessingRun.objects.create(
        workspace=conversation.workspace,
        conversation=conversation,
        source_message=source_message,
        provider_config=provider_config,
        output_message=output_message,
        status=AIProcessingRun.Status.SUCCEEDED,
    )

    assert run.output_message == output_message


@pytest.mark.django_db
def test_ai_processing_run_provider_config_can_be_null_after_delete() -> None:
    conversation = ConversationFactory()
    source_message = MessageFactory(conversation=conversation)
    provider_config = WorkspaceAIProviderConfigFactory(workspace=conversation.workspace)
    run = AIProcessingRun.objects.create(
        workspace=conversation.workspace,
        conversation=conversation,
        source_message=source_message,
        provider_config=provider_config,
    )

    provider_config.delete()

    run.refresh_from_db()
    assert run.provider_config is None


def test_ai_processing_run_does_not_store_secrets_payload_or_body_fields() -> None:
    field_names = {field.name for field in AIProcessingRun._meta.get_fields()}

    assert 'api_key' not in field_names
    assert 'openai_api_key' not in field_names
    assert 'payload' not in field_names
    assert 'raw_payload' not in field_names
    assert 'body' not in field_names
    assert 'response' not in field_names


@pytest.mark.django_db
def test_ai_processing_run_str_does_not_expose_message_body_or_credentials() -> None:
    conversation = ConversationFactory()
    source_message = MessageFactory(
        conversation=conversation,
        body='Mensagem sensivel do cliente',
    )
    provider_config = WorkspaceAIProviderConfigFactory(
        workspace=conversation.workspace,
        api_key='sk-run-secret-key',
    )
    run = AIProcessingRun.objects.create(
        workspace=conversation.workspace,
        conversation=conversation,
        source_message=source_message,
        provider_config=provider_config,
    )

    rendered = str(run)

    assert 'Mensagem sensivel do cliente' not in rendered
    assert 'sk-run-secret-key' not in rendered
