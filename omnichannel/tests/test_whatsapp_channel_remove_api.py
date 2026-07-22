from __future__ import annotations

from unittest.mock import Mock, patch

import pytest
from django.core.cache import cache
from rest_framework import status
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import AccessToken

from omnichannel.evolution import BaseEvolutionClient, EvolutionUnavailableError
from omnichannel.factories import (
    ConversationFactory,
    EvolutionWebhookEventFactory,
    WhatsAppChannelFactory,
)
from omnichannel.models import Conversation, EvolutionWebhookEvent, WhatsAppChannel
from workspaces.factories import MemberFactory, UserFactory, WorkspaceFactory
from workspaces.models import Member

pytestmark = pytest.mark.django_db

MANAGEMENT_CLIENT_PATH = 'omnichannel.whatsapp_channel_management.get_evolution_client'
SENSITIVE = {
    'instance_name': 'private-instance-remove',
    'instance_token': 'private-instance-token',
    'webhook_secret': 'private-webhook-secret',
    'phone_number': '5511999994444',
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


def _detail_url(workspace, channel) -> str:
    return f'/api/workspaces/{workspace.id}/whatsapp-channels/{channel.id}/'


def _channel(workspace, **kwargs) -> WhatsAppChannel:
    defaults = {'workspace': workspace, 'status': WhatsAppChannel.Status.CONNECTED, **SENSITIVE}
    defaults.update(kwargs)
    return WhatsAppChannelFactory(**defaults)


def _mock_client():
    return patch(MANAGEMENT_CLIENT_PATH, return_value=Mock(spec=BaseEvolutionClient))


def test_owner_can_remove_channel() -> None:
    client, _, workspace = _member_client(role=Member.Role.OWNER)
    channel = _channel(workspace)
    with _mock_client() as get_client:
        response = client.delete(_detail_url(workspace, channel))

    assert response.status_code == status.HTTP_204_NO_CONTENT
    assert response.content == b''
    assert not WhatsAppChannel.objects.filter(id=channel.id).exists()
    get_client.return_value.delete_instance.assert_called_once()


def test_admin_cannot_remove_channel_owner_only_policy() -> None:
    client, _, workspace = _member_client(role=Member.Role.ADMIN)
    channel = _channel(workspace)
    with _mock_client() as get_client:
        response = client.delete(_detail_url(workspace, channel))

    assert response.status_code == status.HTTP_403_FORBIDDEN
    assert WhatsAppChannel.objects.filter(id=channel.id).exists()
    get_client.return_value.delete_instance.assert_not_called()


def test_agent_cannot_remove_channel() -> None:
    client, _, workspace = _member_client(role=Member.Role.AGENT)
    channel = _channel(workspace)
    with _mock_client():
        response = client.delete(_detail_url(workspace, channel))

    assert response.status_code == status.HTTP_403_FORBIDDEN
    assert WhatsAppChannel.objects.filter(id=channel.id).exists()


def test_non_member_cannot_remove_channel() -> None:
    _, _, workspace = _member_client()
    channel = _channel(workspace)
    with _mock_client():
        response = _client_for(UserFactory()).delete(_detail_url(workspace, channel))

    assert response.status_code == status.HTTP_403_FORBIDDEN
    assert WhatsAppChannel.objects.filter(id=channel.id).exists()


def test_cross_tenant_channel_returns_404() -> None:
    client, _, workspace = _member_client(role=Member.Role.OWNER)
    other_channel = _channel(WorkspaceFactory())
    with _mock_client():
        response = client.delete(_detail_url(workspace, other_channel))

    assert response.status_code == status.HTTP_404_NOT_FOUND
    assert WhatsAppChannel.objects.filter(id=other_channel.id).exists()
    assert other_channel.instance_name not in response.content.decode()


def test_superuser_without_membership_can_remove() -> None:
    workspace = WorkspaceFactory()
    channel = _channel(workspace)
    superuser = UserFactory(is_staff=True, is_superuser=True)
    with _mock_client():
        response = _client_for(superuser).delete(_detail_url(workspace, channel))

    assert response.status_code == status.HTTP_204_NO_CONTENT
    assert not WhatsAppChannel.objects.filter(id=channel.id).exists()


def test_remove_orphans_conversation_and_cascades_webhook_events() -> None:
    client, _, workspace = _member_client(role=Member.Role.OWNER)
    channel = _channel(workspace)
    conversation = ConversationFactory(workspace=workspace, whatsapp_channel=channel)
    event = EvolutionWebhookEventFactory(whatsapp_channel=channel)

    with _mock_client():
        response = client.delete(_detail_url(workspace, channel))

    assert response.status_code == status.HTTP_204_NO_CONTENT
    conversation.refresh_from_db()
    assert conversation.whatsapp_channel_id is None
    assert Conversation.objects.filter(id=conversation.id).exists()
    assert not EvolutionWebhookEvent.objects.filter(id=event.id).exists()


def test_removing_again_returns_404() -> None:
    client, _, workspace = _member_client(role=Member.Role.OWNER)
    channel = _channel(workspace)
    with _mock_client():
        first = client.delete(_detail_url(workspace, channel))
        second = client.delete(_detail_url(workspace, channel))

    assert first.status_code == status.HTTP_204_NO_CONTENT
    assert second.status_code == status.HTTP_404_NOT_FOUND


def test_evolution_error_does_not_leave_channel_stuck_in_deleting() -> None:
    client, _, workspace = _member_client(role=Member.Role.OWNER)
    channel = _channel(workspace)
    failing = Mock(spec=BaseEvolutionClient)
    failing.delete_instance.side_effect = EvolutionUnavailableError('raw evolution body')

    with patch(MANAGEMENT_CLIENT_PATH, return_value=failing):
        response = client.delete(_detail_url(workspace, channel))

    # Remocao local best-effort: falha remota nao bloqueia nem prende em DELETING.
    assert response.status_code == status.HTTP_204_NO_CONTENT
    assert not WhatsAppChannel.objects.filter(id=channel.id).exists()
    assert 'raw evolution body' not in response.content.decode()


@pytest.mark.parametrize('method', ['put', 'patch'])
def test_detail_still_rejects_put_and_patch(method) -> None:
    client, _, workspace = _member_client(role=Member.Role.OWNER)
    channel = _channel(workspace)
    response = getattr(client, method)(_detail_url(workspace, channel), {}, format='json')
    assert response.status_code == status.HTTP_405_METHOD_NOT_ALLOWED
