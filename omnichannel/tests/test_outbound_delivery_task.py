from __future__ import annotations

import logging
from unittest.mock import patch

import pytest
import requests
from celery.exceptions import Retry

from omnichannel.factories import MessageFactory
from omnichannel.models import Message
from omnichannel.tasks import send_outbound_whatsapp_message


@pytest.mark.django_db
def test_send_outbound_whatsapp_message_sends_pending_message_and_marks_sent() -> None:
    message = MessageFactory(
        direction=Message.Direction.OUTBOUND,
        status=Message.Status.PENDING,
        body='Resposta para enviar.',
        conversation__contact__phone='5511999999999',
        send_error_code='EVOLUTION_TIMEOUT',
    )

    with patch(
        'omnichannel.services.send_whatsapp_message',
        return_value={'key': {'id': 'evolution-message-id'}},
    ) as mock_send:
        result = send_outbound_whatsapp_message.run(str(message.id))

    message.refresh_from_db()
    assert result == str(message.id)
    assert message.status == Message.Status.SENT
    assert message.external_id == 'evolution-message-id'
    assert message.send_error_code == ''
    assert message.next_send_retry_at is None
    assert message.send_attempt_count == 1
    assert message.last_send_attempt_at is not None
    mock_send.assert_called_once_with('5511999999999', 'Resposta para enviar.')


@pytest.mark.django_db
def test_send_outbound_whatsapp_message_already_sent_is_idempotent() -> None:
    message = MessageFactory(
        direction=Message.Direction.OUTBOUND,
        status=Message.Status.SENT,
    )

    with patch('omnichannel.services.send_whatsapp_message') as mock_send:
        result = send_outbound_whatsapp_message.run(str(message.id))

    assert result == str(message.id)
    mock_send.assert_not_called()


@pytest.mark.django_db
def test_send_outbound_whatsapp_message_ignores_inbound_message() -> None:
    message = MessageFactory(
        direction=Message.Direction.INBOUND,
        status=Message.Status.DELIVERED,
    )

    with patch('omnichannel.services.send_whatsapp_message') as mock_send:
        result = send_outbound_whatsapp_message.run(str(message.id))

    assert result is None
    mock_send.assert_not_called()


@pytest.mark.django_db
@pytest.mark.parametrize(
    ('exception', 'expected_error_code'),
    [
        (requests.exceptions.Timeout('timeout'), 'EVOLUTION_TIMEOUT'),
        (requests.exceptions.ConnectionError('connection'), 'EVOLUTION_CONNECTION_ERROR'),
        (requests.exceptions.RequestException('request'), 'EVOLUTION_REQUEST_ERROR'),
    ],
)
def test_send_outbound_whatsapp_message_retryable_error_schedules_retry(
    exception: Exception,
    expected_error_code: str,
    caplog,
) -> None:
    message = MessageFactory(
        direction=Message.Direction.OUTBOUND,
        status=Message.Status.PENDING,
        body='Texto que nao deve vazar.',
    )
    caplog.set_level(logging.WARNING)

    with (
        patch('omnichannel.services.send_whatsapp_message', side_effect=exception) as mock_send,
        patch.object(send_outbound_whatsapp_message, 'retry', side_effect=Retry('retry')) as mock_retry,
        patch('omnichannel.ai.registry.get_provider_adapter') as mock_adapter,
    ):
        with pytest.raises(Retry):
            send_outbound_whatsapp_message.run(str(message.id))

    message.refresh_from_db()
    assert message.status == Message.Status.PENDING
    assert message.send_attempt_count == 1
    assert message.send_error_code == expected_error_code
    assert message.next_send_retry_at is not None
    assert mock_retry.call_args.kwargs['countdown'] == 60
    mock_send.assert_called_once()
    mock_adapter.assert_not_called()
    assert 'Texto que nao deve vazar.' not in caplog.text
    assert 'api_key' not in caplog.text
    assert 'payload' not in caplog.text


@pytest.mark.django_db
def test_send_outbound_whatsapp_message_exhausted_retries_marks_failed_without_new_message() -> None:
    message = MessageFactory(
        direction=Message.Direction.OUTBOUND,
        status=Message.Status.PENDING,
        send_attempt_count=2,
    )

    with (
        patch('omnichannel.services.send_whatsapp_message', side_effect=requests.exceptions.Timeout('timeout')),
        patch.object(send_outbound_whatsapp_message, 'retry') as mock_retry,
        patch('omnichannel.ai.registry.get_provider_adapter') as mock_adapter,
    ):
        result = send_outbound_whatsapp_message.run(str(message.id))

    message.refresh_from_db()
    assert result == str(message.id)
    assert message.status == Message.Status.FAILED
    assert message.send_attempt_count == 3
    assert message.send_error_code == 'EVOLUTION_TIMEOUT'
    assert Message.objects.filter(conversation=message.conversation).count() == 1
    mock_retry.assert_not_called()
    mock_adapter.assert_not_called()


@pytest.mark.django_db
@pytest.mark.parametrize(
    ('exception', 'expected_error_code'),
    [
        (ValueError('invalid response'), 'EVOLUTION_INVALID_RESPONSE'),
        (RuntimeError('unknown'), 'EVOLUTION_UNKNOWN_ERROR'),
    ],
)
def test_send_outbound_whatsapp_message_permanent_error_marks_failed(
    exception: Exception,
    expected_error_code: str,
) -> None:
    message = MessageFactory(
        direction=Message.Direction.OUTBOUND,
        status=Message.Status.PENDING,
    )

    with (
        patch('omnichannel.services.send_whatsapp_message', side_effect=exception),
        patch.object(send_outbound_whatsapp_message, 'retry') as mock_retry,
    ):
        result = send_outbound_whatsapp_message.run(str(message.id))

    message.refresh_from_db()
    assert result == str(message.id)
    assert message.status == Message.Status.FAILED
    assert message.send_attempt_count == 1
    assert message.send_error_code == expected_error_code
    mock_retry.assert_not_called()


@pytest.mark.django_db
def test_send_outbound_whatsapp_message_failed_status_is_not_retried() -> None:
    message = MessageFactory(
        direction=Message.Direction.OUTBOUND,
        status=Message.Status.FAILED,
        send_error_code='EVOLUTION_TIMEOUT',
    )

    with patch('omnichannel.services.send_whatsapp_message') as mock_send:
        result = send_outbound_whatsapp_message.run(str(message.id))

    message.refresh_from_db()
    assert result is None
    assert message.status == Message.Status.FAILED
    assert Message.objects.filter(conversation=message.conversation).count() == 1
    mock_send.assert_not_called()
