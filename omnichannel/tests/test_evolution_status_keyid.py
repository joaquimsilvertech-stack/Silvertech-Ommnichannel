"""Contrato real da Evolution v2: messages.update traz o id em `data.keyId`.

O `keyId` do update é igual ao `key.id` do upsert — é a chave que liga o status
à mensagem. Antes da correção, nenhum path cobria `keyId`/`messageId`, então o
evento terminava IGNORED com INVALID_EXTERNAL_ID.

Observação de contrato (por design, coberto por
`test_evolution_message_status_processing.py::test_inbound_message_is_never_updated`):
o status só atualiza mensagens OUTBOUND. Por isso o teste do keyId usa uma
mensagem outbound cujo external_id == keyId, respeitando a mesma regra.
"""
from __future__ import annotations

import pytest

from omnichannel.evolution_event_processing import process_evolution_channel_event
from omnichannel.factories import ConversationFactory, MessageFactory, WhatsAppChannelFactory
from omnichannel.models import EvolutionWebhookEvent, Message

pytestmark = pytest.mark.django_db

_KEY_ID = 'A581D881B0B052B7F5ED8311EBFD40B3'
_MESSAGE_ID = 'cms2bw34606s2ks5wwh1fb4tt'


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


def _real_update_payload(data: dict) -> dict:
    return {
        'event': 'messages.update',
        'instance': 'st_0a110ed73b474274b7f6098f52916c82',
        'data': data,
        'sender': '556183788392@s.whatsapp.net',
    }


def _real_status_data(**overrides) -> dict:
    data = {
        'messageId': _MESSAGE_ID,
        'keyId': _KEY_ID,
        'remoteJid': '202641053331611@lid',
        'fromMe': False,
        'participant': '202641053331611@lid',
        'status': 'READ',
    }
    data.update(overrides)
    return data


def test_real_update_keyid_matches_message_and_marks_read() -> None:
    channel, message = _outbound(external_id=_KEY_ID, status=Message.Status.DELIVERED)

    process_evolution_channel_event(
        channel=channel,
        payload=_real_update_payload(_real_status_data()),
    )

    message.refresh_from_db()
    receipt = EvolutionWebhookEvent.objects.get(whatsapp_channel=channel)
    assert message.status == Message.Status.READ
    assert receipt.status == EvolutionWebhookEvent.Status.PROCESSED


def test_update_via_message_id_only_is_recognized() -> None:
    """messageId isolado (sem keyId nem key.id) também é reconhecido como id."""
    channel, message = _outbound(external_id=_MESSAGE_ID, status=Message.Status.SENT)
    data = {'messageId': _MESSAGE_ID, 'status': 'DELIVERED'}

    process_evolution_channel_event(channel=channel, payload=_real_update_payload(data))

    message.refresh_from_db()
    assert message.status == Message.Status.DELIVERED
    assert EvolutionWebhookEvent.objects.get(
        whatsapp_channel=channel,
    ).status == EvolutionWebhookEvent.Status.PROCESSED


def test_legacy_key_id_format_still_works() -> None:
    """Regressão: formato antigo com key.id continua funcionando."""
    channel, message = _outbound(external_id='legacy-id', status=Message.Status.PENDING)
    data = {'key': {'id': 'legacy-id'}, 'status': 'SENT'}

    process_evolution_channel_event(channel=channel, payload=_real_update_payload(data))

    message.refresh_from_db()
    assert message.status == Message.Status.SENT


def test_real_keyid_is_extracted_even_without_matching_outbound() -> None:
    """Prova que o id É extraído (Fix 2): sem outbound correspondente o erro é
    OUTBOUND_MESSAGE_NOT_FOUND, e não mais INVALID_EXTERNAL_ID."""
    channel = WhatsAppChannelFactory()

    process_evolution_channel_event(
        channel=channel,
        payload=_real_update_payload(_real_status_data()),
    )

    receipt = EvolutionWebhookEvent.objects.get(whatsapp_channel=channel)
    assert receipt.status == EvolutionWebhookEvent.Status.IGNORED
    assert receipt.error_code == 'OUTBOUND_MESSAGE_NOT_FOUND'


def test_update_without_any_recognizable_id_stays_invalid_external_id() -> None:
    channel, _message = _outbound(external_id=_KEY_ID)
    data = {'remoteJid': '202641053331611@lid', 'status': 'READ'}

    process_evolution_channel_event(channel=channel, payload=_real_update_payload(data))

    receipt = EvolutionWebhookEvent.objects.get(whatsapp_channel=channel)
    assert receipt.status == EvolutionWebhookEvent.Status.IGNORED
    assert receipt.error_code == 'INVALID_EXTERNAL_ID'
