from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from uuid import UUID

from django.core.exceptions import ObjectDoesNotExist

from crm.models import Contact
from omnichannel.evolution.types import MAX_INSTANCE_NAME_LENGTH
from omnichannel.models import Conversation, Message, WhatsAppChannel
from omnichannel.whatsapp_recipient_validation import (
    OUTBOUND_RECIPIENT_SELF,
    OUTBOUND_RECIPIENT_UNRESOLVED,
    validate_whatsapp_recipient,
)

WHATSAPP_CONVERSATION_CHANNEL = 'whatsapp'

OUTBOUND_MESSAGE_NOT_FOUND = 'OUTBOUND_MESSAGE_NOT_FOUND'
OUTBOUND_MESSAGE_NOT_OUTBOUND = 'OUTBOUND_MESSAGE_NOT_OUTBOUND'
OUTBOUND_MESSAGE_NOT_PENDING = 'OUTBOUND_MESSAGE_NOT_PENDING'
OUTBOUND_MESSAGE_NOT_WHATSAPP = 'OUTBOUND_MESSAGE_NOT_WHATSAPP'
OUTBOUND_CONVERSATION_CHANNEL_MISSING = 'OUTBOUND_CONVERSATION_CHANNEL_MISSING'
OUTBOUND_CHANNEL_ROUTE_MISMATCH = 'OUTBOUND_CHANNEL_ROUTE_MISMATCH'
OUTBOUND_CHANNEL_WORKSPACE_MISMATCH = 'OUTBOUND_CHANNEL_WORKSPACE_MISMATCH'
OUTBOUND_CONTACT_WORKSPACE_MISMATCH = 'OUTBOUND_CONTACT_WORKSPACE_MISMATCH'
OUTBOUND_RECIPIENT_INVALID = OUTBOUND_RECIPIENT_UNRESOLVED
OUTBOUND_PROVIDER_UNSUPPORTED = 'OUTBOUND_PROVIDER_UNSUPPORTED'
OUTBOUND_INSTANCE_INVALID = 'OUTBOUND_INSTANCE_INVALID'
OUTBOUND_CHANNEL_NOT_READY = 'OUTBOUND_CHANNEL_NOT_READY'
OUTBOUND_CHANNEL_DISCONNECTED = 'OUTBOUND_CHANNEL_DISCONNECTED'
OUTBOUND_CHANNEL_ERROR = 'OUTBOUND_CHANNEL_ERROR'
OUTBOUND_CHANNEL_DELETING = 'OUTBOUND_CHANNEL_DELETING'
OUTBOUND_CHANNEL_STATUS_INVALID = 'OUTBOUND_CHANNEL_STATUS_INVALID'

_TRANSIENT_CHANNEL_STATUSES = {
    WhatsAppChannel.Status.PROVISIONING,
    WhatsAppChannel.Status.WAITING_QR,
    WhatsAppChannel.Status.CONNECTING,
    WhatsAppChannel.Status.RECONNECTING,
}
_PERMANENT_CHANNEL_ERROR_CODES = {
    WhatsAppChannel.Status.DISCONNECTED: OUTBOUND_CHANNEL_DISCONNECTED,
    WhatsAppChannel.Status.ERROR: OUTBOUND_CHANNEL_ERROR,
    WhatsAppChannel.Status.DELETING: OUTBOUND_CHANNEL_DELETING,
}


@dataclass(frozen=True)
class OutboundWhatsAppRoute:
    message: Message
    conversation: Conversation
    contact: Contact
    channel: WhatsAppChannel
    recipient: str


class OutboundWhatsAppRoutingError(Exception):
    """Falha de roteamento sem PII, credenciais ou identificadores externos."""

    def __init__(
        self,
        error_code: str,
        *,
        retryable: bool = False,
    ) -> None:
        super().__init__('Outbound WhatsApp routing failed.')
        self.error_code = _sanitize_error_code(error_code)
        self.retryable = bool(retryable)


