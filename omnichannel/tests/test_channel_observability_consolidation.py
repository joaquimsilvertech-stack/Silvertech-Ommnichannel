from __future__ import annotations

import logging
from datetime import timedelta
from unittest.mock import Mock, patch

import pytest
from django.conf import settings
from django.core.cache import cache
from django.utils import timezone
from rest_framework.test import APIClient

from omnichannel.evolution import BaseEvolutionClient, EvolutionUnavailableError
from omnichannel.evolution_event_processing import process_evolution_channel_event
from omnichannel.factories import WhatsAppChannelFactory
from omnichannel.models import AIObservabilityEvent, WhatsAppChannel
from omnichannel.observability import (
    get_channel_observability_summary,
    record_channel_observability_event_safe,
)
from omnichannel.observability_serializers import AIObservabilityEventSerializer
from omnichannel.whatsapp_channel_management import (
    WhatsAppChannelManagementError,
    disconnect_whatsapp_channel,
    reconnect_whatsapp_channel,
    remove_whatsapp_channel,
    restart_whatsapp_channel,
)
from workspaces.factories import WorkspaceFactory

pytestmark = pytest.mark.django_db

EventType = AIObservabilityEvent.EventType
EventStatus = AIObservabilityEvent.Status
VALID_QR = 'Q' * 128
FULL_PHONE = '+55 (11) 99876-5432'


@pytest.fixture(autouse=True)
def clear_qr_cache():
    cache.clear()
    yield
    cache.clear()


def _record(workspace, channel, event_type, **kwargs):
    return record_channel_observability_event_safe(
        workspace=workspace,
        channel=channel,
        event_type=event_type,
        status=kwargs.pop('status', EventStatus.SUCCESS),
        **kwargs,
    )


def _connection_payload(state: str, **data) -> dict:
    return {
        'event': 'connection.update',
        'data': {'state': state, 'timestamp': f'2026-07-31T12:00:0{len(state)}Z', **data},
    }


def _inbound_payload(message_type: str) -> dict:
    return {
        'event': 'messages.upsert',
        'data': {
            'key': {
                'id': 'malicious-message-type-1',
                'remoteJid': '5511999990000@s.whatsapp.net',
                'fromMe': False,
            },
            'pushName': 'Contato seguro',
            'message': {'conversation': 'body que nao pode ir para observabilidade'},
            'messageType': message_type,
        },
    }


def test_cross_tenant_channel_is_rejected_at_recording_boundary_without_uuid_leak(caplog) -> None:
    workspace = WorkspaceFactory()
    foreign_channel = WhatsAppChannelFactory()
    caplog.set_level(logging.WARNING, logger='omnichannel.observability')

    result = _record(workspace, foreign_channel, EventType.CHANNEL_CONNECTED)

    assert result is None
    assert not AIObservabilityEvent.objects.filter(workspace=workspace).exists()
    rendered = ' '.join(record.getMessage() + repr(record.__dict__) for record in caplog.records)
    assert str(foreign_channel.id) not in rendered


def test_message_type_is_allowlisted_in_storage_serializer_summary_and_logs(caplog) -> None:
    channel = WhatsAppChannelFactory(status=WhatsAppChannel.Status.CONNECTED)
    caplog.set_level(logging.INFO)

    process_evolution_channel_event(
        channel=channel,
        payload=_inbound_payload(FULL_PHONE),
    )

    event = AIObservabilityEvent.objects.get(
        whatsapp_channel=channel,
        event_type=EventType.CHANNEL_INBOUND_RECEIVED,
    )
    assert event.metadata == {
        'action': 'inbound',
        'direction': 'inbound',
        'message_type': 'unknown',
    }
    serialized = AIObservabilityEventSerializer(event).data
    summary = get_channel_observability_summary(workspace=channel.workspace)
    rendered_logs = ' '.join(record.getMessage() + repr(record.__dict__) for record in caplog.records)
    for rendered in (str(event.metadata), str(serialized), str(summary), rendered_logs):
        assert FULL_PHONE not in rendered
        assert '5511998765432' not in rendered


def test_qrcode_updated_records_safe_idempotent_qr_event() -> None:
    channel = WhatsAppChannelFactory(status=WhatsAppChannel.Status.ERROR)
    payload = {'event': 'QRCODE_UPDATED', 'data': {'base64': VALID_QR}}

    process_evolution_channel_event(channel=channel, payload=payload)
    process_evolution_channel_event(channel=channel, payload=payload)

    events = AIObservabilityEvent.objects.filter(
        whatsapp_channel=channel,
        event_type=EventType.CHANNEL_QR_GENERATED,
    )
    assert events.count() == 1
    event = events.get()
    assert event.workspace_id == channel.workspace_id
    assert event.whatsapp_channel_id_snapshot == channel.id
    assert VALID_QR not in repr(event.__dict__)
    assert 'base64' not in repr(event.metadata)


