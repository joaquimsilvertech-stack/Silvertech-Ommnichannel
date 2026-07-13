from __future__ import annotations

import inspect
import logging
from datetime import timedelta
from unittest.mock import patch

import pytest
from django.utils import timezone

from omnichannel.factories import ConversationFactory, MessageFactory
from omnichannel.models import AIProcessingRun, Message
from omnichannel.services import (
    MAX_AI_PROVIDER_ATTEMPTS,
    MAX_OUTBOUND_DELIVERY_ATTEMPTS,
    can_retry_ai_processing,
    can_retry_message_delivery,
    get_retryable_ai_processing_run,
    mark_ai_processing_attempt_started,
    mark_ai_processing_retrying,
    mark_message_delivery_attempt_started,
    mark_message_delivery_retrying,
)
from workspaces.factories import WorkspaceAIProviderConfigFactory


def _run() -> AIProcessingRun:
    conversation = ConversationFactory()
    source_message = MessageFactory(
        conversation=conversation,
        direction=Message.Direction.INBOUND,
    )
    provider_config = WorkspaceAIProviderConfigFactory(workspace=conversation.workspace)
    return AIProcessingRun.objects.create(
        workspace=conversation.workspace,
        conversation=conversation,
        source_message=source_message,
        provider_config=provider_config,
    )


@pytest.mark.django_db
def test_mark_ai_processing_attempt_started_increments_and_sets_timestamp() -> None:
    run = _run()

    updated = mark_ai_processing_attempt_started(run=run)

    assert updated.attempt_count == 1
    assert updated.last_attempt_at is not None
    assert updated.status == AIProcessingRun.Status.RUNNING


@pytest.mark.django_db
def test_mark_ai_processing_retrying_sets_retry_diagnostics() -> None:
    run = mark_ai_processing_attempt_started(run=_run())
    next_retry_at = timezone.now() + timedelta(seconds=60)

    updated = mark_ai_processing_retrying(
        run=run,
        error_code='provider timeout: sk-secret',
        next_retry_at=next_retry_at,
    )

    assert updated.status == AIProcessingRun.Status.RETRYING
    assert updated.last_error_code == 'PROVIDER_TIMEOUT__REDACTED'
    assert updated.error_code == ''
    assert updated.next_retry_at == next_retry_at


@pytest.mark.django_db
def test_can_retry_ai_processing_respects_max_attempts() -> None:
    run = _run()
    run.attempt_count = MAX_AI_PROVIDER_ATTEMPTS - 1
    assert can_retry_ai_processing(run=run) is True

    run.attempt_count = MAX_AI_PROVIDER_ATTEMPTS
    assert can_retry_ai_processing(run=run) is False


@pytest.mark.django_db
def test_get_retryable_ai_processing_run_validates_source_message() -> None:
    run = _run()
    run.status = AIProcessingRun.Status.RETRYING
    run.save(update_fields=['status', 'updated_at'])
    other_source = MessageFactory(direction=Message.Direction.INBOUND)

    assert get_retryable_ai_processing_run(run_id=str(run.id), source_message=run.source_message) == run
    assert get_retryable_ai_processing_run(run_id=str(run.id), source_message=other_source) is None


@pytest.mark.django_db
def test_mark_message_delivery_attempt_started_increments_and_sets_timestamp() -> None:
    message = MessageFactory(
        direction=Message.Direction.OUTBOUND,
        status=Message.Status.PENDING,
    )

    updated = mark_message_delivery_attempt_started(message=message)

    assert updated.send_attempt_count == 1
    assert updated.last_send_attempt_at is not None


@pytest.mark.django_db
def test_mark_message_delivery_retrying_keeps_pending_and_sets_diagnostics() -> None:
    message = mark_message_delivery_attempt_started(
        message=MessageFactory(
            direction=Message.Direction.OUTBOUND,
            status=Message.Status.PENDING,
        ),
    )
    next_retry_at = timezone.now() + timedelta(seconds=60)

    updated = mark_message_delivery_retrying(
        message=message,
        error_code='evolution timeout: api_key',
        next_retry_at=next_retry_at,
    )

    assert updated.status == Message.Status.PENDING
    assert updated.send_error_code == 'EVOLUTION_TIMEOUT__REDACTED'
    assert updated.next_send_retry_at == next_retry_at


@pytest.mark.django_db
def test_can_retry_message_delivery_respects_max_attempts() -> None:
    message = MessageFactory(direction=Message.Direction.OUTBOUND)
    message.send_attempt_count = MAX_OUTBOUND_DELIVERY_ATTEMPTS - 1
    assert can_retry_message_delivery(message=message) is True

    message.send_attempt_count = MAX_OUTBOUND_DELIVERY_ATTEMPTS
    assert can_retry_message_delivery(message=message) is False


def test_retry_helpers_use_transactions_and_locks() -> None:
    helper_sources = [
        inspect.getsource(mark_ai_processing_attempt_started),
        inspect.getsource(mark_ai_processing_retrying),
        inspect.getsource(get_retryable_ai_processing_run),
        inspect.getsource(mark_message_delivery_attempt_started),
        inspect.getsource(mark_message_delivery_retrying),
    ]

    assert all('transaction.atomic' in source for source in helper_sources)
    assert all('select_for_update' in source for source in helper_sources)


@pytest.mark.django_db
def test_retry_helpers_do_not_call_openai_evolution_or_leak_sensitive_logs(caplog) -> None:
    caplog.set_level(logging.INFO)
    run = _run()
    run.provider_config.api_key = 'sk-helper-secret-key'
    run.provider_config.save(update_fields=['api_key'])
    message = MessageFactory(
        direction=Message.Direction.OUTBOUND,
        status=Message.Status.PENDING,
        body='Texto sensivel para nao logar.',
    )

    with (
        patch('omnichannel.ai.providers.openai.openai.OpenAI') as mock_openai,
        patch('omnichannel.services.send_whatsapp_message') as mock_evolution,
    ):
        mark_ai_processing_attempt_started(run=run)
        mark_ai_processing_retrying(
            run=run,
            error_code='AI_PROVIDER_TIMEOUT',
            next_retry_at=timezone.now() + timedelta(seconds=60),
        )
        mark_message_delivery_attempt_started(message=message)
        mark_message_delivery_retrying(
            message=message,
            error_code='EVOLUTION_TIMEOUT',
            next_retry_at=timezone.now() + timedelta(seconds=60),
        )

    mock_openai.assert_not_called()
    mock_evolution.assert_not_called()
    assert 'sk-helper-secret-key' not in caplog.text
    assert 'Texto sensivel para nao logar.' not in caplog.text
    assert 'payload' not in caplog.text
