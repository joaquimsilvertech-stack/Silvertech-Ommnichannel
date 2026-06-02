"""
Regras de negócio do omnichannel (handlers de provedores externos).
"""
from __future__ import annotations

import logging
from typing import Any, Iterator

import requests
from django.conf import settings
from django.db import transaction

from crm.models import Contact

from .models import Conversation, Message

logger = logging.getLogger(__name__)

WHATSAPP_CHANNEL = 'whatsapp'
WHATSAPP_GRAPH_API_VERSION = 'v19.0'


def _iter_meta_values(payload: dict[str, Any]) -> Iterator[dict[str, Any]]:
    """Percorre entry -> changes -> value do payload padrão da Meta."""
    for entry in payload.get('entry', []):
        if not isinstance(entry, dict):
            continue
        for change in entry.get('changes', []):
            if not isinstance(change, dict):
                continue
            value = change.get('value')
            if isinstance(value, dict):
                yield value


def _upsert_inbound_message(
    *,
    workspace_id: str,
    phone: str,
    contact_name: str,
    body: str,
) -> None:
    """Cria ou reutiliza Contact/Conversation e persiste Message inbound."""
    with transaction.atomic():
        contact, created = Contact.objects.get_or_create(
            workspace_id=workspace_id,
            phone=phone,
            defaults={
                'name': contact_name,
                'channel_id': phone,
            },
        )
        if not created and contact.name != contact_name and contact_name != phone:
            contact.name = contact_name
            contact.save(update_fields=['name', 'updated_at'])

        conversation = Conversation.objects.filter(
            workspace_id=workspace_id,
            contact=contact,
            channel=WHATSAPP_CHANNEL,
            status=Conversation.Status.OPEN,
        ).first()

        if conversation is None:
            conversation = Conversation.objects.create(
                workspace_id=workspace_id,
                contact=contact,
                channel=WHATSAPP_CHANNEL,
                status=Conversation.Status.OPEN,
            )

        Message.objects.create(
            conversation=conversation,
            body=body,
            direction=Message.Direction.INBOUND,
            status=Message.Status.DELIVERED,
        )


def _process_inbound_messages(value: dict[str, Any], workspace_id: str) -> None:
    """Processa blocos `messages` do webhook (texto recebido)."""
    messages = value.get('messages')
    if not messages or not isinstance(messages, list):
        return

    contacts = value.get('contacts', [])
    profile_name: str | None = None
    if contacts and isinstance(contacts[0], dict):
        profile = contacts[0].get('profile', {})
        if isinstance(profile, dict):
            profile_name = profile.get('name')

    for message in messages:
        if not isinstance(message, dict):
            continue

        phone = message.get('from')
        if not phone:
            continue

        text_body = message.get('text', {})
        if not isinstance(text_body, dict):
            continue
        body = text_body.get('body')
        if not body:
            continue

        contact_name = profile_name or str(phone)
        _upsert_inbound_message(
            workspace_id=workspace_id,
            phone=str(phone),
            contact_name=contact_name,
            body=body,
        )


def _process_message_statuses(value: dict[str, Any]) -> None:
    """Atualiza status da Message a partir do webhook (sent/delivered/read/failed)."""
    statuses = value.get('statuses')
    if not statuses or not isinstance(statuses, list):
        return

    valid_statuses = {choice.value for choice in Message.Status}

    for status_item in statuses:
        if not isinstance(status_item, dict):
            continue

        message_id = status_item.get('id')
        status_text = status_item.get('status')
        if not message_id or not status_text:
            continue

        if status_text not in valid_statuses:
            logger.warning(
                'Status WhatsApp desconhecido: %s (wamid=%s)',
                status_text,
                message_id,
            )
            continue

        try:
            message = Message.objects.get(external_id=message_id)
        except Message.DoesNotExist:
            logger.warning('Message não encontrada para wamid=%s', message_id)
            continue

        if message.status != status_text:
            message.status = status_text
            message.save(update_fields=['status', 'updated_at'])


def process_whatsapp_payload(payload: dict[str, Any], workspace_id: str) -> None:
    """
    Processa webhook WhatsApp Cloud API: mensagens inbound e status updates.

    Navega entry -> changes -> value.
    """
    for value in _iter_meta_values(payload):
        _process_inbound_messages(value, workspace_id)
        _process_message_statuses(value)


def send_whatsapp_message(phone: str, text: str) -> dict[str, Any]:
    """
    Envia mensagem de texto via WhatsApp Cloud API (Card #028).

    Raises:
        requests.exceptions.RequestException: falha de rede ou resposta HTTP da Meta.
    """
    phone_number_id = settings.WHATSAPP_PHONE_NUMBER_ID
    access_token = settings.WHATSAPP_ACCESS_TOKEN

    if not phone_number_id or not access_token:
        raise requests.exceptions.RequestException(
            'WHATSAPP_ACCESS_TOKEN ou WHATSAPP_PHONE_NUMBER_ID não configurados.',
        )

    url = (
        f'https://graph.facebook.com/{WHATSAPP_GRAPH_API_VERSION}/'
        f'{phone_number_id}/messages'
    )
    payload = {
        'messaging_product': 'whatsapp',
        'to': phone,
        'type': 'text',
        'text': {'body': text},
    }
    headers = {
        'Authorization': f'Bearer {access_token}',
        'Content-Type': 'application/json',
    }

    try:
        response = requests.post(url, json=payload, headers=headers, timeout=30)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as exc:
        logger.error('Falha ao enviar WhatsApp para %s: %s', phone, exc, exc_info=True)
        if getattr(exc, 'response', None) is not None:
            logger.error('Resposta Meta: %s', exc.response.text)
        raise
