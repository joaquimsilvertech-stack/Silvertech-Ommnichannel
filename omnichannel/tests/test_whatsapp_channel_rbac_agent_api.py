"""
Nao-regressao do requisito de RBAC: AGENT trabalha em conversas/reply, mas nao
tem nenhuma capability sobre canais (list/qr/restart/disconnect/remove).
"""
from __future__ import annotations

from unittest.mock import Mock, patch

import pytest
from rest_framework import status

from omnichannel.evolution import BaseEvolutionClient
from omnichannel.factories import ConversationFactory, WhatsAppChannelFactory
from omnichannel.models import Message, WhatsAppChannel
from tests.security_helpers import auth_client_for, make_user_with_membership
from workspaces.factories import WorkspaceFactory
from workspaces.models import Member

pytestmark = pytest.mark.django_db

MANAGEMENT_CLIENT_PATH = 'omnichannel.whatsapp_channel_management.get_evolution_client'


def _base(workspace, channel) -> str:
    return f'/api/workspaces/{workspace.id}/whatsapp-channels/{channel.id}/'


def test_agent_can_list_conversations() -> None:
    workspace = WorkspaceFactory()
    agent = make_user_with_membership(workspace, Member.Role.AGENT)
    ConversationFactory(workspace=workspace)

    response = auth_client_for(agent).get('/api/omnichannel/conversations/')

    assert response.status_code == status.HTTP_200_OK


def test_agent_can_reply_in_own_workspace() -> None:
    channel = WhatsAppChannelFactory(status=WhatsAppChannel.Status.CONNECTED)
    conversation = ConversationFactory(
        workspace=channel.workspace,
        whatsapp_channel=channel,
        contact__phone='5511999990000',
    )
    agent = make_user_with_membership(channel.workspace, Member.Role.AGENT)

    with patch('omnichannel.tasks.send_outbound_whatsapp_message.delay'):
        response = auth_client_for(agent).post(
            f'/api/omnichannel/conversations/{conversation.id}/reply/',
            {'body': 'Resposta do agente.'},
            format='json',
        )

    assert response.status_code == status.HTTP_201_CREATED
    assert Message.objects.filter(id=response.data['id']).exists()


def test_agent_is_forbidden_on_every_channel_capability() -> None:
    workspace = WorkspaceFactory()
    channel = WhatsAppChannelFactory(
        workspace=workspace,
        status=WhatsAppChannel.Status.CONNECTED,
    )
    agent = make_user_with_membership(workspace, Member.Role.AGENT)
    client = auth_client_for(agent)
    base = _base(workspace, channel)

    with patch(MANAGEMENT_CLIENT_PATH, return_value=Mock(spec=BaseEvolutionClient)):
        results = {
            'list': client.get(f'/api/workspaces/{workspace.id}/whatsapp-channels/'),
            'detail': client.get(base),
            'status': client.get(f'{base}status/'),
            'qr': client.get(f'{base}qr/'),
            'restart': client.post(f'{base}restart/'),
            'disconnect': client.post(f'{base}disconnect/'),
            'remove': client.delete(base),
        }

    for name, response in results.items():
        assert response.status_code == status.HTTP_403_FORBIDDEN, name

    channel.refresh_from_db()
    assert channel.status == WhatsAppChannel.Status.CONNECTED
    assert WhatsAppChannel.objects.filter(id=channel.id).exists()
