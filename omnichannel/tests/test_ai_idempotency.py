from __future__ import annotations

import inspect
import logging
from unittest.mock import patch

import pytest
from django.db import IntegrityError

from omnichannel.factories import ConversationFactory, MessageFactory
from omnichannel.models import AIProcessingRun, Message
from omnichannel.services import (
    AI_PROCESSING_ALREADY_FAILED,
    AI_PROCESSING_ALREADY_RUNNING,
    AI_PROCESSING_ALREADY_SKIPPED,
    AI_PROCESSING_ALREADY_SUCCEEDED,
    claim_ai_processing_run,
    mark_ai_processing_failed,
    mark_ai_processing_skipped,
    mark_ai_processing_succeeded,
)
from workspaces.factories import WorkspaceAIProviderConfigFactory


def _source_with_provider():
    conversation = ConversationFactory()
    source_message = MessageFactory(
        conversation=conversation,
        direction=Message.Direction.INBOUND,
    )
    provider_config = WorkspaceAIProviderConfigFactory(workspace=conversation.workspace)
    return source_message, provider_config


@pytest.mark.django_db
def test_claim_ai_processing_run_creates_running_run() -> None:
    source_message, provider_config = _source_with_provider()

    run, reason_code = claim_ai_processing_run(
        source_message=source_message,
        provider_config=provider_config,
    )

    assert reason_code is None
    assert run is not None
    assert run.status == AIProcessingRun.Status.RUNNING
    assert run.attempt_count == 1
    assert run.started_at is not None
    assert run.workspace == source_message.conversation.workspace
    assert run.conversation == source_message.conversation
    assert run.source_message == source_message
    assert run.provider_config == provider_config


@pytest.mark.django_db
@pytest.mark.parametrize(
    ('status', 'expected_reason'),
    [
        (AIProcessingRun.Status.RUNNING, AI_PROCESSING_ALREADY_RUNNING),
        (AIProcessingRun.Status.SUCCEEDED, AI_PROCESSING_ALREADY_SUCCEEDED),
        (AIProcessingRun.Status.FAILED, AI_PROCESSING_ALREADY_FAILED),
        (AIProcessingRun.Status.SKIPPED, AI_PROCESSING_ALREADY_SKIPPED),
    ],
)
def test_claim_ai_processing_run_skips_existing_status(status: str, expected_reason: str) -> None:
    source_message, provider_config = _source_with_provider()
    AIProcessingRun.objects.create(
        workspace=source_message.conversation.workspace,
        conversation=source_message.conversation,
        source_message=source_message,
        provider_config=provider_config,
        status=status,
        attempt_count=1,
    )

    run, reason_code = claim_ai_processing_run(
        source_message=source_message,
        provider_config=provider_config,
    )

    assert run is None
    assert reason_code == expected_reason
    assert AIProcessingRun.objects.get(source_message=source_message).attempt_count == 1


@pytest.mark.django_db
def test_claim_ai_processing_run_handles_integrity_error_safely() -> None:
    source_message, provider_config = _source_with_provider()
    existing = AIProcessingRun.objects.create(
        workspace=source_message.conversation.workspace,
        conversation=source_message.conversation,
        source_message=source_message,
        provider_config=provider_config,
        status=AIProcessingRun.Status.RUNNING,
    )

    with patch.object(AIProcessingRun.objects, 'create', side_effect=IntegrityError('raw sql leak')):
        run, reason_code = claim_ai_processing_run(
            source_message=source_message,
            provider_config=provider_config,
        )

    assert run is None
    assert reason_code == AI_PROCESSING_ALREADY_RUNNING
    assert AIProcessingRun.objects.get(id=existing.id).source_message == source_message


