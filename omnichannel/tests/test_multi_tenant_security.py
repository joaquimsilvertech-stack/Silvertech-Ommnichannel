from __future__ import annotations

import logging
from unittest.mock import patch

import pytest

from crm.models import Contact
from omnichannel.evolution import EvolutionAPIError
from omnichannel.factories import (
    ConversationFactory,
    MessageFactory,
    WhatsAppChannelFactory,
)
from omnichannel.models import (
    AIObservabilityEvent,
    AIProcessingRun,
    Conversation,
    Message,
    WhatsAppChannel,
)
from omnichannel.services import process_whatsapp_payload
from omnichannel.tasks import process_ai_response, send_outbound_whatsapp_message
from tests.security_helpers import (
    assert_not_found_or_forbidden,
    assert_response_does_not_contain,
    auth_client_for,
    make_user_with_membership,
)
from workspaces.factories import WorkspaceAIProviderConfigFactory, WorkspaceFactory
from workspaces.models import Member


def _payload() -> dict:
    return {
        'event': 'messages.upsert',
        'instance': 'silvertech_whatsapp',
        'data': {
            'key': {
                'id': 'evolution-message-id',
                'remoteJid': '5511999999999@s.whatsapp.net',
                'fromMe': False,
            },
            'message': {'conversation': 'Mensagem inbound secreta'},
        },
    }


@pytest.mark.django_db
def test_conversation_list_filters_and_search_do_not_cross_workspace() -> None:
    workspace_a = WorkspaceFactory()
    workspace_b = WorkspaceFactory()
    owner_a = make_user_with_membership(workspace_a, Member.Role.OWNER)
    conversation_a = ConversationFactory(workspace=workspace_a, contact__name='Contato A')
    conversation_b = ConversationFactory(
        workspace=workspace_b,
        contact__name='Contato B Secreto',
        contact__phone='5522999999999',
    )

    client = auth_client_for(owner_a)
    list_response = client.get('/api/omnichannel/conversations/', {'workspace': str(workspace_b.id)})
    search_response = client.get('/api/omnichannel/conversations/', {'search': 'Contato B Secreto'})

    assert list_response.status_code == 200
    assert search_response.status_code == 200
    assert str(conversation_a.id) not in list_response.content.decode('utf-8')
    assert str(conversation_b.id) not in list_response.content.decode('utf-8')
    assert_response_does_not_contain(search_response, ['Contato B Secreto', '5522999999999'])


@pytest.mark.django_db
def test_conversation_detail_messages_and_reply_other_workspace_are_blocked() -> None:
    workspace_a = WorkspaceFactory()
    workspace_b = WorkspaceFactory()
    owner_a = make_user_with_membership(workspace_a, Member.Role.OWNER)
    conversation_b = ConversationFactory(
        workspace=workspace_b,
        contact__name='Contato B',
        contact__phone='5522888888888',
    )
    MessageFactory(
        conversation=conversation_b,
        body='Body secreto workspace B',
        direction=Message.Direction.INBOUND,
    )
    client = auth_client_for(owner_a)

    detail_response = client.get(f'/api/omnichannel/conversations/{conversation_b.id}/')
    messages_response = client.get(f'/api/omnichannel/conversations/{conversation_b.id}/messages/')
    with patch('omnichannel.tasks.send_outbound_whatsapp_message.delay') as mock_send:
        reply_response = client.post(
            f'/api/omnichannel/conversations/{conversation_b.id}/reply/',
            {'body': 'Tentativa cross tenant'},
            format='json',
        )

    assert_not_found_or_forbidden(detail_response)
    assert_not_found_or_forbidden(messages_response)
    assert_not_found_or_forbidden(reply_response)
    mock_send.assert_not_called()
    assert_response_does_not_contain(messages_response, ['Body secreto workspace B', '5522888888888'])


@pytest.mark.django_db
def test_webhook_with_invalid_workspace_does_not_create_data() -> None:
    before_contacts = Contact.objects.count()
    before_conversations = Conversation.objects.count()
    before_messages = Message.objects.count()

    process_whatsapp_payload(_payload(), 'not-a-uuid')

    assert Contact.objects.count() == before_contacts
    assert Conversation.objects.count() == before_conversations
    assert Message.objects.count() == before_messages


