from __future__ import annotations

import logging
from unittest.mock import patch
from uuid import uuid4

import pytest

from crm.models import Contact
from omnichannel.factories import WhatsAppChannelFactory
from omnichannel.models import Conversation, Message
from omnichannel.tasks import process_evolution_channel_webhook_task

pytestmark = pytest.mark.django_db


def _module_log_text(caplog: pytest.LogCaptureFixture) -> str:
    records = [record for record in caplog.records if record.name == 'omnichannel.tasks']
    return ' '.join(
        f'{record.getMessage()} {record.__dict__}'
        for record in records
    )


def test_evolution_channel_webhook_task_resolves_channel_and_workspace_from_channel(
    caplog: pytest.LogCaptureFixture,
) -> None:
    channel = WhatsAppChannelFactory(webhook_secret='private-webhook-secret')
    caplog.set_level(logging.INFO, logger='omnichannel.tasks')

    result = process_evolution_channel_webhook_task(
        str(channel.id),
        {'event': 'messages.upsert'},
    )

    assert result is None
    record = next(
        record
        for record in caplog.records
        if record.getMessage().startswith('Task de webhook Evolution recebeu')
    )
    assert record.channel_id == str(channel.id)
    assert record.workspace_id == str(channel.workspace_id)
    assert record.event_type == 'MESSAGES_UPSERT'


@pytest.mark.parametrize('channel_id', ['invalid-id', '', None, 123])
def test_evolution_channel_webhook_task_ignores_invalid_channel_id_safely(
    channel_id,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger='omnichannel.tasks')

    result = process_evolution_channel_webhook_task(
        channel_id,
        {'event': 'MESSAGES_UPSERT'},
    )

    assert result is None
    assert 'InvalidChannelId' in _module_log_text(caplog)
    if channel_id == 'invalid-id':
        assert channel_id not in _module_log_text(caplog)


def test_evolution_channel_webhook_task_ignores_removed_channel_safely(
    caplog: pytest.LogCaptureFixture,
) -> None:
    missing_id = uuid4()
    caplog.set_level(logging.INFO, logger='omnichannel.tasks')

    result = process_evolution_channel_webhook_task(
        str(missing_id),
        {'event': 'MESSAGES_UPSERT'},
    )

    assert result is None
    assert 'WhatsAppChannelDoesNotExist' in _module_log_text(caplog)


@pytest.mark.parametrize(
    ('event_value', 'expected_event'),
    [
        ('qrcode.updated', 'QRCODE_UPDATED'),
        ('CONNECTION_UPDATE', 'CONNECTION_UPDATE'),
        ('messages.upsert', 'MESSAGES_UPSERT'),
        ('messages.update', 'MESSAGES_UPDATE'),
        ('send.message', 'SEND_MESSAGE'),
        ('private-message-or-secret', 'UNSUPPORTED_EVENT'),
        (None, 'UNKNOWN_EVENT'),
    ],
)
def test_evolution_channel_webhook_task_sanitizes_event_for_logs(
    event_value,
    expected_event: str,
    caplog: pytest.LogCaptureFixture,
) -> None:
    channel = WhatsAppChannelFactory()
    caplog.set_level(logging.INFO, logger='omnichannel.tasks')

    process_evolution_channel_webhook_task(
        str(channel.id),
        {'event': event_value},
    )

    record = next(record for record in caplog.records if hasattr(record, 'event_type'))
    assert record.event_type == expected_event
    if expected_event == 'UNSUPPORTED_EVENT':
        assert str(event_value) not in _module_log_text(caplog)


def test_evolution_channel_webhook_task_never_logs_payload_message_phone_qr_or_secret(
    caplog: pytest.LogCaptureFixture,
) -> None:
    channel = WhatsAppChannelFactory(webhook_secret='private-channel-secret')
    sensitive_values = (
        channel.webhook_secret,
        'private-message-content',
        '5511999999999',
        'private-qr-base64',
    )
    payload = {
        'event': 'MESSAGES_UPSERT',
        'message': sensitive_values[1],
        'phone': sensitive_values[2],
        'qrcode': sensitive_values[3],
        'secret': sensitive_values[0],
    }
    caplog.set_level(logging.INFO, logger='omnichannel.tasks')

    process_evolution_channel_webhook_task(str(channel.id), payload)

    log_text = _module_log_text(caplog)
    for sensitive_value in sensitive_values:
        assert sensitive_value not in log_text


def test_evolution_channel_webhook_task_creates_no_domain_objects() -> None:
    channel = WhatsAppChannelFactory()
    baseline = (Contact.objects.count(), Conversation.objects.count(), Message.objects.count())

    process_evolution_channel_webhook_task(
        str(channel.id),
        {'event': 'MESSAGES_UPSERT', 'data': {}},
    )

    assert (Contact.objects.count(), Conversation.objects.count(), Message.objects.count()) == baseline


def test_evolution_channel_webhook_task_does_not_call_legacy_ai_or_http() -> None:
    channel = WhatsAppChannelFactory()

    with (
        patch('omnichannel.services.process_whatsapp_payload') as legacy_processor,
        patch('omnichannel.tasks.process_whatsapp_webhook_task.delay') as legacy_task,
        patch('omnichannel.tasks.process_ai_response.delay') as ai_task,
        patch('requests.sessions.Session.request') as http_request,
    ):
        process_evolution_channel_webhook_task(
            str(channel.id),
            {'event': 'MESSAGES_UPSERT'},
        )

    legacy_processor.assert_not_called()
    legacy_task.assert_not_called()
    ai_task.assert_not_called()
    http_request.assert_not_called()


def test_evolution_channel_webhook_task_handles_non_mapping_payload_without_leak(
    caplog: pytest.LogCaptureFixture,
) -> None:
    channel = WhatsAppChannelFactory()
    caplog.set_level(logging.INFO, logger='omnichannel.tasks')

    result = process_evolution_channel_webhook_task(  # type: ignore[arg-type]
        str(channel.id),
        ['private-payload-content'],
    )

    assert result is None
    assert 'UNKNOWN_EVENT' in _module_log_text(caplog)
    assert 'private-payload-content' not in _module_log_text(caplog)
