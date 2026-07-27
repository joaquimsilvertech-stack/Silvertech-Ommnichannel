"""Contrato real da Evolution v2: inbound @lid nunca deriva identidade de sender.

Fixtures baseadas no payload real capturado em smoke test (apikey/segredos
removidos). O remoteJid real é `@lid` e NÃO traz `remoteJidAlt`; `sender`
representa a linha conectada, não o contato.
"""
from __future__ import annotations

import logging

import pytest

from crm.models import Contact
from omnichannel.evolution_event_processing import process_evolution_channel_event
from omnichannel.factories import WhatsAppChannelFactory
from omnichannel.models import Conversation, EvolutionWebhookEvent, Message

pytestmark = pytest.mark.django_db


def _real_lid_payload(
    *,
    remote_jid: str = '202641053331611@lid',
    sender: object = '556183788392@s.whatsapp.net',
    from_me: object = False,
    remote_jid_alt: object = None,
    external_id: str = 'A581D881B0B052B7F5ED8311EBFD40B3',
) -> dict:
    key: dict = {'remoteJid': remote_jid, 'fromMe': from_me, 'id': external_id}
    if remote_jid_alt is not None:
        key['remoteJidAlt'] = remote_jid_alt
    payload: dict = {
        'event': 'messages.upsert',
        'instance': 'st_0a110ed73b474274b7f6098f52916c82',
        'data': {
            'key': key,
            'pushName': 'Ramilla C.Y.',
            'status': 'DELIVERY_ACK',
            'message': {'conversation': 'O que eu preciso fazer?'},
            'messageType': 'conversation',
            'messageTimestamp': 1785102420,
            'source': 'android',
        },
    }
    if sender is not None:
        payload['sender'] = sender
    return payload


def test_real_lid_inbound_preserves_lid_and_never_uses_sender() -> None:
    channel = WhatsAppChannelFactory(phone_number='556183788392')

    process_evolution_channel_event(channel=channel, payload=_real_lid_payload())

    contact = Contact.objects.get(workspace=channel.workspace)
    conversation = Conversation.objects.get(workspace=channel.workspace)
    message = Message.objects.get(conversation=conversation)
    receipt = EvolutionWebhookEvent.objects.get(whatsapp_channel=channel)

    assert contact.phone == ''
    assert contact.channel_id == '202641053331611@lid'
    assert '556183788392' not in (contact.phone, contact.channel_id)
    assert message.direction == Message.Direction.INBOUND
    assert message.body == 'O que eu preciso fazer?'
    assert receipt.status == EvolutionWebhookEvent.Status.PROCESSED


def test_lid_with_remote_jid_alt_still_prefers_alt_over_sender() -> None:
    channel = WhatsAppChannelFactory()
    payload = _real_lid_payload(remote_jid_alt='5511777777777@s.whatsapp.net')

    process_evolution_channel_event(channel=channel, payload=payload)

    contact = Contact.objects.get(workspace=channel.workspace)
    assert contact.phone == '5511777777777'
    assert contact.channel_id == '202641053331611@lid'
    assert EvolutionWebhookEvent.objects.get(
        whatsapp_channel=channel,
    ).status == EvolutionWebhookEvent.Status.PROCESSED


@pytest.mark.parametrize(
    'sender',
    [None, '', 'not-a-jid', '556183788392@g.us', '556183788392@s.whatsapp.net'],
)
def test_sender_variations_never_change_lid_identity(sender) -> None:
    channel = WhatsAppChannelFactory()
    payload = _real_lid_payload(sender=sender)

    process_evolution_channel_event(channel=channel, payload=payload)

    contact = Contact.objects.get(workspace=channel.workspace)
    receipt = EvolutionWebhookEvent.objects.get(whatsapp_channel=channel)
    assert receipt.status == EvolutionWebhookEvent.Status.PROCESSED
    assert contact.channel_id == '202641053331611@lid'
    assert contact.phone == ''


def test_regular_whatsapp_jid_ignores_sender_and_uses_remote_jid() -> None:
    """Regressão: @s.whatsapp.net normal tira o número do próprio remoteJid."""
    channel = WhatsAppChannelFactory()
    payload = _real_lid_payload(
        remote_jid='5511999999999@s.whatsapp.net',
        sender='5511000000000@s.whatsapp.net',
    )

    process_evolution_channel_event(channel=channel, payload=payload)

    contact = Contact.objects.get(workspace=channel.workspace)
    # O `sender` NÃO deve sobrepor o número do remoteJid direto.
    assert contact.phone == '5511999999999'


