from __future__ import annotations

import logging
from unittest.mock import patch

import pytest
from django.core.cache import cache

from omnichannel.evolution_event_processing import (
    EvolutionEventProcessingError,
    process_evolution_channel_event,
)
from omnichannel.evolution_qr_cache import (
    get_evolution_qr_cache_key,
    get_evolution_qr_code,
)
from omnichannel.factories import WhatsAppChannelFactory
from omnichannel.models import EvolutionWebhookEvent, WhatsAppChannel

pytestmark = pytest.mark.django_db

VALID_QR = 'A' * 128


@pytest.fixture(autouse=True)
def clear_qr_cache():
    cache.clear()
    yield
    cache.clear()


def _payload(qr_code: object = VALID_QR) -> dict:
    return {
        'event': 'qrcode.updated',
        'data': {'qrcode': {'base64': qr_code}},
    }


def test_valid_qr_is_cached_and_channel_waits_without_database_storage(settings) -> None:
    settings.EVOLUTION_QR_TTL_SECONDS = 120
    channel = WhatsAppChannelFactory(
        status=WhatsAppChannel.Status.ERROR,
        last_error_code='OLD_ERROR',
    )

    with patch('omnichannel.evolution_qr_cache.cache.set', wraps=cache.set) as cache_set:
        process_evolution_channel_event(channel=channel, payload=_payload())

    channel.refresh_from_db()
    event = EvolutionWebhookEvent.objects.get(whatsapp_channel=channel)
    assert get_evolution_qr_code(channel.id) == VALID_QR
    cache_set.assert_called_once_with(
        get_evolution_qr_cache_key(channel.id),
        VALID_QR,
        timeout=120,
    )
    assert channel.status == WhatsAppChannel.Status.WAITING_QR
    assert channel.last_error_code == ''
    assert channel.last_connection_update_at is not None
    assert event.status == EvolutionWebhookEvent.Status.PROCESSED
    assert VALID_QR not in event.deduplication_key
    assert VALID_QR not in repr(event.__dict__)
    assert not any(
        field.name in {'qr', 'qrcode', 'base64', 'pairingCode'}
        for field in WhatsAppChannel._meta.fields
    )


@pytest.mark.parametrize(
    'payload',
    [
        {'event': 'QRCODE_UPDATED', 'data': {'base64': VALID_QR}},
        {'event': 'QRCODE_UPDATED', 'qrcode': {'base64': VALID_QR}},
        {
            'event': 'QRCODE_UPDATED',
            'data': {'base64': 'data:image/png;base64,' + VALID_QR},
        },
    ],
)
def test_supported_qr_shapes_are_accepted(payload: dict) -> None:
    channel = WhatsAppChannelFactory()
    process_evolution_channel_event(channel=channel, payload=payload)
    assert get_evolution_qr_code(channel.id) is not None


@pytest.mark.parametrize('invalid_qr', [None, '', {'base64': VALID_QR}, 'bad value!', 'A\nB'])
def test_invalid_or_missing_qr_is_ignored_without_channel_change(invalid_qr) -> None:
    channel = WhatsAppChannelFactory(status=WhatsAppChannel.Status.DISCONNECTED)
    process_evolution_channel_event(channel=channel, payload=_payload(invalid_qr))

    channel.refresh_from_db()
    event = EvolutionWebhookEvent.objects.get(whatsapp_channel=channel)
    assert channel.status == WhatsAppChannel.Status.DISCONNECTED
    assert get_evolution_qr_code(channel.id) is None
    assert event.status == EvolutionWebhookEvent.Status.IGNORED
    assert event.error_code == 'INVALID_QR_CODE'


def test_late_qr_does_not_downgrade_connected_channel() -> None:
    channel = WhatsAppChannelFactory(status=WhatsAppChannel.Status.CONNECTED)
    process_evolution_channel_event(channel=channel, payload=_payload())

    channel.refresh_from_db()
    event = EvolutionWebhookEvent.objects.get(whatsapp_channel=channel)
    assert channel.status == WhatsAppChannel.Status.CONNECTED
    assert get_evolution_qr_code(channel.id) is None
    assert event.status == EvolutionWebhookEvent.Status.IGNORED


def test_duplicate_qr_reuses_receipt_and_renews_cache() -> None:
    channel = WhatsAppChannelFactory()
    process_evolution_channel_event(channel=channel, payload=_payload())
    cache.delete(get_evolution_qr_cache_key(channel.id))

    process_evolution_channel_event(channel=channel, payload=_payload())

    assert get_evolution_qr_code(channel.id) == VALID_QR
    assert EvolutionWebhookEvent.objects.filter(whatsapp_channel=channel).count() == 1


def test_cache_failure_marks_receipt_failed_and_is_retryable() -> None:
    channel = WhatsAppChannelFactory()
    with (
        patch('omnichannel.evolution_qr_cache.cache.set', side_effect=RuntimeError),
        pytest.raises(EvolutionEventProcessingError) as raised,
    ):
        process_evolution_channel_event(channel=channel, payload=_payload())

    event = EvolutionWebhookEvent.objects.get(whatsapp_channel=channel)
    channel.refresh_from_db()
    assert raised.value.retryable is True
    assert event.status == EvolutionWebhookEvent.Status.FAILED
    assert event.error_code == 'QR_CACHE_UNAVAILABLE'
    assert channel.status == WhatsAppChannel.Status.DISCONNECTED


def test_database_failure_after_cache_set_attempts_cache_cleanup() -> None:
    channel = WhatsAppChannelFactory()
    with (
        patch.object(WhatsAppChannel, 'save', side_effect=RuntimeError('private-detail')),
        patch(
            'omnichannel.evolution_event_processing.delete_evolution_qr_code',
        ) as delete_qr,
        pytest.raises(RuntimeError),
    ):
        process_evolution_channel_event(channel=channel, payload=_payload())

    delete_qr.assert_called_once_with(channel.id)
    assert EvolutionWebhookEvent.objects.get(
        whatsapp_channel=channel,
    ).status == EvolutionWebhookEvent.Status.FAILED


def test_qr_cache_and_logs_are_isolated_by_channel(caplog) -> None:
    first = WhatsAppChannelFactory()
    second = WhatsAppChannelFactory()
    first_qr = 'B' * 128
    second_qr = 'C' * 128
    caplog.set_level(logging.INFO, logger='omnichannel.evolution_event_processing')

    process_evolution_channel_event(channel=first, payload=_payload(first_qr))
    process_evolution_channel_event(channel=second, payload=_payload(second_qr))

    assert get_evolution_qr_code(first.id) == first_qr
    assert get_evolution_qr_code(second.id) == second_qr
    rendered_logs = ' '.join(record.getMessage() + repr(record.__dict__) for record in caplog.records)
    assert first_qr not in rendered_logs
    assert second_qr not in rendered_logs


def test_qr_processing_never_calls_evolution() -> None:
    channel = WhatsAppChannelFactory()
    with patch('requests.sessions.Session.request') as request:
        process_evolution_channel_event(channel=channel, payload=_payload())
    request.assert_not_called()
