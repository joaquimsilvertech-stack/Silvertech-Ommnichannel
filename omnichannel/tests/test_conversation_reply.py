from __future__ import annotations

import logging
from unittest.mock import patch

import pytest
from django.test import override_settings
from rest_framework import status

from omnichannel.factories import (
    ContactFactory,
    ConversationFactory,
    WhatsAppChannelFactory,
)
from omnichannel.models import Message, WhatsAppChannel
from tests.security_helpers import auth_client_for, make_user_with_membership
from workspaces.factories import WorkspaceFactory
from workspaces.models import Member


def _reply_url(conversation_id) -> str:
    return f'/api/omnichannel/conversations/{conversation_id}/reply/'


@pytest.mark.django_db
def test_reply_creates_pending_message_and_schedules_delivery_only_after_commit(
    django_capture_on_commit_callbacks,
) -> None:
    channel = WhatsAppChannelFactory(status=WhatsAppChannel.Status.CONNECTED)
    conversation = ConversationFactory(
        workspace=channel.workspace,
        whatsapp_channel=channel,
        contact__phone='5511999999999',
    )
    owner = make_user_with_membership(channel.workspace, Member.Role.OWNER)

    with (
        patch('omnichannel.services.send_whatsapp_message') as mock_send,
        patch('omnichannel.evolution.EvolutionAPIClient.send_text') as mock_send_text,
        patch('omnichannel.tasks.send_outbound_whatsapp_message.delay') as mock_delay,
    ):
        with django_capture_on_commit_callbacks(execute=False) as callbacks:
            response = auth_client_for(owner).post(
                _reply_url(conversation.id),
                {'body': 'Resposta manual duravel.'},
                format='json',
            )
        mock_delay.assert_not_called()

        assert len(callbacks) == 1
        callbacks[0]()
        mock_delay.assert_called_once_with(str(response.data['id']), str(channel.id))

    assert response.status_code == status.HTTP_201_CREATED
    message = Message.objects.get(id=response.data['id'])
    assert message.conversation_id == conversation.id
    assert message.body == 'Resposta manual duravel.'
    assert message.direction == Message.Direction.OUTBOUND
    assert message.status == Message.Status.PENDING
    assert message.external_id is None
    assert message.send_error_code == ''
    assert Message.objects.filter(conversation=conversation).count() == 1
    mock_send.assert_not_called()
    mock_send_text.assert_not_called()


@pytest.mark.django_db
@pytest.mark.parametrize('payload', [{}, {'body': ''}, {'body': '   '}, {'body': None}])
def test_reply_rejects_invalid_body_without_creating_message(payload: dict) -> None:
    conversation = ConversationFactory()
    owner = make_user_with_membership(conversation.workspace, Member.Role.OWNER)

    with patch('omnichannel.tasks.send_outbound_whatsapp_message.delay') as mock_delay:
        response = auth_client_for(owner).post(
            _reply_url(conversation.id),
            payload,
            format='json',
        )

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert not Message.objects.filter(conversation=conversation).exists()
    mock_delay.assert_not_called()


@pytest.mark.django_db
def test_reply_cannot_access_conversation_from_another_workspace() -> None:
    own_workspace = WorkspaceFactory()
    other_conversation = ConversationFactory()
    owner = make_user_with_membership(own_workspace, Member.Role.OWNER)

    with patch('omnichannel.tasks.send_outbound_whatsapp_message.delay') as mock_delay:
        response = auth_client_for(owner).post(
            _reply_url(other_conversation.id),
            {'body': 'Tentativa entre tenants.'},
            format='json',
        )

    assert response.status_code in {status.HTTP_403_FORBIDDEN, status.HTTP_404_NOT_FOUND}
    assert not Message.objects.filter(conversation=other_conversation).exists()
    mock_delay.assert_not_called()


@pytest.mark.django_db
def test_reply_with_contact_from_another_workspace_never_sends_in_request(
    django_capture_on_commit_callbacks,
) -> None:
    workspace = WorkspaceFactory()
    foreign_contact = ContactFactory(
        workspace=WorkspaceFactory(),
        name='Contato inconsistente',
        phone='5511888888888',
        channel_id='inconsistent-contact',
    )
    conversation = ConversationFactory(
        workspace=workspace,
        contact=foreign_contact,
    )
    owner = make_user_with_membership(workspace, Member.Role.OWNER)

    with (
        patch('omnichannel.tasks.send_outbound_whatsapp_message.delay') as mock_delay,
        patch('omnichannel.services.send_whatsapp_message') as mock_send,
        patch('omnichannel.evolution.EvolutionAPIClient.send_text') as mock_send_text,
        django_capture_on_commit_callbacks(execute=False) as callbacks,
    ):
        response = auth_client_for(owner).post(
            _reply_url(conversation.id),
            {'body': 'Persistir para validacao central.'},
            format='json',
        )

    assert response.status_code == status.HTTP_409_CONFLICT
    assert response.data == {
        'detail': 'Destinatário WhatsApp não resolvido.',
        'error_code': 'recipient_unresolved',
    }
    assert not Message.objects.filter(conversation=conversation).exists()
    assert callbacks == []
    mock_delay.assert_not_called()
    mock_send.assert_not_called()
    mock_send_text.assert_not_called()


