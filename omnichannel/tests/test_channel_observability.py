from __future__ import annotations

from unittest.mock import Mock, patch

import pytest
from django.core.cache import cache

from omnichannel.evolution import BaseEvolutionClient, EvolutionUnavailableError
from omnichannel.evolution_event_processing import process_evolution_channel_event
from omnichannel.factories import WhatsAppChannelFactory
from omnichannel.models import AIObservabilityEvent, WhatsAppChannel
from omnichannel.observability import record_channel_observability_event_safe
from omnichannel.whatsapp_channel_management import (
    disconnect_whatsapp_channel,
    reconnect_whatsapp_channel,
    remove_whatsapp_channel,
    restart_whatsapp_channel,
)
from omnichannel.whatsapp_channel_provisioning import provision_whatsapp_channel
from workspaces.factories import WorkspaceFactory

pytestmark = pytest.mark.django_db

EventType = AIObservabilityEvent.EventType


@pytest.fixture(autouse=True)
def clear_cache():
    cache.clear()
    yield
    cache.clear()


def _success_response() -> dict:
    return {
        'instance': {
            'instanceName': 'remote-name-not-trusted',
            'instanceId': 'remote-instance-id',
            'status': 'created',
        },
        'hash': {'apikey': 'remote-instance-token'},
        'qrcode': {'base64': 'private-qr-base64', 'pairingCode': 'PRIVATE-PAIRING'},
    }


@pytest.fixture
def evolution_client() -> Mock:
    client = Mock(spec=BaseEvolutionClient)
    client.create_instance.return_value = _success_response()
    client.delete_instance.return_value = {}
    return client


def _events_for(channel, event_type=None):
    queryset = AIObservabilityEvent.objects.filter(whatsapp_channel=channel)
    if event_type is not None:
        queryset = queryset.filter(event_type=event_type)
    return list(queryset)


def _inbound_item(external_id='incoming-1', *, phone='5511977776666', text='Ola mundo') -> dict:
    return {
        'key': {'id': external_id, 'remoteJid': f'{phone}@s.whatsapp.net', 'fromMe': False},
        'pushName': 'Contato Teste',
        'message': {'conversation': text},
        'messageType': 'conversation',
    }


def _inbound_payload(item) -> dict:
    return {
        'event': 'messages.upsert',
        'instance': 'untrusted-instance',
        'workspace_id': 'untrusted-workspace',
        'data': item,
    }


def _connection_payload(state, **data) -> dict:
    return {
        'event': 'connection.update',
        'workspace_id': 'untrusted-workspace',
        'data': {'state': state, 'timestamp': f'2026-07-20T10:00:0{len(state)}Z', **data},
    }


# --- Provisioning lifecycle -------------------------------------------------

def test_provisioning_records_full_lifecycle(evolution_client) -> None:
    workspace = WorkspaceFactory()
    result = provision_whatsapp_channel(
        workspace=workspace,
        channel_name='Canal principal',
        client=evolution_client,
    )
    channel = result.channel

    recorded = {event.event_type for event in _events_for(channel)}
    assert {
        EventType.CHANNEL_CREATED,
        EventType.CHANNEL_PROVISIONED,
        EventType.CHANNEL_WEBHOOK_CONFIGURED,
        EventType.CHANNEL_QR_GENERATED,
    } <= recorded

    for event in _events_for(channel):
        assert event.workspace_id == workspace.id
    qr_event = _events_for(channel, EventType.CHANNEL_QR_GENERATED)[0]
    assert qr_event.latency_ms is not None and qr_event.latency_ms >= 0


def test_provisioning_failure_records_channel_error_with_provisioning_reason() -> None:
    workspace = WorkspaceFactory()
    failing = Mock(spec=BaseEvolutionClient)
    failing.create_instance.side_effect = EvolutionUnavailableError('boom raw body')
    failing.delete_instance.return_value = {}

    with pytest.raises(Exception):
        provision_whatsapp_channel(
            workspace=workspace,
            channel_name='Canal com erro',
            client=failing,
        )

    error_events = AIObservabilityEvent.objects.filter(
        workspace=workspace,
        event_type=EventType.CHANNEL_ERROR,
    )
    assert error_events.count() == 1
    event = error_events.get()
    assert event.status == AIObservabilityEvent.Status.FAILED
    assert event.reason_code == 'PROVISIONING'
    assert 'boom raw body' not in str(event.metadata)


# --- Management -------------------------------------------------------------

def _mock_client():
    return patch(
        'omnichannel.whatsapp_channel_management.get_evolution_client',
        return_value=Mock(spec=BaseEvolutionClient),
    )


def test_restart_records_reconnecting_event() -> None:
    channel = WhatsAppChannelFactory(status=WhatsAppChannel.Status.CONNECTED)
    with _mock_client():
        restart_whatsapp_channel(channel=channel)
    assert _events_for(channel, EventType.CHANNEL_RECONNECTING)


def test_reconnect_records_qr_generated_event() -> None:
    channel = WhatsAppChannelFactory(status=WhatsAppChannel.Status.DISCONNECTED)
    with _mock_client():
        reconnect_whatsapp_channel(channel=channel)
    assert _events_for(channel, EventType.CHANNEL_QR_GENERATED)


