from __future__ import annotations

from unittest.mock import patch

import pytest

from omnichannel.factories import (
    ConversationFactory,
    MessageFactory,
    WhatsAppChannelFactory,
)
from omnichannel.models import Conversation, Message, WhatsAppChannel
from omnichannel.outbound_routing import (
    OUTBOUND_CHANNEL_DELETING,
    OUTBOUND_CHANNEL_DISCONNECTED,
    OUTBOUND_CHANNEL_ERROR,
    OUTBOUND_CHANNEL_NOT_READY,
    OUTBOUND_CHANNEL_ROUTE_MISMATCH,
    OUTBOUND_CHANNEL_STATUS_INVALID,
    OUTBOUND_CHANNEL_WORKSPACE_MISMATCH,
    OUTBOUND_CONTACT_WORKSPACE_MISMATCH,
    OUTBOUND_CONVERSATION_CHANNEL_MISSING,
    OUTBOUND_INSTANCE_INVALID,
    OUTBOUND_MESSAGE_NOT_PENDING,
    OUTBOUND_MESSAGE_NOT_WHATSAPP,
    OUTBOUND_PROVIDER_UNSUPPORTED,
    OUTBOUND_RECIPIENT_INVALID,
    OUTBOUND_RECIPIENT_SELF,
    OutboundWhatsAppRoutingError,
    resolve_outbound_whatsapp_route,
)
from workspaces.factories import WorkspaceFactory

pytestmark = pytest.mark.django_db


def _message_with_route(
    *,
    channel_status: str = WhatsAppChannel.Status.CONNECTED,
    instance_name: str | None = None,
    recipient: str = '5511999999999',
) -> Message:
    channel_kwargs = {'status': channel_status}
    if instance_name is not None:
        channel_kwargs['instance_name'] = instance_name
    channel = WhatsAppChannelFactory(**channel_kwargs)
    conversation = ConversationFactory(
        workspace=channel.workspace,
        whatsapp_channel=channel,
        contact__phone=recipient,
    )
    return MessageFactory(
        conversation=conversation,
        direction=Message.Direction.OUTBOUND,
        status=Message.Status.PENDING,
        body='Conteudo privado outbound.',
    )


def _reload(message: Message) -> Message:
    return Message.objects.select_related(
        'conversation',
        'conversation__contact',
        'conversation__workspace',
        'conversation__whatsapp_channel',
    ).get(id=message.id)


def _assert_routing_error(
    message: Message,
    error_code: str,
    *,
    expected_channel_id=None,
    retryable: bool = False,
) -> OutboundWhatsAppRoutingError:
    with pytest.raises(OutboundWhatsAppRoutingError) as exc_info:
        resolve_outbound_whatsapp_route(
            message=message,
            expected_channel_id=expected_channel_id,
        )
    assert exc_info.value.error_code == error_code
    assert exc_info.value.retryable is retryable
    return exc_info.value


def test_resolves_pending_outbound_from_exact_conversation_channel_and_contact() -> None:
    message = _message_with_route(instance_name='channel-instance')

    route = resolve_outbound_whatsapp_route(message=message)

    assert route.message == message
    assert route.conversation == message.conversation
    assert route.channel == message.conversation.whatsapp_channel
    assert route.contact == message.conversation.contact
    assert route.recipient == '5511999999999'


def test_missing_conversation_channel_fails_closed() -> None:
    message = MessageFactory(
        conversation__whatsapp_channel=None,
        direction=Message.Direction.OUTBOUND,
        status=Message.Status.PENDING,
    )

    _assert_routing_error(message, OUTBOUND_CONVERSATION_CHANNEL_MISSING)


def test_matching_expected_channel_id_is_accepted() -> None:
    message = _message_with_route()

    route = resolve_outbound_whatsapp_route(
        message=message,
        expected_channel_id=str(message.conversation.whatsapp_channel_id),
    )

    assert route.channel.id == message.conversation.whatsapp_channel_id


def test_different_channel_from_same_workspace_is_rejected() -> None:
    message = _message_with_route()
    other = WhatsAppChannelFactory(
        workspace=message.conversation.workspace,
        status=WhatsAppChannel.Status.CONNECTED,
    )

    _assert_routing_error(
        message,
        OUTBOUND_CHANNEL_ROUTE_MISMATCH,
        expected_channel_id=other.id,
    )


def test_expected_channel_from_other_workspace_is_rejected_without_lookup_routing() -> None:
    message = _message_with_route()
    other = WhatsAppChannelFactory(status=WhatsAppChannel.Status.CONNECTED)

    _assert_routing_error(
        message,
        OUTBOUND_CHANNEL_ROUTE_MISMATCH,
        expected_channel_id=other.id,
    )


def test_channel_workspace_mismatch_is_rejected() -> None:
    message = _message_with_route()
    WhatsAppChannel.objects.filter(id=message.conversation.whatsapp_channel_id).update(
        workspace=WorkspaceFactory(),
    )

    _assert_routing_error(
        _reload(message),
        OUTBOUND_CHANNEL_WORKSPACE_MISMATCH,
    )


