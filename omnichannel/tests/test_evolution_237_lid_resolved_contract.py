"""Fixtures de contrato da Evolution API 2.3.7 — "LID resolvido na origem".

Capturado em smoke real 29/07/2026 (número/segredos redigidos; usa números
fictícios de teste). A partir da 2.3.7 a Evolution resolve o LID no recebimento:
o `messages.upsert` de um contato que antes chegava `@lid` agora chega com
`key.remoteJid = <numero>@s.whatsapp.net`, acompanhado de
`key.remoteJidAlt = <mesmo numero>@s.whatsapp.net` E `key.addressingMode = "lid"`
(marcador informativo). O `messages.update` pareado casa por `keyId`
(== `key.id` do upsert) e seu `data.remoteJid` pode vir `@lid` mesmo assim.

Esta suíte é só de contrato: não corrige bug — o parser já resolve tudo isso.
Ela blinda o pipeline contra regressão silenciosa e garante que `addressingMode`
permaneça informativo (nunca ramifique a resolução de identidade).
"""
from __future__ import annotations

import pytest

from crm.models import Contact
from omnichannel.evolution_event_processing import process_evolution_channel_event
from omnichannel.factories import (
    ConversationFactory,
    MessageFactory,
    WhatsAppChannelFactory,
)
from omnichannel.models import Conversation, EvolutionWebhookEvent, Message

pytestmark = pytest.mark.django_db

_CONTACT_PHONE = '5511999999999'
_LINE_SENDER = '5511000000000@s.whatsapp.net'
_KEY_ID = 'AC9F040D67873783156B9E13BF484CC7'
_MESSAGE_ID = 'cms6itncs00vble5ph7v7trzk'


def _resolved_lid_upsert(
    *,
    with_addressing_mode: bool = True,
    sender: object = _LINE_SENDER,
    external_id: str = _KEY_ID,
) -> dict:
    """Inbound real 2.3.7: número direto + remoteJidAlt + addressingMode:'lid'."""
    key: dict = {
        'remoteJid': f'{_CONTACT_PHONE}@s.whatsapp.net',
        'remoteJidAlt': f'{_CONTACT_PHONE}@s.whatsapp.net',
        'fromMe': False,
        'id': external_id,
        'participant': '',
    }
    if with_addressing_mode:
        key['addressingMode'] = 'lid'
    payload: dict = {
        'event': 'messages.upsert',
        'instance': 'st_test_instance',
        'data': {
            'key': key,
            'pushName': 'Contato Real 237',
            'status': 'DELIVERY_ACK',
            'message': {'conversation': 'mensagem real 2.3.7'},
            'messageType': 'conversation',
            'messageTimestamp': 1785355929,
            'source': 'android',
        },
    }
    if sender is not None:
        payload['sender'] = sender
    return payload


def _real_237_update(**overrides) -> dict:
    """Status real 2.3.7: casa por keyId; data.remoteJid pode vir @lid."""
    data = {
        'keyId': _KEY_ID,
        'remoteJid': '199999999999999@lid',
        'fromMe': False,
        'status': 'READ',
        'messageId': _MESSAGE_ID,
    }
    data.update(overrides)
    return {
        'event': 'messages.update',
        'instance': 'st_test_instance',
        'data': data,
        'sender': _LINE_SENDER,
    }


# --- A) Inbound messages.upsert — LID resolvido na origem -------------------


def test_237_resolved_lid_creates_contact_with_real_phone() -> None:
    channel = WhatsAppChannelFactory()

    process_evolution_channel_event(channel=channel, payload=_resolved_lid_upsert())

    contact = Contact.objects.get(workspace=channel.workspace)
    conversation = Conversation.objects.get(workspace=channel.workspace)
    message = Message.objects.get(conversation=conversation)
    receipt = EvolutionWebhookEvent.objects.get(whatsapp_channel=channel)

    # Identidade pelo número direto do remoteJid, nunca por um @lid.
    assert contact.phone == _CONTACT_PHONE
    assert contact.channel_id == _CONTACT_PHONE
    assert '@lid' not in contact.channel_id
    assert message.direction == Message.Direction.INBOUND
    assert message.body == 'mensagem real 2.3.7'
    assert receipt.status == EvolutionWebhookEvent.Status.PROCESSED