def test_reconnecting_webhook_records_channel_reconnecting() -> None:
    channel = WhatsAppChannelFactory(status=WhatsAppChannel.Status.CONNECTED)
    process_evolution_channel_event(channel=channel, payload=_connection_payload('reconnecting'))
    assert AIObservabilityEvent.objects.filter(
        whatsapp_channel=channel,
        event_type=EventType.CHANNEL_RECONNECTING,
    ).count() == 1


@pytest.mark.parametrize(
    ('operation', 'initial_status', 'client_method'),
    [
        (restart_whatsapp_channel, WhatsAppChannel.Status.CONNECTED, 'restart_instance'),
        (reconnect_whatsapp_channel, WhatsAppChannel.Status.DISCONNECTED, 'get_qr_code'),
        (disconnect_whatsapp_channel, WhatsAppChannel.Status.CONNECTED, 'logout_instance'),
    ],
)
def test_management_failures_record_sanitized_channel_error(
    operation,
    initial_status,
    client_method,
) -> None:
    channel = WhatsAppChannelFactory(status=initial_status)
    client = Mock(spec=BaseEvolutionClient)
    getattr(client, client_method).side_effect = EvolutionUnavailableError(
        'private response body',
        error_code='provider/private?error=5511999998888',
    )

    with pytest.raises(WhatsAppChannelManagementError):
        operation(channel=channel, client=client)

    event = AIObservabilityEvent.objects.get(
        whatsapp_channel=channel,
        event_type=EventType.CHANNEL_ERROR,
    )
    assert event.error_code == 'PROVIDER_PRIVATE_ERROR_5511999998888'[:64]
    assert event.metadata['action'] in {'restart', 'reconnect', 'disconnect'}
    assert 'private response body' not in repr(event.__dict__)


def test_remove_remote_failure_records_error_and_preserves_original_best_effort_contract() -> None:
    channel = WhatsAppChannelFactory(status=WhatsAppChannel.Status.CONNECTED)
    workspace = channel.workspace
    channel_id = channel.id
    client = Mock(spec=BaseEvolutionClient)
    client.delete_instance.side_effect = RuntimeError('private response body')

    remove_whatsapp_channel(channel=channel, client=client)

    assert not WhatsAppChannel.objects.filter(id=channel_id).exists()
    event_types = set(
        AIObservabilityEvent.objects.filter(workspace=workspace).values_list(
            'event_type',
            flat=True,
        ),
    )
    assert {EventType.CHANNEL_ERROR, EventType.CHANNEL_REMOVED} <= event_types
    error = AIObservabilityEvent.objects.get(
        workspace=workspace,
        event_type=EventType.CHANNEL_ERROR,
    )
    assert error.error_code == 'EVOLUTION_REMOTE_DELETE_FAILED'
    assert 'private response body' not in repr(error.__dict__)


def test_connection_error_propagates_sanitized_code_to_error_grouping() -> None:
    channel = WhatsAppChannelFactory(status=WhatsAppChannel.Status.CONNECTING)
    process_evolution_channel_event(
        channel=channel,
        payload=_connection_payload('error', statusReason='authentication-failed'),
    )

    channel.refresh_from_db()
    event = AIObservabilityEvent.objects.get(
        whatsapp_channel=channel,
        event_type=EventType.CHANNEL_ERROR,
    )
    assert event.error_code == channel.last_error_code == 'AUTHENTICATION_FAILED'
    assert event.metadata == {'action': 'connection_update'}
    assert get_channel_observability_summary(workspace=channel.workspace)['errors'] == [
        {'error_code': event.error_code, 'count': 1},
    ]


def test_avg_time_to_connection_uses_created_to_first_connection_only() -> None:
    channel = WhatsAppChannelFactory()
    base = timezone.now()
    created = _record(channel.workspace, channel, EventType.CHANNEL_CREATED)
    first_connected = _record(channel.workspace, channel, EventType.CHANNEL_CONNECTED)
    reconnect = _record(channel.workspace, channel, EventType.CHANNEL_CONNECTED)
    AIObservabilityEvent.objects.filter(id=created.id).update(created_at=base - timedelta(seconds=10))
    AIObservabilityEvent.objects.filter(id=first_connected.id).update(
        created_at=base - timedelta(seconds=5),
    )
    AIObservabilityEvent.objects.filter(id=reconnect.id).update(created_at=base)

    summary = get_channel_observability_summary(workspace=channel.workspace)

    assert summary['latency']['avg_time_to_connection_ms'] == 5000
    assert summary['totals']['channel_connected_events'] == 2