def test_disconnect_records_disconnected_event() -> None:
    channel = WhatsAppChannelFactory(status=WhatsAppChannel.Status.CONNECTED)
    with _mock_client():
        disconnect_whatsapp_channel(channel=channel)
    assert _events_for(channel, EventType.CHANNEL_DISCONNECTED)


def test_remove_records_event_that_survives_channel_deletion_via_set_null() -> None:
    workspace = WorkspaceFactory()
    channel = WhatsAppChannelFactory(
        workspace=workspace,
        status=WhatsAppChannel.Status.CONNECTED,
    )
    channel_id = channel.id
    with _mock_client():
        remove_whatsapp_channel(channel=channel)

    assert not WhatsAppChannel.objects.filter(id=channel_id).exists()
    removed_events = AIObservabilityEvent.objects.filter(
        workspace=workspace,
        event_type=EventType.CHANNEL_REMOVED,
    )
    assert removed_events.count() == 1
    event = removed_events.get()
    # SET_NULL: o evento sobrevive ao canal (auditoria preservada).
    assert event.whatsapp_channel_id is None
    assert event.workspace_id == workspace.id


# --- Connection update (webhook) -------------------------------------------

@pytest.mark.parametrize(
    ('state', 'expected_event'),
    [
        ('open', EventType.CHANNEL_CONNECTED),
        ('close', EventType.CHANNEL_DISCONNECTED),
        ('error', EventType.CHANNEL_ERROR),
    ],
)
def test_connection_update_records_channel_event(state, expected_event) -> None:
    channel = WhatsAppChannelFactory(status=WhatsAppChannel.Status.CONNECTING)
    process_evolution_channel_event(channel=channel, payload=_connection_payload(state))
    assert _events_for(channel, expected_event)


def test_connection_error_uses_connection_reason_code() -> None:
    channel = WhatsAppChannelFactory(status=WhatsAppChannel.Status.CONNECTING)
    process_evolution_channel_event(channel=channel, payload=_connection_payload('error'))
    event = _events_for(channel, EventType.CHANNEL_ERROR)[0]
    assert event.reason_code == 'CONNECTION'


# --- Inbound volume (no body / no phone) -----------------------------------

def test_inbound_records_volume_event_without_body_or_phone() -> None:
    channel = WhatsAppChannelFactory(status=WhatsAppChannel.Status.CONNECTED)
    item = _inbound_item(text='Segredo do cliente', phone='5511900001111')
    process_evolution_channel_event(channel=channel, payload=_inbound_payload(item))

    events = _events_for(channel, EventType.CHANNEL_INBOUND_RECEIVED)
    assert len(events) == 1
    event = events[0]
    serialized = str(event.metadata)
    assert 'Segredo do cliente' not in serialized
    assert '5511900001111' not in serialized
    assert event.metadata.get('message_type') == 'conversation'
    assert event.metadata.get('direction') == 'inbound'


# --- Sanitization -----------------------------------------------------------

def test_helper_drops_sensitive_metadata_keys() -> None:
    workspace = WorkspaceFactory()
    channel = WhatsAppChannelFactory(workspace=workspace)
    record_channel_observability_event_safe(
        workspace=workspace,
        channel=channel,
        event_type=EventType.CHANNEL_CONNECTED,
        status=AIObservabilityEvent.Status.SUCCESS,
        metadata={
            'body': 'texto secreto',
            'phone': '5511999998888',
            'webhook_secret': 'super-secret',
            'instance_token': 'token-value',
            'api_key': 'key-value',
            'direction': 'inbound',
        },
    )
    event = _events_for(channel, EventType.CHANNEL_CONNECTED)[0]
    assert event.metadata == {'direction': 'inbound'}


# --- Resilience: observability never breaks the main flow -------------------

def test_provisioning_completes_even_if_observability_raises(evolution_client) -> None:
    workspace = WorkspaceFactory()
    with patch(
        'omnichannel.observability.record_ai_observability_event',
        side_effect=RuntimeError('observability down'),
    ):
        result = provision_whatsapp_channel(
            workspace=workspace,
            channel_name='Canal resiliente',
            client=evolution_client,
        )
    assert result.channel.status == WhatsAppChannel.Status.WAITING_QR
    assert AIObservabilityEvent.objects.filter(workspace=workspace).count() == 0


def test_reconnect_completes_even_if_observability_raises() -> None:
    channel = WhatsAppChannelFactory(status=WhatsAppChannel.Status.DISCONNECTED)
    with _mock_client(), patch(
        'omnichannel.observability.record_ai_observability_event',
        side_effect=RuntimeError('observability down'),
    ):
        result = reconnect_whatsapp_channel(channel=channel)
    assert result.status == WhatsAppChannel.Status.WAITING_QR


def test_inbound_completes_even_if_observability_raises() -> None:
    from omnichannel.models import Message

    channel = WhatsAppChannelFactory(status=WhatsAppChannel.Status.CONNECTED)
    with patch(
        'omnichannel.observability.record_ai_observability_event',
        side_effect=RuntimeError('observability down'),
    ):
        process_evolution_channel_event(
            channel=channel,
            payload=_inbound_payload(_inbound_item()),
        )
    assert Message.objects.filter(
        conversation__whatsapp_channel=channel,
        direction=Message.Direction.INBOUND,
    ).exists()