def test_237_addressing_mode_lid_does_not_change_direct_jid_resolution() -> None:
    """O mesmo payload com e sem `addressingMode` produz o mesmo contato."""
    with_mode = WhatsAppChannelFactory()
    without_mode = WhatsAppChannelFactory()

    process_evolution_channel_event(
        channel=with_mode,
        payload=_resolved_lid_upsert(with_addressing_mode=True),
    )
    process_evolution_channel_event(
        channel=without_mode,
        payload=_resolved_lid_upsert(with_addressing_mode=False),
    )

    contact_with = Contact.objects.get(workspace=with_mode.workspace)
    contact_without = Contact.objects.get(workspace=without_mode.workspace)
    assert contact_with.phone == contact_without.phone == _CONTACT_PHONE
    assert contact_with.channel_id == contact_without.channel_id == _CONTACT_PHONE


@pytest.mark.parametrize('sender', [None, '', _LINE_SENDER, '5511222223333@s.whatsapp.net'])
def test_237_sender_line_never_becomes_identity(sender) -> None:
    channel = WhatsAppChannelFactory()

    process_evolution_channel_event(
        channel=channel,
        payload=_resolved_lid_upsert(sender=sender),
    )

    contact = Contact.objects.get(workspace=channel.workspace)
    # A identidade vem sempre do remoteJid, nunca da linha conectada (`sender`).
    assert contact.phone == _CONTACT_PHONE
    assert contact.channel_id == _CONTACT_PHONE


# --- B) Status messages.update real 2.3.7 pareado --------------------------


def _outbound(*, channel=None, external_id: str, status: str = Message.Status.DELIVERED):
    channel = channel or WhatsAppChannelFactory()
    conversation = ConversationFactory(workspace=channel.workspace, whatsapp_channel=channel)
    message = MessageFactory(
        conversation=conversation,
        direction=Message.Direction.OUTBOUND,
        status=status,
        external_id=external_id,
        body='Outbound body must stay unchanged',
    )
    return channel, message


def test_237_update_matches_outbound_by_keyid_despite_lid_remotejid() -> None:
    channel, message = _outbound(external_id=_KEY_ID, status=Message.Status.DELIVERED)

    process_evolution_channel_event(channel=channel, payload=_real_237_update())

    message.refresh_from_db()
    receipt = EvolutionWebhookEvent.objects.get(whatsapp_channel=channel)
    # Casamento por keyId, mesmo com data.remoteJid == @lid.
    assert message.status == Message.Status.READ
    assert receipt.status == EvolutionWebhookEvent.Status.PROCESSED


def test_237_update_keyid_equals_upsert_key_id_end_to_end() -> None:
    """Invariante de ligação: o keyId do update == key.id do upsert.

    Respeita o design existente (status só atualiza OUTBOUND — cf.
    test_evolution_message_status_processing.py::test_inbound_message_is_never_updated):
    usa uma mensagem OUTBOUND cujo external_id é o key.id do upsert e prova que o
    update pareado a encontra pela mesma chave.
    """
    upsert = _resolved_lid_upsert()
    update = _real_237_update()
    # A chave que amarra os dois eventos é a mesma string.
    assert upsert['data']['key']['id'] == update['data']['keyId'] == _KEY_ID

    channel, message = _outbound(external_id=_KEY_ID, status=Message.Status.SENT)
    process_evolution_channel_event(channel=channel, payload=update)

    message.refresh_from_db()
    assert message.status == Message.Status.READ
    assert EvolutionWebhookEvent.objects.get(
        whatsapp_channel=channel,
    ).status == EvolutionWebhookEvent.Status.PROCESSED
