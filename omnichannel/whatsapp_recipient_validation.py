from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from django.core.exceptions import ObjectDoesNotExist

from omnichannel.models import Conversation

RECIPIENT_UNRESOLVED = 'recipient_unresolved'
RECIPIENT_IS_CHANNEL_PHONE = 'recipient_is_channel_phone'
VALID_RECIPIENT = 'valid_recipient'

OUTBOUND_RECIPIENT_UNRESOLVED = 'OUTBOUND_RECIPIENT_UNRESOLVED'
OUTBOUND_RECIPIENT_SELF = 'OUTBOUND_RECIPIENT_SELF'

_PHONE_PATTERN = re.compile(r'^\d{8,20}$')
_FORMATTED_PHONE_PATTERN = re.compile(r'^\+?[0-9() -]+$')


@dataclass(frozen=True, slots=True)
class WhatsAppRecipientValidation:
    status: str
    canonical_phone: str = ''

    @property
    def is_valid(self) -> bool:
        return self.status == VALID_RECIPIENT

    @property
    def internal_error_code(self) -> str:
        if self.status == RECIPIENT_IS_CHANNEL_PHONE:
            return OUTBOUND_RECIPIENT_SELF
        return OUTBOUND_RECIPIENT_UNRESOLVED


def normalize_trusted_phone(value: object) -> str | None:
    """Normaliza somente telefone composto por digitos e pontuacao conhecida."""
    if not isinstance(value, str) or not value:
        return None
    if any(unicodedata.category(character) == 'Cc' for character in value):
        return None

    candidate = value.strip()
    if not candidate or not _FORMATTED_PHONE_PATTERN.fullmatch(candidate):
        return None
    if candidate.count('+') > 1 or '+' in candidate[1:]:
        return None

    digits = ''.join(character for character in candidate if character.isdigit())
    return digits if _PHONE_PATTERN.fullmatch(digits) else None


def validate_whatsapp_recipient(
    *,
    recipient: object,
    channel_phone_number: object = '',
) -> WhatsAppRecipientValidation:
    canonical_recipient = normalize_trusted_phone(recipient)
    if canonical_recipient is None:
        return WhatsAppRecipientValidation(status=RECIPIENT_UNRESOLVED)

    canonical_channel_phone = normalize_trusted_phone(channel_phone_number)
    if (
        canonical_channel_phone is not None
        and canonical_recipient == canonical_channel_phone
    ):
        return WhatsAppRecipientValidation(status=RECIPIENT_IS_CHANNEL_PHONE)

    return WhatsAppRecipientValidation(
        status=VALID_RECIPIENT,
        canonical_phone=canonical_recipient,
    )


def validate_conversation_whatsapp_recipient(
    conversation: Conversation,
) -> WhatsAppRecipientValidation:
    try:
        contact = conversation.contact
    except (AttributeError, ObjectDoesNotExist):
        return WhatsAppRecipientValidation(status=RECIPIENT_UNRESOLVED)
    if contact.workspace_id != conversation.workspace_id:
        return WhatsAppRecipientValidation(status=RECIPIENT_UNRESOLVED)
    recipient = contact.phone

    try:
        channel = conversation.whatsapp_channel
    except ObjectDoesNotExist:
        channel = None
    if channel is not None and channel.workspace_id != conversation.workspace_id:
        return WhatsAppRecipientValidation(status=RECIPIENT_UNRESOLVED)
    channel_phone_number = channel.phone_number if channel is not None else ''
    return validate_whatsapp_recipient(
        recipient=recipient,
        channel_phone_number=channel_phone_number,
    )
