from __future__ import annotations

from datetime import timedelta

import pytest
from django.utils import timezone

from omnichannel.evolution_event_processing import (
    build_event_deduplication_key,
    claim_evolution_event,
    mark_evolution_event_failed,
    mark_evolution_event_ignored,
    mark_evolution_event_processed,
)
from omnichannel.factories import WhatsAppChannelFactory
from omnichannel.models import EvolutionWebhookEvent

pytestmark = pytest.mark.django_db


def _claim(channel, key: str = 'a' * 64):
    return claim_evolution_event(
        channel=channel,
        event_type='MESSAGES_UPSERT',
        deduplication_key=key,
        external_id='external-id',
    )


def test_first_claim_creates_processing_receipt() -> None:
    channel = WhatsAppChannelFactory()
    claim = _claim(channel)

    assert claim.should_process is True
    assert claim.duplicate is False
    assert claim.event.status == EvolutionWebhookEvent.Status.PROCESSING
    assert claim.event.attempt_count == 1


def test_recent_processing_claim_is_not_reentered() -> None:
    channel = WhatsAppChannelFactory()
    first = _claim(channel)
    second = _claim(channel)

    assert second.should_process is False
    assert second.duplicate is True
    assert second.event.id == first.event.id
    assert EvolutionWebhookEvent.objects.count() == 1


@pytest.mark.parametrize('terminal_status', ['processed', 'ignored'])
def test_terminal_receipt_prevents_reprocessing(terminal_status: str) -> None:
    channel = WhatsAppChannelFactory()
    first = _claim(channel)
    if terminal_status == 'processed':
        mark_evolution_event_processed(first.event)
    else:
        mark_evolution_event_ignored(first.event, error_code='IGNORED_ITEM')

    second = _claim(channel)
    assert second.should_process is False
    assert second.event.id == first.event.id


def test_failed_receipt_is_reclaimed_and_cleared() -> None:
    channel = WhatsAppChannelFactory()
    first = _claim(channel)
    mark_evolution_event_failed(first.event, error_code='TEMPORARY_FAILURE')

    second = _claim(channel)
    second.event.refresh_from_db()
    assert second.should_process is True
    assert second.event.status == EvolutionWebhookEvent.Status.PROCESSING
    assert second.event.attempt_count == 2
    assert second.event.error_code == ''
    assert second.event.finished_at is None


def test_stale_processing_receipt_is_reclaimed(settings) -> None:
    settings.EVOLUTION_EVENT_PROCESSING_STALE_SECONDS = 30
    channel = WhatsAppChannelFactory()
    first = _claim(channel)
    EvolutionWebhookEvent.objects.filter(id=first.event.id).update(
        started_at=timezone.now() - timedelta(seconds=31),
    )

    second = _claim(channel)
    assert second.should_process is True
    assert second.event.attempt_count == 2


def test_deduplication_keys_are_hashes_without_sensitive_material() -> None:
    secret_values = ('private-qr-value', '5511999999999', 'private-message')
    key = build_event_deduplication_key('QRCODE_UPDATED', *secret_values)

    assert len(key) == 64
    assert all(character in '0123456789abcdef' for character in key)
    for value in secret_values:
        assert value not in key


def test_same_key_deduplicates_per_channel_but_not_between_channels() -> None:
    first_channel = WhatsAppChannelFactory()
    second_channel = WhatsAppChannelFactory()
    key = build_event_deduplication_key('MESSAGES_UPSERT', 'same-id')

    first = _claim(first_channel, key)
    duplicate = _claim(first_channel, key)
    other = _claim(second_channel, key)

    assert duplicate.should_process is False
    assert other.should_process is True
    assert first.event.id != other.event.id


def test_status_specific_keys_and_list_item_keys_are_independent() -> None:
    delivered = build_event_deduplication_key('MESSAGE_STATUS', 'id', 'delivered')
    read = build_event_deduplication_key('MESSAGE_STATUS', 'id', 'read')
    first_item = build_event_deduplication_key('MESSAGES_UPSERT', 'first')
    second_item = build_event_deduplication_key('MESSAGES_UPSERT', 'second')

    assert delivered != read
    assert first_item != second_item