def resolve_outbound_whatsapp_route(
    *,
    message: Message,
    expected_channel_id: UUID | str | None = None,
) -> OutboundWhatsAppRoute:
    """Resolve exclusivamente Message -> Conversation -> WhatsAppChannel."""
    if not isinstance(message, Message) or not message.pk or message._state.adding:
        _fail(OUTBOUND_MESSAGE_NOT_FOUND)

    if message.direction != Message.Direction.OUTBOUND:
        _fail(OUTBOUND_MESSAGE_NOT_OUTBOUND)
    if message.status != Message.Status.PENDING:
        _fail(OUTBOUND_MESSAGE_NOT_PENDING)

    try:
        conversation = message.conversation
    except ObjectDoesNotExist:
        _fail(OUTBOUND_MESSAGE_NOT_FOUND)
    if message.conversation_id != conversation.id:
        _fail(OUTBOUND_MESSAGE_NOT_FOUND)
    if conversation.channel != WHATSAPP_CONVERSATION_CHANNEL:
        _fail(OUTBOUND_MESSAGE_NOT_WHATSAPP)
    if conversation.whatsapp_channel_id is None:
        _fail(OUTBOUND_CONVERSATION_CHANNEL_MISSING)

    actual_channel_id = conversation.whatsapp_channel_id
    if expected_channel_id is not None and not _same_uuid(
        expected_channel_id,
        actual_channel_id,
    ):
        _fail(OUTBOUND_CHANNEL_ROUTE_MISMATCH)

    try:
        channel = conversation.whatsapp_channel
    except ObjectDoesNotExist:
        _fail(OUTBOUND_CONVERSATION_CHANNEL_MISSING)
    if channel is None or channel.id != actual_channel_id:
        _fail(OUTBOUND_CHANNEL_ROUTE_MISMATCH)
    if channel.workspace_id != conversation.workspace_id:
        _fail(OUTBOUND_CHANNEL_WORKSPACE_MISMATCH)

    try:
        contact = conversation.contact
    except ObjectDoesNotExist:
        _fail(OUTBOUND_RECIPIENT_INVALID)
    if contact.workspace_id != conversation.workspace_id:
        _fail(OUTBOUND_CONTACT_WORKSPACE_MISMATCH)

    if channel.provider != WhatsAppChannel.Provider.EVOLUTION:
        _fail(OUTBOUND_PROVIDER_UNSUPPORTED)
    if not _is_safe_route_value(
        channel.instance_name,
        max_length=MAX_INSTANCE_NAME_LENGTH,
    ):
        _fail(OUTBOUND_INSTANCE_INVALID)

    recipient_validation = validate_whatsapp_recipient(
        recipient=contact.phone,
        channel_phone_number=channel.phone_number,
    )
    if not recipient_validation.is_valid:
        _fail(recipient_validation.internal_error_code)
    recipient = recipient_validation.canonical_phone

    if channel.status in _TRANSIENT_CHANNEL_STATUSES:
        _fail(OUTBOUND_CHANNEL_NOT_READY, retryable=True)
    permanent_error_code = _PERMANENT_CHANNEL_ERROR_CODES.get(channel.status)
    if permanent_error_code is not None:
        _fail(permanent_error_code)
    if channel.status != WhatsAppChannel.Status.CONNECTED:
        _fail(OUTBOUND_CHANNEL_STATUS_INVALID)

    return OutboundWhatsAppRoute(
        message=message,
        conversation=conversation,
        contact=contact,
        channel=channel,
        recipient=recipient,
    )


def _same_uuid(candidate: UUID | str, expected: UUID) -> bool:
    try:
        return UUID(str(candidate)) == UUID(str(expected))
    except (AttributeError, TypeError, ValueError):
        return False


def _is_safe_route_value(value: object, *, max_length: int) -> bool:
    return (
        isinstance(value, str)
        and bool(value)
        and value == value.strip()
        and len(value) <= max_length
        and not any(unicodedata.category(character) == 'Cc' for character in value)
    )


def _sanitize_error_code(value: object) -> str:
    normalized = re.sub(r'[^A-Z0-9]+', '_', str(value or '').upper()).strip('_')
    return normalized[:64] or 'OUTBOUND_ROUTING_ERROR'


def _fail(error_code: str, *, retryable: bool = False) -> None:
    raise OutboundWhatsAppRoutingError(error_code, retryable=retryable)
