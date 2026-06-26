from __future__ import annotations

from unittest.mock import patch

import pytest
from rest_framework import status
from rest_framework.test import APIClient

from automations.models import Flow
from omnichannel.factories import ContactFactory
from omnichannel.models import Conversation, Message
from omnichannel.services import process_whatsapp_payload
from workspaces.models import Workspace


@pytest.mark.django_db
@patch('automations.tasks.execute_flow_task.delay')
def test_evolution_webhook_creates_inbound_message_and_triggers_flow(
    mock_execute_flow,
    api_client: APIClient,
    tenant_workspace: Workspace,
) -> None:
    contact = ContactFactory(
        workspace=tenant_workspace,
        phone='5511999999999',
        channel_id='5511999999999',
    )
    conversation = Conversation.objects.create(
        workspace=tenant_workspace,
        contact=contact,
        channel='whatsapp',
        status=Conversation.Status.OPEN,
    )
    flow = Flow.objects.create(
        workspace=tenant_workspace,
        name='Fluxo nova mensagem',
        trigger={'type': 'new_message'},
        nodes=[],
        is_active=True,
    )
    payload = {
        'event': 'messages.upsert',
        'instance': 'silvertech_whatsapp',
        'data': {
            'key': {
                'remoteJid': '5511999999999@s.whatsapp.net',
                'fromMe': False,
            },
            'message': {'conversation': 'Mensagem de teste do webhook'},
        },
    }

    def run_webhook_task(payload_arg, workspace_id_arg):
        process_whatsapp_payload(payload_arg, workspace_id_arg)

    with patch(
        'omnichannel.views.process_whatsapp_webhook_task.delay',
        side_effect=run_webhook_task,
    ):
        response = api_client.post(
            f'/api/omnichannel/webhooks/whatsapp/?workspace={tenant_workspace.id}',
            payload,
            format='json',
        )

    assert response.status_code == status.HTTP_200_OK
    assert Message.objects.filter(
        conversation=conversation,
        direction=Message.Direction.INBOUND,
        body='Mensagem de teste do webhook',
    ).exists()
    mock_execute_flow.assert_called_once_with(str(flow.id), str(conversation.id))