def test_contact_workspace_mismatch_is_rejected() -> None:
    message = _message_with_route()
    contact = message.conversation.contact
    contact.workspace = WorkspaceFactory()
    contact.save(update_fields=['workspace', 'updated_at'])

    _assert_routing_error(
        _reload(message),
        OUTBOUND_CONTACT_WORKSPACE_MISMATCH,
    )


def test_non_whatsapp_conversation_is_rejected() -> None:
    message = _message_with_route()
    Conversation.objects.filter(id=message.conversation_id).update(channel='email')

    _assert_routing_error(_reload(message), OUTBOUND_MESSAGE_NOT_WHATSAPP)


def test_non_pending_message_is_rejected() -> None:
    message = _message_with_route()
    message.status = Message.Status.SENT

    _assert_routing_error(message, OUTBOUND_MESSAGE_NOT_PENDING)


def test_unsupported_provider_is_rejected() -> None:
    message = _message_with_route()
    WhatsAppChannel.objects.filter(id=message.conversation.whatsapp_channel_id).update(
        provider='unsupported',
    )

    _assert_routing_error(_reload(message), OUTBOUND_PROVIDER_UNSUPPORTED)


@pytest.mark.parametrize('instance_name', ['', '   ', 'bad\ninstance'])
def test_invalid_instance_name_is_rejected(instance_name: str) -> None:
    message = _message_with_route()
    WhatsAppChannel.objects.filter(id=message.conversation.whatsapp_channel_id).update(
        instance_name=instance_name,
    )

    _assert_routing_error(_reload(message), OUTBOUND_INSTANCE_INVALID)


@pytest.mark.parametrize(
    'recipient',
    [
        '',
        '   ',
        '5511\n99999999',
        '5511999999999@lid',
        'cms3:opaque-recipient',
    ],
)
def test_invalid_recipient_is_rejected(recipient: str) -> None:
    message = _message_with_route()
    contact = message.conversation.contact
    contact.phone = recipient
    contact.save(update_fields=['phone', 'updated_at'])

    _assert_routing_error(_reload(message), OUTBOUND_RECIPIENT_INVALID)


def test_channel_phone_recipient_is_rejected() -> None:
    message = _message_with_route(recipient='+55 (11) 99999-9999')
    channel = message.conversation.whatsapp_channel
    channel.phone_number = '5511999999999'
    channel.save(update_fields=['phone_number', 'updated_at'])

    _assert_routing_error(_reload(message), OUTBOUND_RECIPIENT_SELF)


def test_connected_channel_is_sendable() -> None:
    message = _message_with_route(channel_status=WhatsAppChannel.Status.CONNECTED)

    assert resolve_outbound_whatsapp_route(message=message).channel.status == WhatsAppChannel.Status.CONNECTED


@pytest.mark.parametrize(
    'channel_status',
    [
        WhatsAppChannel.Status.PROVISIONING,
        WhatsAppChannel.Status.WAITING_QR,
        WhatsAppChannel.Status.CONNECTING,
        WhatsAppChannel.Status.RECONNECTING,
    ],
)
def test_transient_channel_status_is_retryable(channel_status: str) -> None:
    message = _message_with_route(channel_status=channel_status)

    _assert_routing_error(
        message,
        OUTBOUND_CHANNEL_NOT_READY,
        retryable=True,
    )


@pytest.mark.parametrize(
    ('channel_status', 'error_code'),
    [
        (WhatsAppChannel.Status.DISCONNECTED, OUTBOUND_CHANNEL_DISCONNECTED),
        (WhatsAppChannel.Status.ERROR, OUTBOUND_CHANNEL_ERROR),
        (WhatsAppChannel.Status.DELETING, OUTBOUND_CHANNEL_DELETING),
    ],
)
def test_permanent_channel_status_fails_without_retry(
    channel_status: str,
    error_code: str,
) -> None:
    message = _message_with_route(channel_status=channel_status)

    _assert_routing_error(message, error_code)


def test_unknown_channel_status_fails_closed() -> None:
    message = _message_with_route()
    WhatsAppChannel.objects.filter(id=message.conversation.whatsapp_channel_id).update(
        status='unknown',
    )

    _assert_routing_error(_reload(message), OUTBOUND_CHANNEL_STATUS_INVALID)


def test_resolver_never_calls_evolution_or_http() -> None:
    message = _message_with_route()

    with (
        patch('omnichannel.evolution.client.get_evolution_client') as client_factory,
        patch('requests.sessions.Session.request') as http_request,
    ):
        resolve_outbound_whatsapp_route(message=message)

    client_factory.assert_not_called()
    http_request.assert_not_called()


def test_routing_exception_does_not_contain_pii_instance_or_body() -> None:
    instance_name = 'private-channel-instance'
    phone = '5511888877777'
    message = _message_with_route(
        channel_status=WhatsAppChannel.Status.DISCONNECTED,
        instance_name=instance_name,
        recipient=phone,
    )

    error = _assert_routing_error(message, OUTBOUND_CHANNEL_DISCONNECTED)
    rendered = f'{error!s} {error!r}'

    assert phone not in rendered
    assert instance_name not in rendered
    assert message.body not in rendered
