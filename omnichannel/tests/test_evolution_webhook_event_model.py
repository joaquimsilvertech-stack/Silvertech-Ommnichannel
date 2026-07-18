from __future__ import annotations

import hashlib

import pytest
from django.db import IntegrityError, transaction

from core.models import BaseModel
from omnichannel.evolution_event_processing import build_provider_message_key
from omnichannel.factories import (
    ConversationFactory,
    EvolutionWebhookEventFactory,
    MessageFactory,
    WhatsAppChannelFactory,
)
from omnichannel.models import EvolutionWebhookEvent, Message

pytestmark = pytest.mark.django_db


def test_event_receipt_inherits_base_model_and_has_safe_defaults() -> None:
    event = EvolutionWebhookEventFactory()

    assert isinstance(event, BaseModel)
    assert event.status == EvolutionWebhookEvent.Status.PROCESSING
    assert event.attempt_count == 1
    assert event.error_code == ''
    assert event.started_at is not None
    assert event.whatsapp_channel.workspace_id == event.whatsapp_channel.workspace.id


def test_event_receipt_schema_has_limits_indexes_and_constraints() -> None:
    meta = EvolutionWebhookEvent._meta
    index_names = {index.name for index in meta.indexes}
    constraint_names = {constraint.name for constraint in meta.constraints}

    assert meta.get_field('event_type').max_length == 64
    assert meta.get_field('deduplication_key').max_length == 64
    assert meta.get_field('external_id').max_length == 255
    assert meta.get_field('error_code').max_length == 64
    assert {
        'omni_evo_channel_event_idx',
        'omni_evo_channel_status_idx',
        'omni_evo_external_id_idx',
        'omni_evo_created_at_idx',
    } <= index_names
    assert 'omni_evo_event_unique_channel_key' in constraint_names


@pytest.mark.parametrize(
    'forbidden_name',
    [
        'payload',
        'raw_payload',
        'body',
        'headers',
        'qrcode',
        'qr',
        'secret',
        'phone_number',
        'webhook_secret',
        'api_key',
    ],
)
def test_event_receipt_does_not_persist_sensitive_content(forbidden_name: str) -> None:
    assert forbidden_name not in {field.name for field in EvolutionWebhookEvent._meta.fields}


def test_event_receipt_unique_key_is_scoped_by_channel() -> None:
    first = EvolutionWebhookEventFactory()
    with pytest.raises(IntegrityError), transaction.atomic():
        EvolutionWebhookEventFactory(
            whatsapp_channel=first.whatsapp_channel,
            deduplication_key=first.deduplication_key,
        )

    other_channel = WhatsAppChannelFactory()
    second = EvolutionWebhookEventFactory(
        whatsapp_channel=other_channel,
        deduplication_key=first.deduplication_key,
    )
    assert second.pk is not None


def test_event_receipt_str_does_not_expose_external_or_deduplication_values() -> None:
    event = EvolutionWebhookEventFactory(
        external_id='private-external-id',
        deduplication_key='a' * 64,
    )

    rendered = str(event)
    assert 'private-external-id' not in rendered
    assert 'a' * 64 not in rendered


def test_provider_message_key_allows_legacy_null_and_saves_hash() -> None:
    legacy = MessageFactory(provider_message_key=None)
    channel = WhatsAppChannelFactory()
    key = build_provider_message_key(channel.id, 'private-external-id')
    message = MessageFactory(
        conversation=ConversationFactory(
            workspace=channel.workspace,
            whatsapp_channel=channel,
        ),
        provider_message_key=key,
    )

    assert legacy.provider_message_key is None
    assert message.provider_message_key == key
    assert len(key) == 64
    assert key == hashlib.sha256(
        f'evolution:{channel.id}:private-external-id'.encode(),
    ).hexdigest()
    assert 'private-external-id' not in key


def test_provider_message_key_is_globally_unique_when_not_null() -> None:
    key = 'b' * 64
    MessageFactory(provider_message_key=key)

    with pytest.raises(IntegrityError), transaction.atomic():
        MessageFactory(provider_message_key=key)


def test_same_external_id_in_different_channels_builds_different_provider_keys() -> None:
    first_channel = WhatsAppChannelFactory()
    second_channel = WhatsAppChannelFactory()

    assert build_provider_message_key(
        first_channel.id,
        'same-external-id',
    ) != build_provider_message_key(second_channel.id, 'same-external-id')


def test_message_model_has_named_partial_provider_key_constraint() -> None:
    constraint = next(
        constraint
        for constraint in Message._meta.constraints
        if constraint.name == 'omni_message_unique_provider_key'
    )
    assert constraint.condition is not None
