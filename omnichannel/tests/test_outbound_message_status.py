from __future__ import annotations

import inspect
import logging
from datetime import timedelta
from unittest.mock import patch

import pytest
from django.utils import timezone

from omnichannel.factories import ConversationFactory, MessageFactory
from omnichannel.models import Message
from omnichannel.services import (
    claim_message_delivery_attempt,
    create_pending_ai_message,
    extract_evolution_message_external_id,
    mark_message_as_failed,
    mark_message_as_sent,
    mark_message_delivery_retrying,
    sanitize_message_send_error_code,
)


@pytest.mark.django_db
def test_create_pending_ai_message_creates_outbound_pending() -> None:
    conversation = ConversationFactory()

    message = create_pending_ai_message(
        conversation=conversation,
        body='Resposta criada antes do envio.',
    )

    assert message.conversation == conversation
    assert message.direction == Message.Direction.OUTBOUND
    assert message.status == Message.Status.PENDING
    assert message.external_id is None
    assert message.send_error_code == ''


@pytest.mark.django_db
def test_create_pending_ai_message_does_not_call_external_services() -> None:
    conversation = ConversationFactory()

    with (
        patch('omnichannel.services.send_whatsapp_message') as mock_evolution,
        patch('omnichannel.ai.providers.openai.openai.OpenAI') as mock_openai,
    ):
        create_pending_ai_message(conversation=conversation, body='Sem chamadas externas.')

    mock_evolution.assert_not_called()
    mock_openai.assert_not_called()


@pytest.mark.django_db
def test_mark_message_as_sent_updates_status_external_id_and_clears_error() -> None:
    message = MessageFactory(
        direction=Message.Direction.OUTBOUND,
        status=Message.Status.PENDING,
        external_id=None,
        send_error_code='EVOLUTION_TIMEOUT',
    )

    updated = mark_message_as_sent(
        message=message,
        external_id='wamid-success-id',
    )

    assert updated.status == Message.Status.SENT
    assert updated.external_id == 'wamid-success-id'
    assert updated.send_error_code == ''


@pytest.mark.django_db
def test_mark_message_as_failed_updates_status_and_error_without_mutating_body_or_external_id() -> None:
    message = MessageFactory(
        direction=Message.Direction.OUTBOUND,
        status=Message.Status.PENDING,
        body='Resposta que falhou no envio.',
        external_id='already-known-id',
    )

    updated = mark_message_as_failed(
        message=message,
        error_code='evolution timeout!',
    )

    assert updated.status == Message.Status.FAILED
    assert updated.send_error_code == 'EVOLUTION_TIMEOUT_'
    assert updated.body == 'Resposta que falhou no envio.'
    assert updated.external_id == 'already-known-id'
    assert Message.objects.filter(conversation=message.conversation).count() == 1


@pytest.mark.parametrize(
    ('payload', 'expected'),
    [
        ({'key': {'id': 'key-id'}}, 'key-id'),
        ({'data': {'key': {'id': 'data-key-id'}}}, 'data-key-id'),
        ({'message': {'key': {'id': 'message-key-id'}}}, 'message-key-id'),
        ({'id': 'root-id'}, 'root-id'),
        ({'unexpected': True}, None),
        ([], None),
    ],
)
def test_extract_evolution_message_external_id_handles_common_formats(payload, expected) -> None:
    assert extract_evolution_message_external_id(payload) == expected


def test_sanitize_message_send_error_code_removes_dangerous_characters_and_limits_length() -> None:
    raw = 'error: sk-secret\nAuthorization header ' + ('x' * 80)

    sanitized = sanitize_message_send_error_code(raw)

    assert sanitized == 'ERROR__REDACTED'
    assert '\n' not in sanitized
    assert ':' not in sanitized


def test_outbound_helpers_use_transactions_and_locks() -> None:
    sent_source = inspect.getsource(mark_message_as_sent)
    failed_source = inspect.getsource(mark_message_as_failed)

    assert 'transaction.atomic' in sent_source
    assert 'select_for_update' in sent_source
    assert 'transaction.atomic' in failed_source
    assert 'select_for_update' in failed_source


@pytest.mark.django_db
def test_outbound_helpers_logs_do_not_leak_body_api_key_or_payload(caplog) -> None:
    caplog.set_level(logging.INFO)
    message = MessageFactory(
        direction=Message.Direction.OUTBOUND,
        status=Message.Status.PENDING,
        body='Texto sensivel da IA',
    )

    mark_message_as_failed(message=message, error_code='EVOLUTION_REQUEST_ERROR')

    assert 'Texto sensivel da IA' not in caplog.text
    assert 'api_key' not in caplog.text
    assert 'payload' not in caplog.text


