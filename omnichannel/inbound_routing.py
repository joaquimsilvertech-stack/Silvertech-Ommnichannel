from __future__ import annotations

import logging
import unicodedata
from dataclasses import dataclass

from django.db import IntegrityError, transaction
from django.db.models import Q

from crm.models import Contact
from omnichannel.models import Conversation, WhatsAppChannel

logger = logging.getLogger(__name__)

WHATSAPP_CONVERSATION_CHANNEL = 'whatsapp'


@dataclass(frozen=True)
class InboundWhatsAppRoute:
    contact: Contact
    conversation: Conversation


def resolve_inbound_whatsapp_route(
    *,
    channel: WhatsAppChannel,
    phone: str,
    contact_name: str,
) -> InboundWhatsAppRoute:
    """Resolve a rota inbound usando somente a identidade do canal bloqueado."""
    workspace_id = channel.workspace_id
    safe_contact_name = _safe_contact_name(contact_name, phone)
    contact = _resolve_contact(
        workspace_id=workspace_id,
        phone=phone,
        contact_name=safe_contact_name,
    )
    conversation = _resolve_conversation(channel=channel, contact=contact)
    return InboundWhatsAppRoute(contact=contact, conversation=conversation)


def _resolve_contact(*, workspace_id, phone: str, contact_name: str) -> Contact:
    contact = _get_exact_contact(workspace_id=workspace_id, phone=phone)
    if contact is None:
        candidate = _get_unclaimed_contact(workspace_id=workspace_id, phone=phone)
        if candidate is not None:
            try:
                with transaction.atomic():
                    _claim_contact_identity(contact=candidate, phone=phone)
                contact = candidate
            except IntegrityError:
                contact = _get_exact_contact(workspace_id=workspace_id, phone=phone)
                if contact is None:
                    raise
        else:
            try:
                with transaction.atomic():
                    contact = _create_contact_identity(
                        workspace_id=workspace_id,
                        phone=phone,
                        contact_name=contact_name,
                    )
            except IntegrityError:
                contact = _get_exact_contact(workspace_id=workspace_id, phone=phone)
                if contact is None:
                    raise

    _synchronize_contact(contact=contact, phone=phone, contact_name=contact_name)
    return contact


def _get_exact_contact(*, workspace_id, phone: str) -> Contact | None:
    try:
        return Contact.objects.select_for_update().get(
            workspace_id=workspace_id,
            channel_id=phone,
        )
    except Contact.DoesNotExist:
        return None


def _get_unclaimed_contact(*, workspace_id, phone: str) -> Contact | None:
    return (
        Contact.objects.select_for_update()
        .filter(workspace_id=workspace_id, phone=phone)
        .filter(Q(channel_id__isnull=True) | Q(channel_id=''))
        .order_by('created_at', 'id')
        .first()
    )


def _claim_contact_identity(*, contact: Contact, phone: str) -> None:
    contact.channel_id = phone
    contact.save(update_fields=['channel_id', 'updated_at'])


def _create_contact_identity(
    *,
    workspace_id,
    phone: str,
    contact_name: str,
) -> Contact:
    return Contact.objects.create(
        workspace_id=workspace_id,
        phone=phone,
        channel_id=phone,
        name=contact_name,
    )


def _synchronize_contact(*, contact: Contact, phone: str, contact_name: str) -> None:
    update_fields: list[str] = []
    has_placeholder_name = _is_placeholder_name(contact=contact, phone=phone)
    if contact.phone != phone:
        contact.phone = phone
        update_fields.append('phone')

    if has_placeholder_name and contact.name != contact_name:
        contact.name = contact_name
        update_fields.append('name')

    if update_fields:
        contact.save(update_fields=[*update_fields, 'updated_at'])


def _is_placeholder_name(*, contact: Contact, phone: str) -> bool:
    current_name = contact.name or ''
    return not current_name or current_name in {
        phone,
        contact.phone,
        contact.channel_id or '',
    }


def _safe_contact_name(value: object, phone: str) -> str:
    if not isinstance(value, str):
        return phone
    if not value or value != value.strip() or len(value) > 255:
        return phone
    if any(unicodedata.category(character) == 'Cc' for character in value):
        return phone
    return value


def _resolve_conversation(
    *,
    channel: WhatsAppChannel,
    contact: Contact,
) -> Conversation:
    conversations = Conversation.objects.select_for_update().filter(
        workspace_id=channel.workspace_id,
        contact=contact,
        channel=WHATSAPP_CONVERSATION_CHANNEL,
        whatsapp_channel=channel,
        status=Conversation.Status.OPEN,
    ).order_by('created_at', 'id')
    matches = list(conversations[:2])
    if matches:
        conversation = matches[0]
        if len(matches) > 1:
            logger.warning(
                'Rotas inbound possuem conversas abertas duplicadas',
                extra={
                    'workspace_id': str(channel.workspace_id),
                    'channel_id': str(channel.id),
                    'contact_id': str(contact.id),
                    'conversation_id': str(conversation.id),
                    'duplicate_count': conversations.count(),
                    'error_code': 'DUPLICATE_OPEN_CONVERSATIONS',
                },
            )
        return conversation

    return Conversation.objects.create(
        workspace_id=channel.workspace_id,
        contact=contact,
        channel=WHATSAPP_CONVERSATION_CHANNEL,
        whatsapp_channel=channel,
        status=Conversation.Status.OPEN,
    )
