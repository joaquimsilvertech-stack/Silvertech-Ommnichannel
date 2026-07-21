from __future__ import annotations

import pytest
from django.contrib import admin
from django.test import Client
from django.urls import reverse

from omnichannel.admin import ConversationAdmin, MessageAdmin, MessageInline
from omnichannel.factories import ConversationFactory, MessageFactory, WhatsAppChannelFactory
from omnichannel.models import Conversation, Message
from workspaces.factories import UserFactory, WorkspaceFactory

CONVERSATION_CHANGELIST_URL = reverse('admin:omnichannel_conversation_changelist')
MESSAGE_CHANGELIST_URL = reverse('admin:omnichannel_message_changelist')


@pytest.fixture
def superuser_client() -> Client:
    user = UserFactory(is_staff=True, is_superuser=True)
    client = Client()
    client.force_login(user)
    return client


@pytest.fixture
def conversation() -> Conversation:
    workspace = WorkspaceFactory()
    channel = WhatsAppChannelFactory(workspace=workspace, name='Canal principal')
    return ConversationFactory(workspace=workspace, whatsapp_channel=channel)


def _conversation_change_url(conversation: Conversation) -> str:
    return reverse('admin:omnichannel_conversation_change', args=[conversation.id])


def _message_change_url(message: Message) -> str:
    return reverse('admin:omnichannel_message_change', args=[message.id])


@pytest.mark.django_db
def test_conversation_changelist_shows_whatsapp_channel(superuser_client, conversation) -> None:
    content = superuser_client.get(CONVERSATION_CHANGELIST_URL).content.decode()

    assert 'Canal principal' in content


@pytest.mark.django_db
def test_legacy_conversation_without_channel_renders_safely(superuser_client) -> None:
    legacy = ConversationFactory(whatsapp_channel=None)

    changelist = superuser_client.get(CONVERSATION_CHANGELIST_URL)
    detail = superuser_client.get(_conversation_change_url(legacy))

    assert changelist.status_code == 200
    assert detail.status_code == 200
    assert 'Sem canal (legado)' in changelist.content.decode()


@pytest.mark.django_db
def test_conversation_tenant_and_channel_fields_are_readonly() -> None:
    model_admin = admin.site._registry[Conversation]

    assert isinstance(model_admin, ConversationAdmin)
    for field in ('workspace', 'contact', 'channel', 'whatsapp_channel'):
        assert field in model_admin.readonly_fields


@pytest.mark.django_db
def test_conversation_post_cannot_move_workspace_or_channel(superuser_client, conversation) -> None:
    other_workspace = WorkspaceFactory()
    other_channel = WhatsAppChannelFactory(workspace=other_workspace)
    other_contact = ConversationFactory(workspace=other_workspace).contact

    superuser_client.post(
        _conversation_change_url(conversation),
        data={
            'workspace': str(other_workspace.id),
            'contact': str(other_contact.id),
            'whatsapp_channel': str(other_channel.id),
            'channel': 'telegram',
            'status': Conversation.Status.OPEN,
            'messages-TOTAL_FORMS': '0',
            'messages-INITIAL_FORMS': '0',
            'messages-MIN_NUM_FORMS': '0',
            'messages-MAX_NUM_FORMS': '0',
        },
    )
    conversation.refresh_from_db()

    assert conversation.workspace_id != other_workspace.id
    assert conversation.whatsapp_channel_id != other_channel.id
    assert conversation.channel == 'whatsapp'


@pytest.mark.django_db
def test_message_inline_is_visible_and_read_only(superuser_client, conversation, rf) -> None:
    MessageFactory(conversation=conversation, body='Conteudo inline visivel')

    content = superuser_client.get(_conversation_change_url(conversation)).content.decode()

    assert 'Conteudo inline visivel' in content

    request = rf.get('/')
    request.user = UserFactory(is_staff=True, is_superuser=True)
    inline = MessageInline(Conversation, admin.site)

    assert inline.extra == 0
    assert inline.can_delete is False
    assert inline.has_add_permission(request, conversation) is False
    assert inline.has_change_permission(request, conversation) is False
    assert inline.has_delete_permission(request, conversation) is False
    for field in ('body', 'direction', 'status'):
        assert field in inline.readonly_fields


@pytest.mark.django_db
def test_message_admin_pages_are_accessible(superuser_client, conversation) -> None:
    message = MessageFactory(conversation=conversation, body='Corpo somente no detalhe')

    changelist = superuser_client.get(MESSAGE_CHANGELIST_URL)
    detail = superuser_client.get(_message_change_url(message))

    assert changelist.status_code == 200
    assert detail.status_code == 200
    assert 'Corpo somente no detalhe' in detail.content.decode()
    assert 'Corpo somente no detalhe' not in changelist.content.decode()


@pytest.mark.django_db
def test_message_changelist_identifies_workspace_and_channel(superuser_client, conversation) -> None:
    MessageFactory(conversation=conversation)

    content = superuser_client.get(MESSAGE_CHANGELIST_URL).content.decode()

    assert conversation.workspace.name in content
    assert 'Canal principal' in content


@pytest.mark.django_db
def test_message_changelist_shows_delivery_diagnostics(superuser_client, conversation) -> None:
    MessageFactory(
        conversation=conversation,
        direction=Message.Direction.OUTBOUND,
        status=Message.Status.FAILED,
        send_attempt_count=5,
        send_error_code='evolution_unavailable',
    )

    content = superuser_client.get(MESSAGE_CHANGELIST_URL).content.decode()

    assert 'evolution_unavailable' in content
    assert '>5<' in content


@pytest.mark.django_db
def test_message_admin_body_is_not_in_list_display() -> None:
    model_admin = admin.site._registry[Message]

    assert isinstance(model_admin, MessageAdmin)
    assert 'body' not in model_admin.list_display


@pytest.mark.django_db
def test_message_admin_permissions_are_view_only(rf) -> None:
    request = rf.get('/')
    request.user = UserFactory(is_staff=True, is_superuser=True)
    model_admin = admin.site._registry[Message]

    assert model_admin.has_view_permission(request) is True
    assert model_admin.has_add_permission(request) is False
    assert model_admin.has_change_permission(request) is False
    assert model_admin.has_delete_permission(request) is False


@pytest.mark.django_db
def test_message_add_and_delete_views_are_blocked(superuser_client, conversation) -> None:
    message = MessageFactory(conversation=conversation)

    add_response = superuser_client.get(reverse('admin:omnichannel_message_add'))
    delete_response = superuser_client.post(
        reverse('admin:omnichannel_message_delete', args=[message.id]),
        data={'post': 'yes'},
    )

    assert add_response.status_code == 403
    assert delete_response.status_code == 403
    assert Message.objects.filter(pk=message.pk).exists()


@pytest.mark.django_db
def test_message_change_post_does_not_modify_message(superuser_client, conversation) -> None:
    message = MessageFactory(
        conversation=conversation,
        body='Corpo original',
        direction=Message.Direction.INBOUND,
        status=Message.Status.DELIVERED,
    )

    response = superuser_client.post(
        _message_change_url(message),
        data={
            'body': 'Corpo adulterado',
            'direction': Message.Direction.OUTBOUND,
            'status': Message.Status.SENT,
        },
    )
    message.refresh_from_db()

    assert response.status_code in (302, 403)
    assert message.body == 'Corpo original'
    assert message.direction == Message.Direction.INBOUND
    assert message.status == Message.Status.DELIVERED