def test_recent_reconnection_does_not_replace_first_connection_outside_window() -> None:
    channel = WhatsAppChannelFactory()
    base = timezone.now()
    created = _record(channel.workspace, channel, EventType.CHANNEL_CREATED)
    first_connected = _record(channel.workspace, channel, EventType.CHANNEL_CONNECTED)
    _record(channel.workspace, channel, EventType.CHANNEL_CONNECTED)
    AIObservabilityEvent.objects.filter(id=created.id).update(created_at=base - timedelta(days=3))
    AIObservabilityEvent.objects.filter(id=first_connected.id).update(
        created_at=base - timedelta(days=2),
    )

    assert get_channel_observability_summary(
        workspace=channel.workspace,
        period='24h',
    )['latency']['avg_time_to_connection_ms'] is None


def test_channel_inventory_is_current_and_workspace_scoped() -> None:
    workspace = WorkspaceFactory()
    connected = WhatsAppChannelFactory(
        workspace=workspace,
        status=WhatsAppChannel.Status.CONNECTED,
    )
    disconnected = WhatsAppChannelFactory(
        workspace=workspace,
        status=WhatsAppChannel.Status.DISCONNECTED,
    )
    WhatsAppChannelFactory(workspace=workspace, status=WhatsAppChannel.Status.ERROR)
    foreign = WhatsAppChannelFactory(status=WhatsAppChannel.Status.CONNECTED)
    _record(workspace, connected, EventType.CHANNEL_CONNECTED)
    _record(workspace, connected, EventType.CHANNEL_CONNECTED)
    _record(workspace, disconnected, EventType.CHANNEL_DISCONNECTED)
    _record(foreign.workspace, foreign, EventType.CHANNEL_CONNECTED)

    totals = get_channel_observability_summary(workspace=workspace)['totals']
    assert totals['channels_connected'] == 1
    assert totals['channels_disconnected'] == 1
    assert totals['channel_connected_events'] == 2
    assert totals['channel_disconnected_events'] == 1


def test_removed_channel_uuid_snapshot_is_serialized_and_aggregated() -> None:
    channel = WhatsAppChannelFactory(status=WhatsAppChannel.Status.CONNECTED)
    workspace = channel.workspace
    channel_id = channel.id
    client = Mock(spec=BaseEvolutionClient)

    remove_whatsapp_channel(channel=channel, client=client)

    event = AIObservabilityEvent.objects.get(
        workspace=workspace,
        event_type=EventType.CHANNEL_REMOVED,
    )
    assert event.whatsapp_channel_id is None
    assert event.whatsapp_channel_id_snapshot == channel_id
    assert AIObservabilityEventSerializer(event).data['whatsapp_channel_id'] == str(channel_id)
    by_channel = get_channel_observability_summary(workspace=workspace)['by_channel']
    assert str(channel_id) in {row['whatsapp_channel_id'] for row in by_channel}


def test_retention_policy_defaults_are_declared_without_purge() -> None:
    assert settings.CHANNEL_OBSERVABILITY_TRAFFIC_RETENTION_DAYS == 90
    assert settings.CHANNEL_OBSERVABILITY_LIFECYCLE_RETENTION_DAYS == 365


def test_channel_observability_endpoints_are_typed_in_openapi() -> None:
    response = APIClient().get('/api/schema/')
    assert response.status_code == 200
    schema = response.data
    summary_path = '/api/workspaces/{workspace_id}/channel-observability/summary/'
    timeseries_path = '/api/workspaces/{workspace_id}/channel-observability/timeseries/'
    assert summary_path in schema['paths']
    assert timeseries_path in schema['paths']
    summary_get = schema['paths'][summary_path]['get']
    timeseries_get = schema['paths'][timeseries_path]['get']
    assert summary_get['operationId'] == 'workspace_channel_observability_summary_retrieve'
    assert timeseries_get['operationId'] == 'workspace_channel_observability_timeseries_retrieve'
    assert {'200', '400', '401', '403', '404'} <= set(summary_get['responses'])
    period = next(item for item in summary_get['parameters'] if item['name'] == 'period')
    assert period['schema']['enum'] == ['24h', '7d', '30d']


def test_consolidation_paths_never_call_real_evolution_or_openai() -> None:
    channel = WhatsAppChannelFactory(status=WhatsAppChannel.Status.CONNECTED)
    with (
        patch('requests.sessions.Session.request') as http_request,
        patch('omnichannel.tasks.process_ai_response.delay') as ai_task,
    ):
        process_evolution_channel_event(
            channel=channel,
            payload=_connection_payload('reconnecting'),
        )
    http_request.assert_not_called()
    ai_task.assert_not_called()