@pytest.mark.django_db
def test_webhook_for_workspace_a_does_not_create_data_in_workspace_b() -> None:
    workspace_a = WorkspaceFactory()
    workspace_b = WorkspaceFactory()
    WorkspaceAIProviderConfigFactory(workspace=workspace_a, api_key='sk-webhook-a-key')

    with (
        patch('omnichannel.services.transaction.on_commit', side_effect=lambda callback: callback()),
        patch('omnichannel.tasks.process_ai_response.delay'),
        patch('omnichannel.signals.send_event'),
    ):
        process_whatsapp_payload(_payload(), str(workspace_a.id))

    assert Message.objects.filter(conversation__workspace=workspace_a).count() == 1
    assert Message.objects.filter(conversation__workspace=workspace_b).count() == 0


@pytest.mark.django_db
def test_process_ai_response_ignores_source_message_from_other_workspace(caplog) -> None:
    conversation_a = ConversationFactory()
    conversation_b = ConversationFactory()
    WorkspaceAIProviderConfigFactory(workspace=conversation_a.workspace, api_key='sk-provider-a-key')
    source_b = MessageFactory(
        conversation=conversation_b,
        direction=Message.Direction.INBOUND,
        body='Mensagem secreta B',
    )
    caplog.set_level(logging.INFO)

    with (
        patch('omnichannel.ai.registry.get_provider_adapter') as mock_adapter,
        patch('omnichannel.services.send_whatsapp_message') as mock_evolution,
    ):
        result = process_ai_response.run(str(conversation_a.id), source_message_id=str(source_b.id))

    assert result is None
    assert not AIProcessingRun.objects.exists()
    assert not Message.objects.filter(conversation=conversation_a, direction=Message.Direction.OUTBOUND).exists()
    mock_adapter.assert_not_called()
    mock_evolution.assert_not_called()
    assert 'Mensagem secreta B' not in caplog.text
    assert 'sk-provider-a-key' not in caplog.text


@pytest.mark.django_db
def test_process_ai_response_source_message_outbound_or_missing_is_ignored() -> None:
    conversation = ConversationFactory()
    WorkspaceAIProviderConfigFactory(workspace=conversation.workspace, api_key='sk-provider-key')
    outbound = MessageFactory(conversation=conversation, direction=Message.Direction.OUTBOUND)

    with (
        patch('omnichannel.ai.registry.get_provider_adapter') as mock_adapter,
        patch('omnichannel.services.send_whatsapp_message') as mock_evolution,
    ):
        outbound_result = process_ai_response.run(str(conversation.id), source_message_id=str(outbound.id))
        missing_result = process_ai_response.run(
            str(conversation.id),
            source_message_id='00000000-0000-0000-0000-000000000000',
        )

    assert outbound_result is None
    assert missing_result is None
    assert not AIProcessingRun.objects.exists()
    mock_adapter.assert_not_called()
    mock_evolution.assert_not_called()


@pytest.mark.django_db
def test_send_outbound_whatsapp_message_ignores_invalid_inbound_and_non_pending(caplog) -> None:
    inbound = MessageFactory(direction=Message.Direction.INBOUND, body='Inbound secreto')
    failed = MessageFactory(direction=Message.Direction.OUTBOUND, status=Message.Status.FAILED)
    caplog.set_level(logging.WARNING)

    with patch('omnichannel.services.send_whatsapp_message') as mock_send:
        missing_result = send_outbound_whatsapp_message.run('00000000-0000-0000-0000-000000000000')
        inbound_result = send_outbound_whatsapp_message.run(str(inbound.id))
        failed_result = send_outbound_whatsapp_message.run(str(failed.id))

    assert missing_result is None
    assert inbound_result is None
    assert failed_result is None
    mock_send.assert_not_called()
    assert 'Inbound secreto' not in caplog.text


@pytest.mark.django_db
def test_send_outbound_failure_logs_do_not_expose_body_or_phone(caplog) -> None:
    channel = WhatsAppChannelFactory(status=WhatsAppChannel.Status.CONNECTED)
    conversation = ConversationFactory(
        workspace=channel.workspace,
        whatsapp_channel=channel,
        contact__phone='5511777777777',
    )
    message = MessageFactory(
        conversation=conversation,
        direction=Message.Direction.OUTBOUND,
        status=Message.Status.PENDING,
        send_attempt_count=2,
        body='Mensagem outbound secreta',
    )
    caplog.set_level(logging.WARNING)

    with patch(
        'omnichannel.services.send_whatsapp_message',
        side_effect=EvolutionAPIError(),
    ):
        result = send_outbound_whatsapp_message.run(str(message.id))

    assert result == str(message.id)
    assert 'Mensagem outbound secreta' not in caplog.text
    assert '5511777777777' not in caplog.text
    assert 'Mensagem outbound secreta' not in str(
        list(AIObservabilityEvent.objects.values_list('metadata', flat=True)),
    )
