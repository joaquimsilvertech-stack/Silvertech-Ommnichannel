from __future__ import annotations

from unittest.mock import patch
from uuid import uuid4

import pytest
from django.conf import settings as django_settings
from django.core.cache import cache
from django.test import override_settings
from rest_framework import status
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import AccessToken

from omnichannel.evolution_qr_cache import (
    EvolutionQRCodeCacheError,
    store_evolution_qr_code,
)
from omnichannel.factories import WhatsAppChannelFactory
from omnichannel.models import WhatsAppChannel
from workspaces.factories import MemberFactory, UserFactory, WorkspaceFactory
from workspaces.models import Member

pytestmark = pytest.mark.django_db

STATUS_FIELDS = {
    'id',
    'status',
    'phone_number_masked',
    'has_qr_code',
    'connected_at',
    'last_connection_update_at',
    'updated_at',
}
RAW_QR = 'S' * 128


@pytest.fixture(autouse=True)
def clear_channel_cache():
    cache.clear()
    yield
    cache.clear()


def _client_for(user) -> APIClient:
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f'Bearer {AccessToken.for_user(user)}')
    return client


def _member_client(*, role: str = Member.Role.OWNER, workspace=None):
    user = UserFactory()
    workspace = workspace or WorkspaceFactory()
    MemberFactory(user=user, workspace=workspace, role=role)
    return _client_for(user), user, workspace


def _status_url(workspace, channel) -> str:
    return (
        f'/api/workspaces/{workspace.id}/whatsapp-channels/'
        f'{channel.id}/status/'
    )


def _sensitive_channel(*, workspace, **kwargs):
    defaults = {
        'workspace': workspace,
        'instance_name': f'private-instance-{uuid4().hex}',
        'instance_id': 'private-instance-id',
        'instance_token': 'private-instance-token',
        'webhook_secret': 'private-webhook-secret',
        'phone_number': '5511999991234',
        'last_error_code': 'PRIVATE_LAST_ERROR',
    }
    defaults.update(kwargs)
    return WhatsAppChannelFactory(**defaults)


def test_status_requires_authentication() -> None:
    workspace = WorkspaceFactory()
    channel = WhatsAppChannelFactory(workspace=workspace)
    response = APIClient().get(_status_url(workspace, channel))
    assert response.status_code == status.HTTP_401_UNAUTHORIZED


@pytest.mark.parametrize('role', [Member.Role.OWNER, Member.Role.ADMIN])
def test_owner_and_admin_can_read_status(role: str) -> None:
    client, _, workspace = _member_client(role=role)
    channel = WhatsAppChannelFactory(workspace=workspace)
    response = client.get(_status_url(workspace, channel))
    assert response.status_code == status.HTTP_200_OK
    assert response.json()['id'] == str(channel.id)


def test_superuser_can_read_status_without_membership() -> None:
    user = UserFactory(is_superuser=True, is_staff=True)
    workspace = WorkspaceFactory()
    channel = WhatsAppChannelFactory(workspace=workspace)
    response = _client_for(user).get(_status_url(workspace, channel))
    assert response.status_code == status.HTTP_200_OK


@pytest.mark.parametrize('access_kind', ['agent', 'non_member'])
def test_agent_and_non_member_cannot_read_status(access_kind: str) -> None:
    workspace = WorkspaceFactory()
    channel = WhatsAppChannelFactory(workspace=workspace)
    if access_kind == 'agent':
        client, _, _ = _member_client(role=Member.Role.AGENT, workspace=workspace)
    else:
        client = _client_for(UserFactory())
    response = client.get(_status_url(workspace, channel))
    assert response.status_code == status.HTTP_403_FORBIDDEN


def test_cross_tenant_channel_is_hidden() -> None:
    client, _, workspace = _member_client()
    other = _sensitive_channel(workspace=WorkspaceFactory())
    response = client.get(_status_url(workspace, other))
    assert response.status_code == status.HTTP_404_NOT_FOUND
    assert other.instance_name not in response.content.decode()


def test_status_returns_only_current_local_public_fields() -> None:
    client, _, workspace = _member_client()
    channel = _sensitive_channel(
        workspace=workspace,
        status=WhatsAppChannel.Status.CONNECTED,
    )

    response = client.get(_status_url(workspace, channel))

    payload = response.json()
    rendered = response.content.decode()
    assert response.status_code == status.HTTP_200_OK
    assert set(payload) == STATUS_FIELDS
    assert payload['status'] == WhatsAppChannel.Status.CONNECTED
    assert payload['phone_number_masked'] == '********1234'
    assert payload['has_qr_code'] is False
    for secret in (
        channel.phone_number,
        channel.instance_name,
        channel.instance_id,
        channel.instance_token,
        channel.webhook_secret,
        channel.last_error_code,
        str(channel.webhook_public_id),
    ):
        assert secret not in rendered