@pytest.mark.django_db
@pytest.mark.parametrize(
    'positive_status',
    [Message.Status.SENT, Message.Status.DELIVERED, Message.Status.READ],
)
def test_mark_message_as_failed_never_downgrades_positive_status(
    positive_status: str,
) -> None:
    existing_retry_at = timezone.now() + timedelta(minutes=5)
    message = MessageFactory(
        direction=Message.Direction.OUTBOUND,
        status=positive_status,
        external_id='existing-provider-id',
        send_error_code='EXISTING_ERROR',
        next_send_retry_at=existing_retry_at,
    )

    updated = mark_message_as_failed(
        message=message,
        error_code='LATE_FAILURE',
    )

    assert updated.status == positive_status
    assert updated.external_id == 'existing-provider-id'
    assert updated.send_error_code == 'EXISTING_ERROR'
    assert updated.next_send_retry_at == existing_retry_at


@pytest.mark.django_db
@pytest.mark.parametrize(
    'advanced_status',
    [Message.Status.DELIVERED, Message.Status.READ],
)
def test_mark_message_as_sent_never_downgrades_advanced_status(
    advanced_status: str,
) -> None:
    message = MessageFactory(
        direction=Message.Direction.OUTBOUND,
        status=advanced_status,
        external_id='existing-provider-id',
        send_error_code='STALE_ERROR',
        next_send_retry_at=timezone.now() + timedelta(minutes=5),
    )

    updated = mark_message_as_sent(
        message=message,
        external_id='replacement-provider-id',
    )

    assert updated.status == advanced_status
    assert updated.external_id == 'existing-provider-id'
    assert updated.send_error_code == ''
    assert updated.next_send_retry_at is None


@pytest.mark.django_db
def test_mark_message_as_sent_can_confirm_a_later_success_from_failed() -> None:
    message = MessageFactory(
        direction=Message.Direction.OUTBOUND,
        status=Message.Status.FAILED,
        external_id=None,
        send_error_code='EARLIER_FAILURE',
    )

    updated = mark_message_as_sent(
        message=message,
        external_id='confirmed-provider-id',
    )

    assert updated.status == Message.Status.SENT
    assert updated.external_id == 'confirmed-provider-id'
    assert updated.send_error_code == ''


@pytest.mark.django_db
@pytest.mark.parametrize(
    'protected_status',
    [Message.Status.SENT, Message.Status.DELIVERED, Message.Status.READ],
)
def test_mark_message_delivery_retrying_never_downgrades_positive_status(
    protected_status: str,
) -> None:
    existing_retry_at = timezone.now() + timedelta(minutes=3)
    message = MessageFactory(
        direction=Message.Direction.OUTBOUND,
        status=protected_status,
        external_id='existing-provider-id',
        send_error_code='EXISTING_ERROR',
        next_send_retry_at=existing_retry_at,
    )

    updated = mark_message_delivery_retrying(
        message=message,
        error_code='LATE_RETRY',
        next_retry_at=timezone.now() + timedelta(minutes=10),
    )

    assert updated.status == protected_status
    assert updated.external_id == 'existing-provider-id'
    assert updated.send_error_code == 'EXISTING_ERROR'
    assert updated.next_send_retry_at == existing_retry_at


@pytest.mark.django_db
def test_mark_message_delivery_retrying_does_not_reopen_failed_message() -> None:
    message = MessageFactory(
        direction=Message.Direction.OUTBOUND,
        status=Message.Status.FAILED,
        send_error_code='FINAL_FAILURE',
    )

    updated = mark_message_delivery_retrying(
        message=message,
        error_code='LATE_RETRY',
        next_retry_at=timezone.now() + timedelta(minutes=10),
    )

    assert updated.status == Message.Status.FAILED
    assert updated.send_error_code == 'FINAL_FAILURE'
    assert updated.next_send_retry_at is None


@pytest.mark.django_db
@pytest.mark.parametrize(
    'terminal_status',
    [
        Message.Status.SENT,
        Message.Status.DELIVERED,
        Message.Status.READ,
        Message.Status.FAILED,
    ],
)
def test_claim_does_not_increment_non_pending_message(terminal_status: str) -> None:
    message = MessageFactory(
        direction=Message.Direction.OUTBOUND,
        status=terminal_status,
        send_attempt_count=2,
    )

    claimed = claim_message_delivery_attempt(message_id=message.id)

    message.refresh_from_db()
    assert claimed is None
    assert message.status == terminal_status
    assert message.send_attempt_count == 2
