from __future__ import annotations

import pytest
from rest_framework import status
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import AccessToken

from omnichannel.factories import WhatsAppChannelFactory
from omnichannel.models import AIObservabilityEvent
from omnichannel.observability import record_channel_observability_event_safe
from workspaces.factories import MemberFactory, UserFactory, WorkspaceFactory
from workspaces.models import Member, Workspace

pytestmark = pytest.mark.django_db

EventType = AIObservabilityEvent.EventType


def _client_for(user) -> APIClient:
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f'Bearer {AccessToken.for_user(user)}')
    return client


def _owner_client(workspace=None):
    user = UserFactory()
    workspace = workspace or WorkspaceFactory()
    MemberFactory(user=user, workspace=workspace, role=Member.Role.OWNER)
    return _client_for(user), workspace


def _summary_url(workspace: Workspace) -> str:
    return f'/api/workspaces/{workspace.id}/channel-observability/summary/'


def _timeseries_url(workspace: Workspace) -> str:
    return f'/api/workspaces/{workspace.id}/channel-observability/timeseries/'


def _emit(workspace, event_type, **kwargs):
    channel = kwargs.pop('channel', None) or WhatsAppChannelFactory(workspace=workspace)
    record_channel_observability_event_safe(
        workspace=workspace,
        channel=channel,
        event_type=event_type,
        status=kwargs.pop('status', AIObservabilityEvent.Status.SUCCESS),
        **kwargs,
    )
    return channel


def test_owner_can_access_channel_summary() -> None:
    client, workspace = _owner_client()
    channel = WhatsAppChannelFactory(
        workspace=workspace,
        status='connected',
    )
    _emit(workspace, EventType.CHANNEL_CONNECTED, channel=channel)

    response = client.get(_summary_url(workspace))

    assert response.status_code == status.HTTP_200_OK
    assert response.json()['totals']['channels_connected'] == 1


def test_admin_can_access_channel_summary() -> None:
    workspace = WorkspaceFactory()
    user = UserFactory()
    MemberFactory(user=user, workspace=workspace, role=Member.Role.ADMIN)

    response = _client_for(user).get(_summary_url(workspace))

    assert response.status_code == status.HTTP_200_OK


def test_agent_and_non_member_cannot_access_channel_summary() -> None:
    workspace = WorkspaceFactory()
    agent = UserFactory()
    non_member = UserFactory()
    MemberFactory(user=agent, workspace=workspace, role=Member.Role.AGENT)

    assert _client_for(agent).get(
        _summary_url(workspace),
    ).status_code == status.HTTP_403_FORBIDDEN
    assert _client_for(non_member).get(
        _summary_url(workspace),
    ).status_code == status.HTTP_403_FORBIDDEN


def test_summary_is_scoped_to_workspace() -> None:
    client, workspace = _owner_client()
    other_workspace = WorkspaceFactory()
    local_channel = WhatsAppChannelFactory(workspace=workspace, status='connected')
    other_channel = WhatsAppChannelFactory(workspace=other_workspace, status='connected')
    _emit(workspace, EventType.CHANNEL_CONNECTED, channel=local_channel)
    _emit(other_workspace, EventType.CHANNEL_CONNECTED, channel=other_channel)
    _emit(other_workspace, EventType.CHANNEL_ERROR)

    body = client.get(_summary_url(workspace)).json()

    assert body['workspace_id'] == str(workspace.id)
    assert body['totals']['channels_connected'] == 1
    assert body['totals']['channels_error'] == 0


def test_cross_tenant_request_does_not_leak_other_workspace() -> None:
    client, _ = _owner_client()
    other_workspace = WorkspaceFactory()
    _emit(other_workspace, EventType.CHANNEL_CONNECTED)

    # Membro do proprio workspace pedindo o de outro tenant: negado, sem vazar.
    response = client.get(_summary_url(other_workspace))
    assert response.status_code in {status.HTTP_403_FORBIDDEN, status.HTTP_404_NOT_FOUND}
    assert 'channels_connected' not in response.content.decode()


def test_summary_aggregates_channel_metrics() -> None:
    client, workspace = _owner_client()
    channel = WhatsAppChannelFactory(workspace=workspace, status='connected')
    _emit(workspace, EventType.CHANNEL_CONNECTED, channel=channel)
    _emit(workspace, EventType.CHANNEL_DISCONNECTED, channel=channel)
    _emit(
        workspace,
        EventType.CHANNEL_ERROR,
        channel=channel,
        status=AIObservabilityEvent.Status.FAILED,
        reason_code='PROVISIONING',
    )
    _emit(workspace, EventType.CHANNEL_INBOUND_RECEIVED, channel=channel)
    _emit(workspace, EventType.OUTBOUND_DELIVERY_SUCCESS, channel=channel)
    _emit(
        workspace,
        EventType.OUTBOUND_DELIVERY_FAILED,
        channel=channel,
        status=AIObservabilityEvent.Status.FAILED,
    )

    totals = client.get(_summary_url(workspace)).json()['totals']
    assert totals['channels_connected'] == 1
    assert totals['channels_disconnected'] == 0
    assert totals['channel_connected_events'] == 1
    assert totals['channel_disconnected_events'] == 1
    assert totals['channels_error'] == 1
    assert totals['provisioning_failed'] == 1
    assert totals['inbound_received'] == 1
    assert totals['outbound_success'] == 1
    assert totals['outbound_failed'] == 1

    body = client.get(_summary_url(workspace)).json()
    assert body['rates']['outbound_success_rate'] == 0.5
    channel_rows = {row['whatsapp_channel_id']: row for row in body['by_channel']}
    assert str(channel.id) in channel_rows
    assert channel_rows[str(channel.id)]['connected'] == 1


def test_timeseries_scoped_and_ok() -> None:
    client, workspace = _owner_client()
    _emit(workspace, EventType.CHANNEL_CONNECTED)

    response = client.get(_timeseries_url(workspace))

    assert response.status_code == status.HTTP_200_OK
    body = response.json()
    assert body['workspace_id'] == str(workspace.id)
    assert sum(point['connected'] for point in body['points']) == 1


def test_invalid_period_is_rejected() -> None:
    client, workspace = _owner_client()
    response = client.get(_summary_url(workspace), {'period': 'bogus'})
    assert response.status_code == status.HTTP_400_BAD_REQUEST