def test_group_and_from_me_are_still_discarded_even_with_sender() -> None:
    channel = WhatsAppChannelFactory()

    process_evolution_channel_event(
        channel=channel,
        payload=_real_lid_payload(remote_jid='123456789@g.us'),
    )
    process_evolution_channel_event(
        channel=channel,
        payload=_real_lid_payload(from_me=True, external_id='from-me-1'),
    )

    events = EvolutionWebhookEvent.objects.filter(whatsapp_channel=channel)
    errors = set(events.values_list('error_code', flat=True))
    assert errors == {'UNSUPPORTED_GROUP_MESSAGE', 'MESSAGE_FROM_ME'}
    assert not Contact.objects.filter(workspace=channel.workspace).exists()


def test_two_lids_with_same_sender_do_not_collapse() -> None:
    channel = WhatsAppChannelFactory()

    process_evolution_channel_event(
        channel=channel,
        payload=_real_lid_payload(
            remote_jid='111111111111111@lid',
            external_id='lid-message-1',
        ),
    )
    process_evolution_channel_event(
        channel=channel,
        payload=_real_lid_payload(
            remote_jid='222222222222222@lid',
            external_id='lid-message-2',
        ),
    )

    assert set(
        Contact.objects.filter(workspace=channel.workspace).values_list(
            'channel_id',
            flat=True,
        ),
    ) == {'111111111111111@lid', '222222222222222@lid'}
    assert Conversation.objects.filter(whatsapp_channel=channel).count() == 2
    assert Message.objects.filter(conversation__whatsapp_channel=channel).count() == 2


def test_different_messages_from_same_lid_reuse_contact_and_conversation() -> None:
    channel = WhatsAppChannelFactory()

    process_evolution_channel_event(
        channel=channel,
        payload=_real_lid_payload(external_id='same-lid-message-1'),
    )
    process_evolution_channel_event(
        channel=channel,
        payload=_real_lid_payload(external_id='same-lid-message-2'),
    )

    assert Contact.objects.filter(workspace=channel.workspace).count() == 1
    assert Conversation.objects.filter(whatsapp_channel=channel).count() == 1
    assert Message.objects.filter(conversation__whatsapp_channel=channel).count() == 2


def test_repeated_lid_event_remains_idempotent() -> None:
    channel = WhatsAppChannelFactory()
    payload = _real_lid_payload()

    process_evolution_channel_event(channel=channel, payload=payload)
    process_evolution_channel_event(channel=channel, payload=payload)

    assert Contact.objects.filter(workspace=channel.workspace).count() == 1
    assert Conversation.objects.filter(whatsapp_channel=channel).count() == 1
    assert Message.objects.filter(conversation__whatsapp_channel=channel).count() == 1
    assert EvolutionWebhookEvent.objects.filter(whatsapp_channel=channel).count() == 1


def test_lid_later_receives_verified_phone_without_losing_identity() -> None:
    channel = WhatsAppChannelFactory()
    process_evolution_channel_event(channel=channel, payload=_real_lid_payload())

    process_evolution_channel_event(
        channel=channel,
        payload=_real_lid_payload(
            external_id='lid-with-phone-later',
            remote_jid_alt='5511777777777@s.whatsapp.net',
        ),
    )

    contact = Contact.objects.get(workspace=channel.workspace)
    assert contact.channel_id == '202641053331611@lid'
    assert contact.phone == '5511777777777'


def test_lid_without_phone_does_not_clear_existing_phone() -> None:
    channel = WhatsAppChannelFactory()
    contact = Contact.objects.create(
        workspace=channel.workspace,
        name='Nome curado',
        phone='5511777777777',
        channel_id='202641053331611@lid',
    )

    process_evolution_channel_event(channel=channel, payload=_real_lid_payload())

    contact.refresh_from_db()
    assert contact.phone == '5511777777777'


def test_lid_conflicting_phone_is_preserved_and_logged_safely(caplog) -> None:
    channel = WhatsAppChannelFactory()
    contact = Contact.objects.create(
        workspace=channel.workspace,
        name='Nome curado',
        phone='5511777777777',
        channel_id='202641053331611@lid',
    )
    caplog.set_level(logging.WARNING, logger='omnichannel.inbound_routing')

    process_evolution_channel_event(
        channel=channel,
        payload=_real_lid_payload(
            remote_jid_alt='5511888888888@s.whatsapp.net',
        ),
    )

    contact.refresh_from_db()
    assert contact.phone == '5511777777777'
    record = next(
        item
        for item in caplog.records
        if getattr(item, 'error_code', '') == 'INBOUND_PHONE_CONFLICT'
    )
    rendered = f'{record.getMessage()} {record.__dict__}'
    assert '5511777777777' not in rendered
    assert '5511888888888' not in rendered


def test_lid_alternate_equal_to_channel_phone_is_not_trusted() -> None:
    channel = WhatsAppChannelFactory(phone_number='556183788392')

    process_evolution_channel_event(
        channel=channel,
        payload=_real_lid_payload(
            remote_jid_alt='556183788392@s.whatsapp.net',
        ),
    )

    contact = Contact.objects.get(workspace=channel.workspace)
    assert contact.channel_id == '202641053331611@lid'
    assert contact.phone == ''