@pytest.mark.parametrize(
    ('channel_status', 'cache_qr', 'expected'),
    [
        (WhatsAppChannel.Status.WAITING_QR, True, True),
        (WhatsAppChannel.Status.WAITING_QR, False, False),
        (WhatsAppChannel.Status.CONNECTED, True, False),
        (WhatsAppChannel.Status.CONNECTING, True, False),
        (WhatsAppChannel.Status.ERROR, True, False),
        (WhatsAppChannel.Status.DELETING, True, False),
    ],
)
def test_status_has_qr_only_for_waiting_channel_with_cache(
    channel_status: str,
    cache_qr: bool,
    expected: bool,
) -> None:
    client, _, workspace = _member_client()
    channel = WhatsAppChannelFactory(workspace=workspace, status=channel_status)
    if cache_qr:
        store_evolution_qr_code(channel.id, RAW_QR)

    response = client.get(_status_url(workspace, channel))

    assert response.status_code == status.HTTP_200_OK
    assert response.json()['has_qr_code'] is expected
    assert RAW_QR not in response.content.decode()


def test_status_never_calls_evolution_http_or_celery() -> None:
    client, _, workspace = _member_client()
    channel = WhatsAppChannelFactory(
        workspace=workspace,
        status=WhatsAppChannel.Status.WAITING_QR,
    )
    with (
        patch('omnichannel.evolution.client.EvolutionAPIClient.get_connection_state') as state_call,
        patch('omnichannel.evolution.client.EvolutionAPIClient.get_qr_code') as qr_call,
        patch('requests.sessions.Session.request') as http_call,
        patch('omnichannel.tasks.process_evolution_channel_webhook_task.delay') as task_call,
    ):
        response = client.get(_status_url(workspace, channel))

    assert response.status_code == status.HTTP_200_OK
    state_call.assert_not_called()
    qr_call.assert_not_called()
    http_call.assert_not_called()
    task_call.assert_not_called()


def test_cache_failure_keeps_local_status_available() -> None:
    client, _, workspace = _member_client()
    channel = _sensitive_channel(
        workspace=workspace,
        status=WhatsAppChannel.Status.WAITING_QR,
    )
    with patch(
        'omnichannel.whatsapp_channel_read_service.get_evolution_qr_code',
        side_effect=EvolutionQRCodeCacheError('QR_CACHE_UNAVAILABLE'),
    ):
        response = client.get(_status_url(workspace, channel))

    assert response.status_code == status.HTTP_200_OK
    assert response.json()['status'] == WhatsAppChannel.Status.WAITING_QR
    assert response.json()['has_qr_code'] is False
    assert channel.phone_number not in response.content.decode()


def test_status_does_not_update_channel() -> None:
    client, _, workspace = _member_client()
    channel = WhatsAppChannelFactory(
        workspace=workspace,
        status=WhatsAppChannel.Status.CONNECTING,
    )
    before = (
        channel.status,
        channel.connected_at,
        channel.last_connection_update_at,
        channel.updated_at,
    )

    response = client.get(_status_url(workspace, channel))

    channel.refresh_from_db()
    assert response.status_code == status.HTTP_200_OK
    assert (
        channel.status,
        channel.connected_at,
        channel.last_connection_update_at,
        channel.updated_at,
    ) == before


def test_status_response_disables_intermediary_cache() -> None:
    client, _, workspace = _member_client()
    channel = WhatsAppChannelFactory(workspace=workspace)
    response = client.get(_status_url(workspace, channel))
    assert response['Cache-Control'] == 'private, no-store'
    assert 'Authorization' in response['Vary']


@pytest.mark.parametrize('method', ['post', 'put', 'patch', 'delete'])
def test_status_is_read_only(method: str) -> None:
    client, _, workspace = _member_client()
    channel = WhatsAppChannelFactory(workspace=workspace)
    response = getattr(client, method)(
        _status_url(workspace, channel),
        {},
        format='json',
    )
    assert response.status_code == status.HTTP_405_METHOD_NOT_ALLOWED


def test_status_allows_head_and_options() -> None:
    client, _, workspace = _member_client()
    channel = WhatsAppChannelFactory(workspace=workspace)
    assert client.head(_status_url(workspace, channel)).status_code == status.HTTP_200_OK
    assert client.options(_status_url(workspace, channel)).status_code == status.HTTP_200_OK


def test_status_read_throttle_returns_429_with_reduced_rate() -> None:
    client, _, workspace = _member_client()
    channel = WhatsAppChannelFactory(workspace=workspace)
    rates = {
        **django_settings.REST_FRAMEWORK['DEFAULT_THROTTLE_RATES'],
        'whatsapp_channel_read': '1/minute',
    }
    framework_settings = {**django_settings.REST_FRAMEWORK, 'DEFAULT_THROTTLE_RATES': rates}
    cache.clear()
    with override_settings(REST_FRAMEWORK=framework_settings):
        first = client.get(_status_url(workspace, channel))
        second = client.get(_status_url(workspace, channel))
    assert first.status_code == status.HTTP_200_OK
    assert second.status_code == status.HTTP_429_TOO_MANY_REQUESTS