@pytest.mark.django_db
def test_mark_ai_processing_succeeded_links_output_message() -> None:
    source_message, provider_config = _source_with_provider()
    run, _ = claim_ai_processing_run(
        source_message=source_message,
        provider_config=provider_config,
    )
    output_message = MessageFactory(
        conversation=source_message.conversation,
        direction=Message.Direction.OUTBOUND,
        status=Message.Status.PENDING,
    )

    updated_run = mark_ai_processing_succeeded(
        run=run,
        output_message=output_message,
    )

    assert updated_run.status == AIProcessingRun.Status.SUCCEEDED
    assert updated_run.output_message == output_message
    assert updated_run.output_message.status == Message.Status.PENDING
    assert updated_run.error_code == ''
    assert updated_run.finished_at is not None


@pytest.mark.django_db
def test_succeeded_run_with_failed_output_message_still_blocks_regeneration() -> None:
    source_message, provider_config = _source_with_provider()
    output_message = MessageFactory(
        conversation=source_message.conversation,
        direction=Message.Direction.OUTBOUND,
        status=Message.Status.FAILED,
        send_error_code='EVOLUTION_TIMEOUT',
    )
    AIProcessingRun.objects.create(
        workspace=source_message.conversation.workspace,
        conversation=source_message.conversation,
        source_message=source_message,
        provider_config=provider_config,
        output_message=output_message,
        status=AIProcessingRun.Status.SUCCEEDED,
        attempt_count=1,
    )

    run, reason_code = claim_ai_processing_run(
        source_message=source_message,
        provider_config=provider_config,
    )

    assert run is None
    assert reason_code == AI_PROCESSING_ALREADY_SUCCEEDED
    assert AIProcessingRun.objects.get(source_message=source_message).error_code == ''


@pytest.mark.django_db
def test_mark_ai_processing_failed_sanitizes_error_code() -> None:
    source_message, provider_config = _source_with_provider()
    run, _ = claim_ai_processing_run(
        source_message=source_message,
        provider_config=provider_config,
    )

    updated_run = mark_ai_processing_failed(
        run=run,
        error_code='provider error: sk-secret',
    )

    assert updated_run.status == AIProcessingRun.Status.FAILED
    assert updated_run.error_code == 'PROVIDER_ERROR__SK_SECRET'
    assert updated_run.finished_at is not None


@pytest.mark.django_db
def test_mark_ai_processing_skipped_sanitizes_error_code() -> None:
    source_message, provider_config = _source_with_provider()
    run, _ = claim_ai_processing_run(
        source_message=source_message,
        provider_config=provider_config,
    )

    updated_run = mark_ai_processing_skipped(
        run=run,
        error_code='already skipped',
    )

    assert updated_run.status == AIProcessingRun.Status.SKIPPED
    assert updated_run.error_code == 'ALREADY_SKIPPED'


def test_idempotency_helpers_use_transactions_and_locks() -> None:
    claim_source = inspect.getsource(claim_ai_processing_run)
    success_source = inspect.getsource(mark_ai_processing_succeeded)
    failed_source = inspect.getsource(mark_ai_processing_failed)
    skipped_source = inspect.getsource(mark_ai_processing_skipped)

    assert 'transaction.atomic' in claim_source
    assert 'select_for_update' in claim_source
    assert 'transaction.atomic' in success_source
    assert 'select_for_update' in success_source
    assert 'mark_ai_processing_failed' in failed_source
    assert 'mark_ai_processing_skipped' in skipped_source


@pytest.mark.django_db
def test_idempotency_helpers_do_not_call_openai_evolution_or_create_outbound(caplog) -> None:
    source_message, provider_config = _source_with_provider()
    secret = 'sk-idempotency-secret-key'
    provider_config.api_key = secret
    provider_config.save(update_fields=['api_key'])
    caplog.set_level(logging.INFO)

    with (
        patch('omnichannel.ai.providers.openai.openai.OpenAI') as mock_openai,
        patch('omnichannel.services.send_whatsapp_message') as mock_evolution,
    ):
        run, reason_code = claim_ai_processing_run(
            source_message=source_message,
            provider_config=provider_config,
        )

    assert run is not None
    assert reason_code is None
    assert not Message.objects.filter(
        conversation=source_message.conversation,
        direction=Message.Direction.OUTBOUND,
    ).exists()
    mock_openai.assert_not_called()
    mock_evolution.assert_not_called()
    assert secret not in caplog.text
