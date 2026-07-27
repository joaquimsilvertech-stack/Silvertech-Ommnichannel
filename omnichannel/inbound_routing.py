from __future__ import annotations

import logging
import unicodedata
from dataclasses import dataclass

from django.db import IntegrityError, transaction
from django.db.models import Q

from crm.models import Contact
from omnichannel.models import Conversation, WhatsAppChannel
from omnichannel.whatsapp_recipient_validation import (
    RECIPIENT_IS_CHANNEL_PHONE,
    validate_whatsapp_recipient,
)

logger = logging.getLogger(__name__)

WHATSAPP_CONVERSATION_CHANNEL = 'whatsapp'


@dataclass(frozen=True)
class InboundWhatsAppRoute:
    contact: Contact
    conversation: Conversation


def resolve_inbound_whatsapp_route(
    *,
    channel: WhatsAppChannel,
    provider_identity: str,
    resolved_phone: str,
    contact_name: str,
) -> InboundWhatsAppRoute:
    """Resolve a rota inbound usando somente a identidade do canal bloqueado."""
    contact = resolve_inbound_whatsapp_contact(
        workspace_id=channel.workspace_id,
        provider_identity=provider_identity,
        resolved_phone=resolved_phone,
        contact_name=contact_name,
        channel_phone_number=channel.phone_number,
    )
    conversation = _resolve_conversation(channel=channel, contact=contact)
    return InboundWhatsAppRoute(contact=contact, conversation=conversation)


def resolve_inbound_whatsapp_contact(
    *,
    workspace_id,
    provider_identity: str,
    resolved_phone: str,
    contact_name: str,
    channel_phone_number: str = '',
) -> Contact:
    """Resolve Contact sem confundir identidade do provider com telefone."""
    recipient_validation = validate_whatsapp_recipient(
        recipient=resolved_phone,
        channel_phone_number=channel_phone_number,
    )
    safe_resolved_phone = (
        recipient_validation.canonical_phone
        if recipient_validation.is_valid
        else ''
    )
    if recipient_validation.status == RECIPIENT_IS_CHANNEL_PHONE:
        logger.warning(
            'Telefone resolvido inbound corresponde a linha do canal',
            extra={
                'workspace_id': str(workspace_id),
                'error_code': 'INBOUND_RECIPIENT_IS_CHANNEL_PHONE',
            },
        )

    safe_contact_name = _safe_contact_name(
        contact_name,
        provider_identity=provider_identity,
        resolved_phone=safe_resolved_phone,
    )
    contact = _get_exact_contact(
        workspace_id=workspace_id,
        provider_identity=provider_identity,
    )
    if contact is None:
        candidate = None
        if provider_identity == safe_resolved_phone:
            candidate = _get_unclaimed_contact(
                workspace_id=workspace_id,
                resolved_phone=safe_resolved_phone,
            )
        if candidate is not None:
            try:
                with transaction.atomic():
                    _claim_contact_identity(
                        contact=candidate,
                        provider_identity=provider_identity,
                    )
                contact = candidate
            except IntegrityError:
                contact = _get_exact_contact(
                    workspace_id=workspace_id,
                    provider_identity=provider_identity,
                )
                if contact is None:
                    raise
        else:
            try:
                with transaction.atomic():
                    contact = _create_contact_identity(
                        workspace_id=workspace_id,
                        provider_identity=provider_identity,
                        resolved_phone=safe_resolved_phone,
                        contact_name=safe_contact_name,
                    )
            except IntegrityError:
                contact = _get_exact_contact(
                    workspace_id=workspace_id,
                    provider_identity=provider_identity,
                )
                if contact is None:
                    raise

    _synchronize_contact(
        contact=contact,
        provider_identity=provider_identity,
        resolved_phone=safe_resolved_phone,
        contact_name=safe_contact_name,
    )
    return contact


def _get_exact_contact(*, workspace_id, provider_identity: str) -> Contact | None:
    try:
        return Contact.objects.select_for_update().get(
            workspace_id=workspace_id,
            channel_id=provider_identity,
        )
    except Contact.DoesNotExist:
        return None


def _get_unclaimed_contact(*, workspace_id, resolved_phone: str) -> Contact | None:
    return (
        Contact.objects.select_for_update()
        .filter(workspace_id=workspace_id, phone=resolved_phone)
        .filter(Q(channel_id__isnull=True) | Q(channel_id=''))
        .order_by('created_at', 'id')
        .first()
    )


def _claim_contact_identity(*, contact: Contact, provider_identity: str) -> None:
    contact.channel_id = provider_identity
    contact.save(update_fields=['channel_id', 'updated_at'])


def _create_contact_identity(
    *,
    workspace_id,
    provider_identity: str,
    resolved_phone: str,
    contact_name: str,
) -> Contact:
    return Contact.objects.create(
        workspace_id=workspace_id,
        phone=resolved_phone,
        channel_id=provider_identity,
        name=contact_name,
    )


def _synchronize_contact(
    *,
    contact: Contact,
    provider_identity: str,
    resolved_phone: str,
    contact_name: str,
) -> None:
    update_fields: list[str] = []
    has_placeholder_name = _is_placeholder_name(
        contact=contact,
        provider_identity=provider_identity,
        resolved_phone=resolved_phone,
    )
    if not contact.phone and resolved_phone:
        contact.phone = resolved_phone
        update_fields.append('phone')
    elif contact.phone and resolved_phone and contact.phone != resolved_phone:
        logger.warning(
            'Telefone inbound conflita com identidade existente',
            extra={
                'workspace_id': str(contact.workspace_id),
                'contact_id': str(contact.id),
                'error_code': 'INBOUND_PHONE_CONFLICT',
            },
        )

    if has_placeholder_name and contact.name != contact_name:
        contact.name = contact_name
        update_fields.append('name')

    if update_fields:
        contact.save(update_fields=[*update_fields, 'updated_at'])


def _is_placeholder_name(
    *,
    contact: Contact,
    provider_identity: str,
    resolved_phone: str,
) -> bool:
    current_name = contact.name or ''
    return not current_name or current_name in {
        provider_identity,
        resolved_phone,
        contact.phone,
        contact.channel_id or '',
    }


def _safe_contact_name(
    value: object,
    *,
    provider_identity: str,
    resolved_phone: str,
) -> str:
    fallback = resolved_phone or provider_identity
    if not isinstance(value, str):
        return fallback
    if not value or value != value.strip() or len(value) > 255:
        return fallback
    if any(unicodedata.category(character) == 'Cc' for character in value):
        return fallback
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
