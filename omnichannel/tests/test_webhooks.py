from __future__ import annotations

import logging
from unittest.mock import patch

import pytest
from rest_framework import status
from rest_framework.test import APIClient

from automations.models import Flow
from omnichannel.factories import ContactFactory
from omnichannel.models import Conversation, Message
from omnichannel.services import process_whatsapp_payload
from workspaces.factories import WorkspaceAIProviderConfigFactory
from workspaces.models import AIProvider
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
        is_human_handoff=False,
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

    with (
        patch(
            'omnichannel.views.process_whatsapp_webhook_task.delay',
            side_effect=run_webhook_task,
        ),
        patch('omnichannel.signals.send_event'),
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


def _payload(
    *,
    remote_jid: str = '5511999999999@s.whatsapp.net',
    from_me: bool = False,
    text: str | None = 'Mensagem inbound para IA',
    message: dict | None = None,
    message_type: str | None = None,
) -> dict:
    payload_message = message if message is not None else {'conversation': text}
    payload = {
        'event': 'messages.upsert',
        'instance': 'silvertech_whatsapp',
        'data': {
            'key': {
                'id': 'evolution-message-id',
                'remoteJid': remote_jid,
                'fromMe': from_me,
            },
            'message': payload_message,
        },
    }
    if message_type:
        payload['data']['messageType'] = message_type
    return payload


def _run_webhook_inline(payload_arg, workspace_id_arg):
    process_whatsapp_payload(payload_arg, workspace_id_arg)


@pytest.mark.django_db
def test_valid_inbound_webhook_schedules_ai_after_commit(
    api_client: APIClient,
    tenant_workspace: Workspace,
) -> None:
    WorkspaceAIProviderConfigFactory(workspace=tenant_workspace, api_key='sk-webhook-ai-key')

    with (
        patch('omnichannel.views.process_whatsapp_webhook_task.delay', side_effect=_run_webhook_inline),
        patch('omnichannel.services.transaction.on_commit', side_effect=lambda callback: callback()),
        patch('omnichannel.tasks.process_ai_response.delay') as mock_ai_delay,
        patch('omnichannel.signals.send_event'),
    ):
        response = api_client.post(
            f'/api/omnichannel/webhooks/whatsapp/?workspace={tenant_workspace.id}',
            _payload(),
            format='json',
        )

    assert response.status_code == status.HTTP_200_OK
    inbound = Message.objects.get(
        conversation__workspace=tenant_workspace,
        direction=Message.Direction.INBOUND,
        body='Mensagem inbound para IA',
    )
    mock_ai_delay.assert_called_once_with(
        conversation_id=str(inbound.conversation_id),
        source_message_id=str(inbound.id),
    )


@pytest.mark.django_db
def test_ai_schedule_uses_transaction_on_commit(tenant_workspace: Workspace) -> None:
    WorkspaceAIProviderConfigFactory(workspace=tenant_workspace, api_key='sk-on-commit-key')
    callbacks = []

    with (
        patch('omnichannel.services.transaction.on_commit', side_effect=callbacks.append) as mock_on_commit,
        patch('omnichannel.tasks.process_ai_response.delay') as mock_ai_delay,
        patch('omnichannel.signals.send_event'),
    ):
        process_whatsapp_payload(_payload(), str(tenant_workspace.id))

        mock_on_commit.assert_called_once()
        mock_ai_delay.assert_not_called()

        callbacks[0]()

        inbound = Message.objects.get(conversation__workspace=tenant_workspace)
        mock_ai_delay.assert_called_once_with(
            conversation_id=str(inbound.conversation_id),
            source_message_id=str(inbound.id),
        )


@pytest.mark.django_db
@pytest.mark.parametrize(
    'payload',
    [
        _payload(from_me=True),
        _payload(remote_jid='120363000000000000@g.us'),
        _payload(text=''),
        _payload(message={'imageMessage': {'url': 'https://example.test/image.jpg'}}, message_type='imageMessage'),
    ],
)
def test_webhook_does_not_schedule_ai_for_non_processable_events(
    payload: dict,
    tenant_workspace: Workspace,
) -> None:
    WorkspaceAIProviderConfigFactory(workspace=tenant_workspace, api_key='sk-skip-events-key')

    with (
        patch('omnichannel.tasks.process_ai_response.delay') as mock_ai_delay,
        patch('omnichannel.signals.send_event'),
    ):
        process_whatsapp_payload(payload, str(tenant_workspace.id))

    mock_ai_delay.assert_not_called()


@pytest.mark.django_db
def test_webhook_does_not_schedule_ai_for_handoff_conversation(tenant_workspace: Workspace) -> None:
    contact = ContactFactory(
        workspace=tenant_workspace,
        phone='5511999999999',
        channel_id='5511999999999',
    )
    Conversation.objects.create(
        workspace=tenant_workspace,
        contact=contact,
        channel='whatsapp',
        status=Conversation.Status.OPEN,
        is_human_handoff=True,
    )
    WorkspaceAIProviderConfigFactory(workspace=tenant_workspace, api_key='sk-handoff-webhook-key')

    with (
        patch('omnichannel.tasks.process_ai_response.delay') as mock_ai_delay,
        patch('omnichannel.signals.send_event'),
    ):
        process_whatsapp_payload(_payload(), str(tenant_workspace.id))

    mock_ai_delay.assert_not_called()


@pytest.mark.django_db
def test_webhook_does_not_schedule_ai_without_active_provider(tenant_workspace: Workspace) -> None:
    WorkspaceAIProviderConfigFactory(
        workspace=tenant_workspace,
        api_key='sk-inactive-webhook-key',
        is_active=False,
    )

    with (
        patch('omnichannel.tasks.process_ai_response.delay') as mock_ai_delay,
        patch('omnichannel.signals.send_event'),
    ):
        process_whatsapp_payload(_payload(), str(tenant_workspace.id))

    mock_ai_delay.assert_not_called()


@pytest.mark.django_db
def test_webhook_does_not_schedule_ai_for_unsupported_provider(tenant_workspace: Workspace) -> None:
    WorkspaceAIProviderConfigFactory(
        workspace=tenant_workspace,
        provider=AIProvider.ANTHROPIC,
        api_key='sk-unsupported-webhook-key',
    )

    with (
        patch('omnichannel.tasks.process_ai_response.delay') as mock_ai_delay,
        patch('omnichannel.signals.send_event'),
    ):
        process_whatsapp_payload(_payload(), str(tenant_workspace.id))

    mock_ai_delay.assert_not_called()


@pytest.mark.django_db
def test_webhook_does_not_schedule_ai_without_api_key(tenant_workspace: Workspace) -> None:
    WorkspaceAIProviderConfigFactory(workspace=tenant_workspace, api_key='')

    with (
        patch('omnichannel.tasks.process_ai_response.delay') as mock_ai_delay,
        patch('omnichannel.signals.send_event'),
    ):
        process_whatsapp_payload(_payload(), str(tenant_workspace.id))

    mock_ai_delay.assert_not_called()


@pytest.mark.django_db
def test_ai_schedule_failure_does_not_break_webhook_response(
    api_client: APIClient,
    tenant_workspace: Workspace,
    caplog,
) -> None:
    WorkspaceAIProviderConfigFactory(workspace=tenant_workspace, api_key='sk-schedule-failure-key')
    caplog.set_level(logging.ERROR)

    with (
        patch('omnichannel.views.process_whatsapp_webhook_task.delay', side_effect=_run_webhook_inline),
        patch('omnichannel.services.transaction.on_commit', side_effect=lambda callback: callback()),
        patch('omnichannel.tasks.process_ai_response.delay', side_effect=RuntimeError('broker down')),
        patch('omnichannel.signals.send_event'),
    ):
        response = api_client.post(
            f'/api/omnichannel/webhooks/whatsapp/?workspace={tenant_workspace.id}',
            _payload(),
            format='json',
        )

    assert response.status_code == status.HTTP_200_OK
    assert 'sk-schedule-failure-key' not in caplog.text
    assert 'Mensagem inbound para IA' not in caplog.text


@pytest.mark.django_db
def test_webhook_does_not_call_openai_evolution_or_create_outbound(
    api_client: APIClient,
    tenant_workspace: Workspace,
) -> None:
    WorkspaceAIProviderConfigFactory(workspace=tenant_workspace, api_key='sk-no-runtime-call-key')

    with (
        patch('omnichannel.views.process_whatsapp_webhook_task.delay', side_effect=_run_webhook_inline),
        patch('omnichannel.services.transaction.on_commit', side_effect=lambda callback: callback()),
        patch('omnichannel.tasks.process_ai_response.delay') as mock_ai_delay,
        patch('omnichannel.ai.providers.openai.openai.OpenAI') as mock_openai,
        patch('omnichannel.services.send_whatsapp_message') as mock_evolution,
        patch('omnichannel.signals.send_event'),
    ):
        response = api_client.post(
            f'/api/omnichannel/webhooks/whatsapp/?workspace={tenant_workspace.id}',
            _payload(),
            format='json',
        )

    assert response.status_code == status.HTTP_200_OK
    mock_ai_delay.assert_called_once()
    mock_openai.assert_not_called()
    mock_evolution.assert_not_called()
    assert not Message.objects.filter(
        conversation__workspace=tenant_workspace,
        direction=Message.Direction.OUTBOUND,
    ).exists()