@pytest.mark.django_db
@pytest.mark.parametrize(
    'recipient',
    [
        '',
        '5511999999999@lid',
        'cms3:opaque-recipient',
    ],
)
def test_reply_blocks_unresolved_recipient_before_persisting_or_scheduling(
    recipient: str,
    django_capture_on_commit_callbacks,
) -> None:
    channel = WhatsAppChannelFactory(status=WhatsAppChannel.Status.CONNECTED)
    conversation = ConversationFactory(
        workspace=channel.workspace,
        whatsapp_channel=channel,
        contact__phone=recipient,
    )
    owner = make_user_with_membership(channel.workspace, Member.Role.OWNER)

    with (
        patch('omnichannel.tasks.send_outbound_whatsapp_message.delay') as mock_delay,
        patch('omnichannel.services.send_whatsapp_message') as mock_send,
        django_capture_on_commit_callbacks(execute=False) as callbacks,
    ):
        response = auth_client_for(owner).post(
            _reply_url(conversation.id),
            {'body': 'Não deve ser persistida.'},
            format='json',
        )

    assert response.status_code == status.HTTP_409_CONFLICT
    assert response.data == {
        'detail': 'Destinatário WhatsApp não resolvido.',
        'error_code': 'recipient_unresolved',
    }
    assert not Message.objects.filter(conversation=conversation).exists()
    assert callbacks == []
    mock_delay.assert_not_called()
    mock_send.assert_not_called()


@pytest.mark.django_db
def test_reply_blocks_channel_phone_before_persisting_or_scheduling(
    django_capture_on_commit_callbacks,
) -> None:
    channel = WhatsAppChannelFactory(
        status=WhatsAppChannel.Status.CONNECTED,
        phone_number='5511988887777',
    )
    conversation = ConversationFactory(
        workspace=channel.workspace,
        whatsapp_channel=channel,
        contact__phone='+55 (11) 98888-7777',
    )
    owner = make_user_with_membership(channel.workspace, Member.Role.OWNER)

    with (
        patch('omnichannel.tasks.send_outbound_whatsapp_message.delay') as mock_delay,
        patch('omnichannel.services.send_whatsapp_message') as mock_send,
        django_capture_on_commit_callbacks(execute=False) as callbacks,
    ):
        response = auth_client_for(owner).post(
            _reply_url(conversation.id),
            {'body': 'Não deve retornar à própria linha.'},
            format='json',
        )

    assert response.status_code == status.HTTP_409_CONFLICT
    assert response.data == {
        'detail': 'O destinatário corresponde à própria linha WhatsApp.',
        'error_code': 'recipient_is_channel_phone',
    }
    assert not Message.objects.filter(conversation=conversation).exists()
    assert callbacks == []
    mock_delay.assert_not_called()
    mock_send.assert_not_called()


@pytest.mark.django_db
@override_settings(EVOLUTION_INSTANCE_NAME='legacy-global-must-not-be-used')
def test_reply_without_channel_schedules_none_without_global_fallback(
    django_capture_on_commit_callbacks,
) -> None:
    conversation = ConversationFactory(
        whatsapp_channel=None,
        contact__phone='5511777777777',
    )
    owner = make_user_with_membership(conversation.workspace, Member.Role.OWNER)

    with (
        patch('omnichannel.tasks.send_outbound_whatsapp_message.delay') as mock_delay,
        patch('omnichannel.services.send_whatsapp_message') as mock_send,
    ):
        with django_capture_on_commit_callbacks(execute=False) as callbacks:
            response = auth_client_for(owner).post(
                _reply_url(conversation.id),
                {'body': 'Sem canal persistido.'},
                format='json',
            )
        assert len(callbacks) == 1
        callbacks[0]()
        mock_delay.assert_called_once_with(str(response.data['id']), None)

    assert response.status_code == status.HTTP_201_CREATED
    message = Message.objects.get(id=response.data['id'])
    assert message.status == Message.Status.PENDING
    assert message.external_id is None
    mock_send.assert_not_called()
    assert 'legacy-global-must-not-be-used' not in str(mock_delay.call_args)


@pytest.mark.django_db
def test_reply_enqueue_failure_does_not_expose_sensitive_values(
    django_capture_on_commit_callbacks,
    caplog,
) -> None:
    channel = WhatsAppChannelFactory(
        status=WhatsAppChannel.Status.CONNECTED,
        instance_name='private-instance-name',
        instance_token='private-instance-token',
    )
    conversation = ConversationFactory(
        workspace=channel.workspace,
        whatsapp_channel=channel,
        contact__phone='5511666666666',
    )
    owner = make_user_with_membership(channel.workspace, Member.Role.OWNER)
    caplog.set_level(logging.WARNING, logger='omnichannel.services')

    with (
        patch(
            'omnichannel.tasks.send_outbound_whatsapp_message.delay',
            side_effect=RuntimeError('private-instance-token 5511666666666'),
        ),
        django_capture_on_commit_callbacks(execute=True),
    ):
        response = auth_client_for(owner).post(
            _reply_url(conversation.id),
            {'body': 'Corpo privado da resposta.'},
            format='json',
        )

    assert response.status_code == status.HTTP_201_CREATED
    assert Message.objects.get(id=response.data['id']).status == Message.Status.PENDING
    rendered_logs = ' '.join(
        record.getMessage() + repr(record.__dict__)
        for record in caplog.records
    )
    assert 'Corpo privado da resposta.' not in rendered_logs
    assert '5511666666666' not in rendered_logs
    assert 'private-instance-name' not in rendered_logs
    assert 'private-instance-token' not in rendered_logs
