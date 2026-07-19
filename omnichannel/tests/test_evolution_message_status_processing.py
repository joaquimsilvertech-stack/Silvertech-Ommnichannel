from __future__ import annotations

import logging
from unittest.mock import patch

import pytest

from omnichannel.evolution_event_processing import (
    build_provider_message_key,
    normalize_evolution_message_status,
    process_evolution_channel_event,
)
from omnichannel.factories import ConversationFactory, MessageFactory, WhatsAppChannelFactory
from omnichannel.models import EvolutionWebhookEvent, Message, WhatsAppChannel
from omnichannel.tasks import send_outbound_whatsapp_message

pytestmark = pytest.mark.django_db


def _outbound(
    *,
    channel=None,
    external_id: str = 'outbound-message-1',
    status: str = Message.Status.PENDING,
    provider_message_key=None,
):
    channel = channel or WhatsAppChannelFactory()
    conversation = ConversationFactory(
        workspace=channel.workspace,
        whatsapp_channel=channel,
    )
    message = MessageFactory(
        conversation=conversation,
        direction=Message.Direction.OUTBOUND,
        status=status,
        external_id=external_id,
        provider_message_key=provider_message_key,
        body='Outbound body must stay unchanged',
    )
    return channel, message


def _payload(
    external_id: object = 'outbound-message-1',
    provider_status: object = 'SENT',
    *,
    event: str = 'messages.update',
) -> dict:
    return {
        'event': event,
        'data': {'key': {'id': external_id}, 'status': provider_status},
    }


@pytest.mark.parametrize(
    ('current', 'provider_status', 'expected'),
    [
        (Message.Status.PENDING, 'SENT', Message.Status.SENT),
        (Message.Status.SENT, 'DELIVERED', Message.Status.DELIVERED),
        (Message.Status.DELIVERED, 'READ', Message.Status.READ),
        (Message.Status.PENDING, 'DELIVERY_ACK', Message.Status.DELIVERED),
        (Message.Status.PENDING, 'READ_ACK', Message.Status.READ),
        (Message.Status.PENDING, 'FAILED', Message.Status.FAILED),
        (Message.Status.SENT, 'ERROR', Message.Status.FAILED),
        (Message.Status.FAILED, 'SENT', Message.Status.SENT),
        (Message.Status.FAILED, 'DELIVERED', Message.Status.DELIVERED),
        (Message.Status.FAILED, 'PLAYED', Message.Status.READ),
    ],
)
def test_supported_monotonic_transitions(current: str, provider_status: str, expected: str) -> None:
    channel, message = _outbound(status=current)
    process_evolution_channel_event(
        channel=channel,
        payload=_payload(provider_status=provider_status),
    )

    message.refresh_from_db()
    receipt = EvolutionWebhookEvent.objects.get(whatsapp_channel=channel)
    assert message.status == expected
    assert receipt.status == EvolutionWebhookEvent.Status.PROCESSED


@pytest.mark.parametrize(
    ('current', 'provider_status'),
    [
        (Message.Status.DELIVERED, 'SENT'),
        (Message.Status.READ, 'DELIVERED'),
        (Message.Status.READ, 'FAILED'),
        (Message.Status.DELIVERED, 'ERROR'),
        (Message.Status.SENT, 'PENDING'),
    ],
)
def test_regressive_or_late_failure_status_is_ignored(current: str, provider_status: str) -> None:
    channel, message = _outbound(status=current)
    process_evolution_channel_event(
        channel=channel,
        payload=_payload(provider_status=provider_status),
    )
    message.refresh_from_db()
    receipt = EvolutionWebhookEvent.objects.get(whatsapp_channel=channel)
    assert message.status == current
    assert receipt.status == EvolutionWebhookEvent.Status.IGNORED
    assert receipt.error_code == 'STATUS_REGRESSION'


def test_success_clears_send_error_and_failure_saves_generic_code() -> None:
    channel, failed = _outbound(
        status=Message.Status.FAILED,
        external_id='recover-message',
    )
    failed.send_error_code = 'OLD_PRIVATE_CODE'
    failed.save(update_fields=['send_error_code', 'updated_at'])
    process_evolution_channel_event(
        channel=channel,
        payload=_payload('recover-message', 'SENT'),
    )
    failed.refresh_from_db()
    assert failed.send_error_code == ''

    other_channel, pending = _outbound(external_id='failure-message')
    process_evolution_channel_event(
        channel=other_channel,
        payload=_payload('failure-message', 'FAILED'),
    )
    pending.refresh_from_db()
    assert pending.send_error_code == 'EVOLUTION_DELIVERY_FAILED'


