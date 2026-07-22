from __future__ import annotations

from unittest.mock import Mock, patch

import pytest
from django.core.cache import cache
from rest_framework import status
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import AccessToken

from omnichannel.evolution import BaseEvolutionClient, EvolutionUnavailableError
from omnichannel.factories import WhatsAppChannelFactory
from omnichannel.models import WhatsAppChannel
from workspaces.factories import MemberFactory, UserFactory, WorkspaceFactory
from workspaces.models import Member

pytestmark = pytest.mark.django_db

MANAGEMENT_CLIENT_PATH = 'omnichannel.whatsapp_channel_management.get_evolution_client'
SENSITIVE = {
    'instance_name': 'private-instance-disconnect',
    'instance_token': 'private-instance-token',
    'webhook_secret': 'private-webhook-secret',
    'phone_number': '5511999993333',
}


@pytest.fixture(autouse=True)
def clear_cache():
    cache.clear()
    yield
    cache.clear()


def _client_for(user) -> APIClient:
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f'Bearer {AccessToken.for_user(user)}')
    return client


def _member_client(*, role=Member.Role.OWNER, workspace=None):
    user = UserFactory()
    workspace = workspace or WorkspaceFactory()
    MemberFactory(user=user, workspace=workspace, role=role)
    return _client_for(user), user, workspace


def _disconnect_url(workspace, channel) -> str:
    return f'/api/workspaces/{workspace.id}/whatsapp-channels/{channel.id}/disconnect/'


def _channel(workspace, **kwargs) -> WhatsAppChannel:
    defaults = {
        'workspace': workspace,
        'status': WhatsAppChannel.Status.CONNECTED,
        'connected_at': None,
        **SENSITIVE,
    }
    defaults.update(kwargs)
    return WhatsAppChannelFactory(**defaults)


def _mock_client():
    return patch(MANAGEMENT_CLIENT_PATH, return_value=Mock(spec=BaseEvolutionClient))


@pytest.mark.parametrize('role', [Member.Role.OWNER, Member.Role.ADMIN])
def test_owner_and_admin_can_disconnect(role) -> None:
    client, _, workspace = _member_client(role=role)
    channel = _channel(workspace)
    with _mock_client() as get_client:
        response = client.post(_disconnect_url(workspace, channel))

    assert response.status_code == status.HTTP_200_OK
    assert response.json()['status'] == WhatsAppChannel.Status.DISCONNECTED
    channel.refresh_from_db()
    assert channel.status == WhatsAppChannel.Status.DISCONNECTED
    assert channel.phone_number == ''
    assert channel.connected_at is None
    get_client.return_value.logout_instance.assert_called_once()


def test_agent_cannot_disconnect() -> None:
    client, _, workspace = _member_client(role=Member.Role.AGENT)
    channel = _channel(workspace)
    with _mock_client():
        response = client.post(_disconnect_url(workspace, channel))

    assert response.status_code == status.HTTP_403_FORBIDDEN
    channel.refresh_from_db()
    assert channel.status == WhatsAppChannel.Status.CONNECTED


def test_non_member_cannot_disconnect() -> None:
    _, _, workspace = _member_client()
    channel = _channel(workspace)
    with _mock_client():
        response = _client_for(UserFactory()).post(_disconnect_url(workspace, channel))

    assert response.status_code == status.HTTP_403_FORBIDDEN


def test_cross_tenant_channel_returns_404() -> None:
    client, _, workspace = _member_client()
    other_channel = _channel(WorkspaceFactory())
    with _mock_client():
        response = client.post(_disconnect_url(workspace, other_channel))

    assert response.status_code == status.HTTP_404_NOT_FOUND
    assert other_channel.instance_name not in response.content.decode()


def test_superuser_without_membership_can_disconnect() -> None:
    workspace = WorkspaceFactory()
    channel = _channel(workspace)
    superuser = UserFactory(is_staff=True, is_superuser=True)
    with _mock_client():
        response = _client_for(superuser).post(_disconnect_url(workspace, channel))

    assert response.status_code == status.HTTP_200_OK


def test_disconnect_is_idempotent_without_calling_evolution() -> None:
    client, _, workspace = _member_client()
    channel = _channel(workspace, status=WhatsAppChannel.Status.DISCONNECTED)
    with _mock_client() as get_client:
        response = client.post(_disconnect_url(workspace, channel))

    assert response.status_code == status.HTTP_200_OK
    assert response.json()['status'] == WhatsAppChannel.Status.DISCONNECTED
    get_client.return_value.logout_instance.assert_not_called()


@pytest.mark.parametrize(
    'blocked_status',
    [WhatsAppChannel.Status.PROVISIONING, WhatsAppChannel.Status.DELETING],
)
def test_disconnect_forbidden_during_lifecycle_returns_409(blocked_status) -> None:
    client, _, workspace = _member_client()
    channel = _channel(workspace, status=blocked_status)
    with _mock_client() as get_client:
        response = client.post(_disconnect_url(workspace, channel))

    assert response.status_code == status.HTTP_409_CONFLICT
    assert response.json()['error_code'] == 'CHANNEL_STATE_CONFLICT'
    get_client.return_value.logout_instance.assert_not_called()


def test_evolution_error_returns_safe_status_without_internal_detail() -> None:
    client, _, workspace = _member_client()
    channel = _channel(workspace)
    failing = Mock(spec=BaseEvolutionClient)
    failing.logout_instance.side_effect = EvolutionUnavailableError('raw evolution stack')
    with patch(MANAGEMENT_CLIENT_PATH, return_value=failing):
        response = client.post(_disconnect_url(workspace, channel))

    assert response.status_code == status.HTTP_502_BAD_GATEWAY
    raw = response.content.decode()
    assert response.json()['error_code'] == 'EVOLUTION_UNAVAILABLE'
    assert 'raw evolution stack' not in raw
    for secret in SENSITIVE.values():
        assert secret not in raw
    # Falha de logout nao deve corromper o estado do canal.
    channel.refresh_from_db()
    assert channel.status == WhatsAppChannel.Status.CONNECTED


@pytest.mark.parametrize('method', ['get', 'put', 'patch', 'delete'])
def test_disconnect_only_allows_post(method) -> None:
    client, _, workspace = _member_client()
    channel = _channel(workspace)
    response = getattr(client, method)(_disconnect_url(workspace, channel))
    assert response.status_code == status.HTTP_405_METHOD_NOT_ALLOWED
