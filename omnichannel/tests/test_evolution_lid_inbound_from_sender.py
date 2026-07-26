"""Contrato real da Evolution v2: inbound @lid deriva o telefone do `sender`.

Fixtures baseadas no payload real capturado em smoke test (apikey/segredos
removidos). O remoteJid real é `@lid` ofuscado e NÃO traz `remoteJidAlt`; o
número do contato chega em `sender` (raiz do payload). Estes testes falhariam
antes da correção (evento terminava IGNORED com INVALID_REMOTE_JID).
"""
from __future__ import annotations

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


def test_real_lid_inbound_uses_sender_as_contact_number() -> None:
    channel = WhatsAppChannelFactory()

    process_evolution_channel_event(channel=channel, payload=_real_lid_payload())

    contact = Contact.objects.get(workspace=channel.workspace)
    conversation = Conversation.objects.get(workspace=channel.workspace)
    message = Message.objects.get(conversation=conversation)
    receipt = EvolutionWebhookEvent.objects.get(whatsapp_channel=channel)

    # O número vem de `sender`, nunca do @lid ofuscado.
    assert contact.phone == '556183788392'
    assert contact.channel_id == '556183788392'
    assert '202641053331611' not in (contact.phone, contact.channel_id)
    assert message.direction == Message.Direction.INBOUND
    assert message.body == 'O que eu preciso fazer?'
    assert receipt.status == EvolutionWebhookEvent.Status.PROCESSED


def test_lid_with_remote_jid_alt_still_prefers_alt_over_sender() -> None:
    """Compat: quando remoteJidAlt existe, ele tem prioridade sobre o `sender`."""
    channel = WhatsAppChannelFactory()
    payload = _real_lid_payload(remote_jid_alt='5511777777777@s.whatsapp.net')

    process_evolution_channel_event(channel=channel, payload=payload)

    contact = Contact.objects.get(workspace=channel.workspace)
    assert contact.phone == '5511777777777'
    assert EvolutionWebhookEvent.objects.get(
        whatsapp_channel=channel,
    ).status == EvolutionWebhookEvent.Status.PROCESSED


@pytest.mark.parametrize('sender', [None, '', 'not-a-jid', '556183788392@g.us'])
def test_lid_without_alt_and_without_valid_sender_is_ignored(sender) -> None:
    channel = WhatsAppChannelFactory()
    payload = _real_lid_payload(sender=sender)

    process_evolution_channel_event(channel=channel, payload=payload)

    receipt = EvolutionWebhookEvent.objects.get(whatsapp_channel=channel)
    assert receipt.status == EvolutionWebhookEvent.Status.IGNORED
    assert receipt.error_code == 'INVALID_REMOTE_JID'
    assert not Contact.objects.filter(workspace=channel.workspace).exists()


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