def test_status_update_preserves_body_and_does_not_create_message() -> None:
    channel, message = _outbound()
    original_body = message.body
    before_count = Message.objects.count()

    process_evolution_channel_event(channel=channel, payload=_payload())

    message.refresh_from_db()
    assert message.body == original_body
    assert Message.objects.count() == before_count


def test_repeated_status_is_idempotent() -> None:
    channel, message = _outbound()
    payload = _payload()
    process_evolution_channel_event(channel=channel, payload=payload)
    process_evolution_channel_event(channel=channel, payload=payload)

    message.refresh_from_db()
    assert message.status == Message.Status.SENT
    assert EvolutionWebhookEvent.objects.filter(whatsapp_channel=channel).count() == 1


@pytest.mark.parametrize(
    ('external_id', 'provider_status', 'expected_error'),
    [
        (None, 'SENT', 'INVALID_EXTERNAL_ID'),
        ('', 'SENT', 'INVALID_EXTERNAL_ID'),
        ('outbound-message-1', 'UNKNOWN_STATUS', 'UNSUPPORTED_MESSAGE_STATUS'),
        ('outbound-message-1', 3, 'UNSUPPORTED_MESSAGE_STATUS'),
    ],
)
def test_invalid_external_id_or_status_is_ignored(
    external_id,
    provider_status,
    expected_error: str,
) -> None:
    channel, message = _outbound()
    process_evolution_channel_event(
        channel=channel,
        payload=_payload(external_id, provider_status),
    )
    message.refresh_from_db()
    receipt = EvolutionWebhookEvent.objects.get(whatsapp_channel=channel)
    assert message.status == Message.Status.PENDING
    assert receipt.status == EvolutionWebhookEvent.Status.IGNORED
    assert receipt.error_code == expected_error


def test_inbound_message_is_never_updated() -> None:
    channel = WhatsAppChannelFactory()
    conversation = ConversationFactory(workspace=channel.workspace, whatsapp_channel=channel)
    inbound = MessageFactory(
        conversation=conversation,
        direction=Message.Direction.INBOUND,
        external_id='outbound-message-1',
        status=Message.Status.DELIVERED,
    )
    process_evolution_channel_event(channel=channel, payload=_payload())
    inbound.refresh_from_db()
    assert inbound.status == Message.Status.DELIVERED
    assert EvolutionWebhookEvent.objects.get(
        whatsapp_channel=channel,
    ).error_code == 'OUTBOUND_MESSAGE_NOT_FOUND'


def test_message_from_other_channel_or_workspace_is_never_updated() -> None:
    owner_channel, message = _outbound()
    incoming_channel = WhatsAppChannelFactory()
    process_evolution_channel_event(channel=incoming_channel, payload=_payload())

    message.refresh_from_db()
    assert message.status == Message.Status.PENDING
    assert owner_channel.workspace_id != incoming_channel.workspace_id


def test_provider_key_is_preferred_and_can_be_filled_transitionally() -> None:
    channel, legacy = _outbound(external_id='legacy-external-id')
    assert legacy.provider_message_key is None
    process_evolution_channel_event(
        channel=channel,
        payload=_payload('legacy-external-id', 'DELIVERED'),
    )
    legacy.refresh_from_db()
    expected_key = build_provider_message_key(channel.id, 'legacy-external-id')
    assert legacy.provider_message_key == expected_key
    assert legacy.status == Message.Status.DELIVERED

    keyed_channel, keyed = _outbound(
        external_id='different-stale-id',
        provider_message_key=build_provider_message_key(channel.id, 'unused'),
    )
    expected = build_provider_message_key(keyed_channel.id, 'key-only-id')
    keyed.provider_message_key = expected
    keyed.save(update_fields=['provider_message_key', 'updated_at'])
    process_evolution_channel_event(
        channel=keyed_channel,
        payload=_payload('key-only-id', 'SENT'),
    )
    keyed.refresh_from_db()
    assert keyed.status == Message.Status.SENT


def test_provider_key_conflict_does_not_update_wrong_message() -> None:
    target_channel, target = _outbound(external_id='conflicting-id')
    other_channel, other = _outbound(
        external_id='other-id',
        provider_message_key=build_provider_message_key(target_channel.id, 'conflicting-id'),
    )

    process_evolution_channel_event(
        channel=target_channel,
        payload=_payload('conflicting-id', 'SENT'),
    )

    target.refresh_from_db()
    other.refresh_from_db()
    receipt = EvolutionWebhookEvent.objects.get(whatsapp_channel=target_channel)
    assert target.status == Message.Status.PENDING
    assert other.status == Message.Status.PENDING
    assert receipt.error_code == 'PROVIDER_KEY_CONFLICT'
    assert other_channel.id != target_channel.id


