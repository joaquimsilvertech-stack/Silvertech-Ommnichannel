from __future__ import annotations

import logging
from unittest.mock import patch

import pytest
from django.test import override_settings

from automations.engine import FlowEngine
from automations.models import Flow
from omnichannel.factories import ConversationFactory, WhatsAppChannelFactory
from omnichannel.models import Message, WhatsAppChannel
from workspaces.factories import WorkspaceFactory


def _flow(*, workspace, text='Mensagem criada pelo flow.') -> Flow:
    return Flow.objects.create(
        workspace=workspace,
        name='Flow outbound',
        trigger={'type': 'new_message'},
        nodes=[
            {
                'id': 'send-1',
                'type': 'send_whatsapp',
                'config': {'text': text},
            },
        ],
    )


@pytest.mark.django_db
def test_send_whatsapp_node_creates_pending_message_and_schedules_after_commit(
    django_capture_on_commit_callbacks,
) -> None:
    channel = WhatsAppChannelFactory(status=WhatsAppChannel.Status.CONNECTED)
    conversation = ConversationFactory(
        workspace=channel.workspace,
        whatsapp_channel=channel,
        contact__phone='5511999999999',
    )
    flow = _flow(workspace=channel.workspace, text='Mensagem duravel do flow.')

    with (
        patch('omnichannel.services.send_whatsapp_message') as mock_send,
        patch('omnichannel.evolution.EvolutionAPIClient.send_text') as mock_send_text,
        patch('omnichannel.tasks.send_outbound_whatsapp_message.delay') as mock_delay,
    ):
        with django_capture_on_commit_callbacks(execute=False) as callbacks:
            FlowEngine().execute_flow(str(flow.id), str(conversation.id))
        mock_delay.assert_not_called()

        assert len(callbacks) == 1
        callbacks[0]()

    message = conversation.messages.get()
    assert message.conversation_id == conversation.id
    assert message.body == 'Mensagem duravel do flow.'
    assert message.direction == Message.Direction.OUTBOUND
    assert message.status == Message.Status.PENDING
    assert message.external_id is None
    assert message.send_error_code == ''
    assert list(conversation.messages.values_list('id', flat=True)) == [message.id]
    mock_send.assert_not_called()
    mock_send_text.assert_not_called()
    mock_delay.assert_called_once_with(str(message.id), str(channel.id))


@pytest.mark.django_db
@pytest.mark.parametrize('invalid_text', [None, '', '   ', 123, {}, []])
def test_send_whatsapp_node_with_invalid_text_creates_nothing(
    invalid_text,
    django_capture_on_commit_callbacks,
) -> None:
    conversation = ConversationFactory()
    flow = _flow(workspace=conversation.workspace, text=invalid_text)

    with (
        patch('omnichannel.tasks.send_outbound_whatsapp_message.delay') as mock_delay,
        django_capture_on_commit_callbacks(execute=False) as callbacks,
    ):
        FlowEngine().execute_flow(str(flow.id), str(conversation.id))

    assert not Message.objects.filter(conversation=conversation).exists()
    assert callbacks == []
    mock_delay.assert_not_called()


@pytest.mark.django_db
def test_handoff_blocks_flow_before_message_creation() -> None:
    conversation = ConversationFactory(is_human_handoff=True)
    flow = _flow(workspace=conversation.workspace)

    with patch('omnichannel.tasks.send_outbound_whatsapp_message.delay') as mock_delay:
        FlowEngine().execute_flow(str(flow.id), str(conversation.id))

    assert not Message.objects.filter(conversation=conversation).exists()
    mock_delay.assert_not_called()


@pytest.mark.django_db
def test_workspace_mismatch_blocks_flow_before_message_creation() -> None:
    conversation = ConversationFactory()
    flow = _flow(workspace=WorkspaceFactory())

    with patch('omnichannel.tasks.send_outbound_whatsapp_message.delay') as mock_delay:
        FlowEngine().execute_flow(str(flow.id), str(conversation.id))

    assert not Message.objects.filter(conversation=conversation).exists()
    mock_delay.assert_not_called()


@pytest.mark.django_db
@override_settings(EVOLUTION_INSTANCE_NAME='legacy-global-must-not-be-used')
def test_flow_without_channel_schedules_none_without_global_fallback(
    django_capture_on_commit_callbacks,
) -> None:
    conversation = ConversationFactory(
        whatsapp_channel=None,
        contact__phone='5511888888888',
    )
    flow = _flow(workspace=conversation.workspace)

    with (
        patch('omnichannel.tasks.send_outbound_whatsapp_message.delay') as mock_delay,
        patch('omnichannel.services.send_whatsapp_message') as mock_send,
    ):
        with django_capture_on_commit_callbacks(execute=False) as callbacks:
            FlowEngine().execute_flow(str(flow.id), str(conversation.id))
        assert len(callbacks) == 1
        callbacks[0]()

    message = conversation.messages.get()
    assert message.status == Message.Status.PENDING
    mock_send.assert_not_called()
    mock_delay.assert_called_once_with(str(message.id), None)
    assert 'legacy-global-must-not-be-used' not in str(mock_delay.call_args)


@pytest.mark.django_db
def test_flow_logs_exclude_body_phone_instance_and_credentials(
    django_capture_on_commit_callbacks,
    caplog,
) -> None:
    channel = WhatsAppChannelFactory(
        status=WhatsAppChannel.Status.CONNECTED,
        instance_name='private-flow-instance',
        instance_token='private-flow-token',
    )
    conversation = ConversationFactory(
        workspace=channel.workspace,
        whatsapp_channel=channel,
        contact__phone='5511777777777',
    )
    flow = _flow(workspace=channel.workspace, text='Private flow body')
    caplog.set_level(logging.INFO, logger='automations.engine')

    with django_capture_on_commit_callbacks(execute=False):
        FlowEngine().execute_flow(str(flow.id), str(conversation.id))

    rendered_logs = ' '.join(
        record.getMessage() + repr(record.__dict__)
        for record in caplog.records
    )
    assert 'Private flow body' not in rendered_logs
    assert '5511777777777' not in rendered_logs
    assert 'private-flow-instance' not in rendered_logs
    assert 'private-flow-token' not in rendered_logs
