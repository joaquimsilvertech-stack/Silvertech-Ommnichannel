from __future__ import annotations

from unittest.mock import Mock, patch

import pytest
from django.core.cache import cache
from rest_framework import status
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import AccessToken

from omnichannel.evolution import BaseEvolutionClient, EvolutionUnavailableError
from omnichannel.factories import ConversationFactory, WhatsAppChannelFactory
from omnichannel.models import Conversation, WhatsAppChannel
from workspaces.factories import MemberFactory, UserFactory, WorkspaceFactory
from workspaces.models import Member

pytestmark = pytest.mark.django_db

MANAGEMENT_CLIENT_PATH = 'omnichannel.whatsapp_channel_management.get_evolution_client'
SENSITIVE = {
    'instance_name': 'private-instance-reconnect',
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


def _reconnect_url(workspace, channel) -> str:
    return f'/api/workspaces/{workspace.id}/whatsapp-channels/{channel.id}/reconnect/'


def _channel(workspace, **kwargs) -> WhatsAppChannel:
    defaults = {
        'workspace': workspace,
        'status': WhatsAppChannel.Status.DISCONNECTED,
        **SENSITIVE,
    }
    defaults.update(kwargs)
    return WhatsAppChannelFactory(**defaults)


def _mock_client():
    return patch(MANAGEMENT_CLIENT_PATH, return_value=Mock(spec=BaseEvolutionClient))


@pytest.mark.parametrize(
    'from_status',
    [WhatsAppChannel.Status.DISCONNECTED, WhatsAppChannel.Status.ERROR],
)
def test_reconnect_from_stopped_state_moves_to_waiting_qr(from_status) -> None:
    client, _, workspace = _member_client()
    channel = _channel(workspace, status=from_status, last_error_code='PREVIOUS_ERROR')
    with _mock_client() as get_client:
        response = client.post(_reconnect_url(workspace, channel))

    assert response.status_code == status.HTTP_200_OK
    assert response.json()['status'] == WhatsAppChannel.Status.WAITING_QR
    channel.refresh_from_db()
    assert channel.status == WhatsAppChannel.Status.WAITING_QR
    # Reconecta reusando a instancia existente: aciona a via de conexao (QR),
    # nunca recria a instancia.
    get_client.return_value.get_qr_code.assert_called_once_with(
        instance_name=channel.instance_name,
    )
    get_client.return_value.create_instance.assert_not_called()


def test_reconnect_preserves_instance_secret_and_history() -> None:
    client, _, workspace = _member_client()
    channel = _channel(workspace, status=WhatsAppChannel.Status.DISCONNECTED)
    original_instance = channel.instance_name
    original_public_id = channel.webhook_public_id
    original_secret = channel.webhook_secret
    conversation = ConversationFactory(workspace=workspace, whatsapp_channel=channel)

    with _mock_client():
        response = client.post(_reconnect_url(workspace, channel))

    assert response.status_code == status.HTTP_200_OK
    channel.refresh_from_db()
    assert channel.instance_name == original_instance
    assert channel.webhook_public_id == original_public_id
    assert channel.webhook_secret == original_secret
    conversation.refresh_from_db()
    assert conversation.whatsapp_channel_id == channel.id


def test_reconnect_is_idempotent_when_already_waiting_qr() -> None:
    client, _, workspace = _member_client()
    channel = _channel(workspace, status=WhatsAppChannel.Status.WAITING_QR)
    with _mock_client() as get_client:
        response = client.post(_reconnect_url(workspace, channel))

    assert response.status_code == status.HTTP_200_OK
    assert response.json()['status'] == WhatsAppChannel.Status.WAITING_QR
    channel.refresh_from_db()
    assert channel.status == WhatsAppChannel.Status.WAITING_QR
    # Ja aguardando QR: nao recria instancia nem duplica QR.
    get_client.return_value.get_qr_code.assert_not_called()
    get_client.return_value.create_instance.assert_not_called()


@pytest.mark.parametrize(
    'blocked_status',
    [
        WhatsAppChannel.Status.PROVISIONING,
        WhatsAppChannel.Status.DELETING,
        WhatsAppChannel.Status.CONNECTED,
        WhatsAppChannel.Status.CONNECTING,
        WhatsAppChannel.Status.RECONNECTING,
    ],
)
def test_reconnect_blocked_from_incompatible_state_returns_409(blocked_status) -> None:
    client, _, workspace = _member_client()
    channel = _channel(workspace, status=blocked_status)
    with _mock_client() as get_client:
        response = client.post(_reconnect_url(workspace, channel))

    assert response.status_code == status.HTTP_409_CONFLICT
    assert response.json()['error_code'] == 'CHANNEL_STATE_CONFLICT'
    get_client.return_value.get_qr_code.assert_not_called()
    channel.refresh_from_db()
    assert channel.status == blocked_status


@pytest.mark.parametrize('role', [Member.Role.OWNER, Member.Role.ADMIN])
def test_owner_and_admin_can_reconnect(role) -> None:
    client, _, workspace = _member_client(role=role)
    channel = _channel(workspace)
    with _mock_client():
        response = client.post(_reconnect_url(workspace, channel))

    assert response.status_code == status.HTTP_200_OK


def test_agent_cannot_reconnect() -> None:
    client, _, workspace = _member_client(role=Member.Role.AGENT)
    channel = _channel(workspace)
    with _mock_client() as get_client:
        response = client.post(_reconnect_url(workspace, channel))

    assert response.status_code == status.HTTP_403_FORBIDDEN
    get_client.return_value.get_qr_code.assert_not_called()
    channel.refresh_from_db()
    assert channel.status == WhatsAppChannel.Status.DISCONNECTED


def test_non_member_cannot_reconnect() -> None:
    _, _, workspace = _member_client()
    channel = _channel(workspace)
    outsider = _client_for(UserFactory())
    with _mock_client():
        response = outsider.post(_reconnect_url(workspace, channel))

    assert response.status_code == status.HTTP_403_FORBIDDEN


def test_cross_tenant_channel_returns_404_without_leaking_existence() -> None:
    client, _, workspace = _member_client()
    other_channel = _channel(WorkspaceFactory())
    with _mock_client():
        response = client.post(_reconnect_url(workspace, other_channel))

    assert response.status_code == status.HTTP_404_NOT_FOUND
    assert other_channel.instance_name not in response.content.decode()


def test_superuser_without_membership_can_reconnect() -> None:
    workspace = WorkspaceFactory()
    channel = _channel(workspace)
    superuser = UserFactory(is_staff=True, is_superuser=True)
    with _mock_client():
        response = _client_for(superuser).post(_reconnect_url(workspace, channel))

    assert response.status_code == status.HTTP_200_OK


def test_evolution_error_returns_safe_status_without_internal_detail() -> None:
    client, _, workspace = _member_client()
    channel = _channel(workspace)
    failing = Mock(spec=BaseEvolutionClient)
    failing.get_qr_code.side_effect = EvolutionUnavailableError('boom raw evolution body')
    with patch(MANAGEMENT_CLIENT_PATH, return_value=failing):
        response = client.post(_reconnect_url(workspace, channel))

    assert response.status_code == status.HTTP_502_BAD_GATEWAY
    body = response.json()
    assert body['error_code'] == 'EVOLUTION_UNAVAILABLE'
    raw = response.content.decode()
    assert 'boom raw evolution body' not in raw
    for secret in SENSITIVE.values():
        assert secret not in raw
    # Canal permanece em estado coerente (nao avanca para WAITING_QR na falha).
    channel.refresh_from_db()
    assert channel.status == WhatsAppChannel.Status.DISCONNECTED


def test_reconnect_response_does_not_leak_secrets() -> None:
    client, _, workspace = _member_client()
    channel = _channel(workspace, status=WhatsAppChannel.Status.DISCONNECTED)
    with _mock_client():
        response = client.post(_reconnect_url(workspace, channel))

    raw = response.content.decode()
    assert response['Cache-Control'] == 'private, no-store'
    for secret in SENSITIVE.values():
        assert secret not in raw


@pytest.mark.parametrize('method', ['get', 'put', 'patch', 'delete'])
def test_reconnect_only_allows_post(method) -> None:
    client, _, workspace = _member_client()
    channel = _channel(workspace)
    response = getattr(client, method)(_reconnect_url(workspace, channel))
    assert response.status_code == status.HTTP_405_METHOD_NOT_ALLOWED
