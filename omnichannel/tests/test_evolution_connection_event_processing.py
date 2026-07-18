from __future__ import annotations

import logging
from unittest.mock import patch

import pytest
from django.core.cache import cache

from omnichannel.evolution_event_processing import process_evolution_channel_event
from omnichannel.evolution_qr_cache import get_evolution_qr_code, store_evolution_qr_code
from omnichannel.factories import WhatsAppChannelFactory
from omnichannel.models import Conversation, EvolutionWebhookEvent, Message, WhatsAppChannel

pytestmark = pytest.mark.django_db


def _payload(state: str, **data) -> dict:
    return {
        'event': 'connection.update',
        'workspace_id': 'untrusted-workspace',
        'data': {'state': state, 'timestamp': f'2026-07-18T20:00:0{len(state)}Z', **data},
    }


@pytest.fixture(autouse=True)
def clear_qr_cache():
    cache.clear()
    yield
    cache.clear()


@pytest.mark.parametrize(
    ('provider_state', 'expected_status'),
    [
        ('open', WhatsAppChannel.Status.CONNECTED),
        ('connected', WhatsAppChannel.Status.CONNECTED),
        ('connecting', WhatsAppChannel.Status.CONNECTING),
        ('reconnecting', WhatsAppChannel.Status.RECONNECTING),
        ('close', WhatsAppChannel.Status.DISCONNECTED),
        ('closed', WhatsAppChannel.Status.DISCONNECTED),
        ('disconnected', WhatsAppChannel.Status.DISCONNECTED),
        ('error', WhatsAppChannel.Status.ERROR),
        ('qr', WhatsAppChannel.Status.WAITING_QR),
        ('qrcode', WhatsAppChannel.Status.WAITING_QR),
        ('waiting_qr', WhatsAppChannel.Status.WAITING_QR),
    ],
)
def test_connection_states_are_mapped(provider_state: str, expected_status: str) -> None:
    channel = WhatsAppChannelFactory()
    process_evolution_channel_event(channel=channel, payload=_payload(provider_state))

    channel.refresh_from_db()
    event = EvolutionWebhookEvent.objects.get(whatsapp_channel=channel)
    assert channel.status == expected_status
    assert channel.last_connection_update_at is not None
    assert event.status == EvolutionWebhookEvent.Status.PROCESSED


def test_connected_sets_history_clears_error_and_stores_valid_phone() -> None:
    channel = WhatsAppChannelFactory(last_error_code='OLD_ERROR')
    process_evolution_channel_event(
        channel=channel,
        payload=_payload('open', wuid='5511999999999:12@s.whatsapp.net'),
    )

    channel.refresh_from_db()
    assert channel.status == WhatsAppChannel.Status.CONNECTED
    assert channel.connected_at is not None
    assert channel.last_error_code == ''
    assert channel.phone_number == '5511999999999'


@pytest.mark.parametrize('invalid_phone', ['abc@s.whatsapp.net', '123', {}, '5511@g.us'])
def test_invalid_phone_is_not_stored(invalid_phone) -> None:
    channel = WhatsAppChannelFactory(phone_number='')
    process_evolution_channel_event(
        channel=channel,
        payload=_payload('connected', phoneNumber=invalid_phone),
    )
    channel.refresh_from_db()
    assert channel.phone_number == ''


def test_error_stores_only_safe_code_not_raw_detail() -> None:
    channel = WhatsAppChannelFactory()
    payload = _payload('error', statusReason='private raw failure detail')
    process_evolution_channel_event(channel=channel, payload=payload)

    channel.refresh_from_db()
    assert channel.status == WhatsAppChannel.Status.ERROR
    assert channel.last_error_code == 'EVOLUTION_CONNECTION_ERROR'
    assert 'PRIVATE_RAW' not in channel.last_error_code


def test_enum_like_error_reason_is_sanitized() -> None:
    channel = WhatsAppChannelFactory()
    process_evolution_channel_event(
        channel=channel,
        payload=_payload('error', statusReason='authentication-failed'),
    )
    channel.refresh_from_db()
    assert channel.last_error_code == 'AUTHENTICATION_FAILED'