@pytest.mark.parametrize(
    'event_name',
    ['messages.update', 'SEND_MESSAGE', 'send.message.update'],
)
def test_supported_delivery_event_names_are_processed(event_name: str) -> None:
    channel, message = _outbound()
    process_evolution_channel_event(
        channel=channel,
        payload=_payload(event=event_name),
    )
    message.refresh_from_db()
    assert message.status == Message.Status.SENT


def test_status_data_list_processes_items_independently() -> None:
    channel, first = _outbound(external_id='list-status-1')
    _, second = _outbound(channel=channel, external_id='list-status-2')
    payload = {
        'event': 'messages.update',
        'data': [
            {'key': {'id': 'list-status-1'}, 'status': 'DELIVERED'},
            {'key': {}, 'status': 'READ'},
            {'key': {'id': 'list-status-2'}, 'status': 'READ'},
        ],
    }
    process_evolution_channel_event(channel=channel, payload=payload)
    first.refresh_from_db()
    second.refresh_from_db()
    assert first.status == Message.Status.DELIVERED
    assert second.status == Message.Status.READ
    assert EvolutionWebhookEvent.objects.filter(whatsapp_channel=channel).count() == 3


@pytest.mark.parametrize(
    ('value', 'expected'),
    [
        ('pending', Message.Status.PENDING),
        ('server.ack', Message.Status.SENT),
        ('delivery_ack', Message.Status.DELIVERED),
        ('played', Message.Status.READ),
        ('error', Message.Status.FAILED),
        (3, None),
        ('unknown', None),
    ],
)
def test_message_status_normalization_is_explicit(value, expected) -> None:
    assert normalize_evolution_message_status(value) == expected


def test_status_logs_exclude_external_id_phone_and_body(caplog) -> None:
    external_id = 'private-outbound-external-id'
    channel, message = _outbound(external_id=external_id)
    message.conversation.contact.phone = '5511555555555'
    message.conversation.contact.save(update_fields=['phone', 'updated_at'])
    caplog.set_level(logging.INFO, logger='omnichannel.evolution_event_processing')

    process_evolution_channel_event(
        channel=channel,
        payload=_payload(external_id, 'SENT'),
    )

    rendered = ' '.join(record.getMessage() + repr(record.__dict__) for record in caplog.records)
    assert external_id not in rendered
    assert '5511555555555' not in rendered
    assert message.body not in rendered


def test_status_processing_never_calls_ai_evolution_or_http() -> None:
    channel, _message = _outbound()
    with (
        patch('omnichannel.tasks.process_ai_response.delay') as ai_task,
        patch('omnichannel.services.send_whatsapp_message') as evolution_send,
        patch('requests.sessions.Session.request') as request,
    ):
        process_evolution_channel_event(channel=channel, payload=_payload())
    ai_task.assert_not_called()
    evolution_send.assert_not_called()
    request.assert_not_called()


def test_sent_message_status_remains_scoped_to_the_sending_channel() -> None:
    channel_a = WhatsAppChannelFactory(
        status=WhatsAppChannel.Status.CONNECTED,
        instance_name='status-channel-a',
    )
    channel_b = WhatsAppChannelFactory(
        workspace=channel_a.workspace,
        status=WhatsAppChannel.Status.CONNECTED,
        instance_name='status-channel-b',
    )
    conversation = ConversationFactory(
        workspace=channel_a.workspace,
        whatsapp_channel=channel_a,
        contact__phone='5511999999999',
    )
    message = MessageFactory(
        conversation=conversation,
        direction=Message.Direction.OUTBOUND,
        status=Message.Status.PENDING,
        external_id=None,
    )

    with patch(
        'omnichannel.services.send_whatsapp_message',
        return_value={'key': {'id': 'shared-external-id'}},
    ) as evolution_send:
        send_outbound_whatsapp_message.run(str(message.id), str(channel_a.id))

    message.refresh_from_db()
    assert message.status == Message.Status.SENT
    assert message.external_id == 'shared-external-id'
    assert evolution_send.call_args.kwargs['channel'].id == channel_a.id

    process_evolution_channel_event(
        channel=channel_a,
        payload=_payload('shared-external-id', 'DELIVERED'),
    )
    message.refresh_from_db()
    assert message.status == Message.Status.DELIVERED

    process_evolution_channel_event(
        channel=channel_b,
        payload=_payload('shared-external-id', 'READ'),
    )
    message.refresh_from_db()
    assert message.status == Message.Status.DELIVERED