def test_unknown_connection_state_is_ignored() -> None:
    channel = WhatsAppChannelFactory(status=WhatsAppChannel.Status.DISCONNECTED)
    process_evolution_channel_event(channel=channel, payload=_payload('private-state'))

    channel.refresh_from_db()
    event = EvolutionWebhookEvent.objects.get(whatsapp_channel=channel)
    assert channel.status == WhatsAppChannel.Status.DISCONNECTED
    assert event.status == EvolutionWebhookEvent.Status.IGNORED
    assert event.error_code == 'UNSUPPORTED_CONNECTION_STATE'


@pytest.mark.parametrize('late_state', ['connecting', 'qr'])
def test_late_transitional_state_does_not_downgrade_connected_channel(late_state: str) -> None:
    channel = WhatsAppChannelFactory(status=WhatsAppChannel.Status.CONNECTED)
    process_evolution_channel_event(channel=channel, payload=_payload(late_state))
    channel.refresh_from_db()
    assert channel.status == WhatsAppChannel.Status.CONNECTED


def test_explicit_close_can_disconnect_connected_channel() -> None:
    channel = WhatsAppChannelFactory(status=WhatsAppChannel.Status.CONNECTED)
    process_evolution_channel_event(channel=channel, payload=_payload('close'))
    channel.refresh_from_db()
    assert channel.status == WhatsAppChannel.Status.DISCONNECTED


def test_connected_removes_cached_qr_best_effort() -> None:
    channel = WhatsAppChannelFactory()
    store_evolution_qr_code(channel.id, 'D' * 128)
    process_evolution_channel_event(channel=channel, payload=_payload('connected'))
    assert get_evolution_qr_code(channel.id) is None


def test_qr_cache_delete_failure_does_not_rollback_connected_state() -> None:
    channel = WhatsAppChannelFactory()
    with patch('omnichannel.evolution_qr_cache.cache.delete', side_effect=RuntimeError):
        process_evolution_channel_event(channel=channel, payload=_payload('connected'))
    channel.refresh_from_db()
    assert channel.status == WhatsAppChannel.Status.CONNECTED


def test_connection_event_is_idempotent_and_has_no_domain_message_side_effects() -> None:
    channel = WhatsAppChannelFactory()
    payload = _payload('connected')
    baseline = (Conversation.objects.count(), Message.objects.count())

    process_evolution_channel_event(channel=channel, payload=payload)
    process_evolution_channel_event(channel=channel, payload=payload)

    assert EvolutionWebhookEvent.objects.filter(whatsapp_channel=channel).count() == 1
    assert (Conversation.objects.count(), Message.objects.count()) == baseline


def test_payload_workspace_does_not_control_channel_or_other_workspace() -> None:
    first = WhatsAppChannelFactory()
    other = WhatsAppChannelFactory(status=WhatsAppChannel.Status.ERROR)
    payload = _payload('connected')
    payload['workspace_id'] = str(other.workspace_id)

    process_evolution_channel_event(channel=first, payload=payload)

    first.refresh_from_db()
    other.refresh_from_db()
    assert first.status == WhatsAppChannel.Status.CONNECTED
    assert other.status == WhatsAppChannel.Status.ERROR


def test_connection_logs_exclude_phone_and_raw_error(caplog) -> None:
    channel = WhatsAppChannelFactory()
    phone = '5511888888888'
    raw_error = 'private raw connection error'
    caplog.set_level(logging.INFO, logger='omnichannel.evolution_event_processing')

    process_evolution_channel_event(
        channel=channel,
        payload=_payload('error', sender=f'{phone}@s.whatsapp.net', statusReason=raw_error),
    )

    rendered = ' '.join(record.getMessage() + repr(record.__dict__) for record in caplog.records)
    assert phone not in rendered
    assert raw_error not in rendered


def test_connection_processing_never_calls_ai_or_http() -> None:
    channel = WhatsAppChannelFactory()
    with (
        patch('omnichannel.tasks.process_ai_response.delay') as ai_task,
        patch('requests.sessions.Session.request') as request,
    ):
        process_evolution_channel_event(channel=channel, payload=_payload('connected'))
    ai_task.assert_not_called()
    request.assert_not_called()
