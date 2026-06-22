"""
Regras de negocio do omnichannel (handlers de provedores externos).
"""
from __future__ import annotations

import logging
from typing import Any

import requests
from django.conf import settings
from django.db import transaction

from crm.models import Contact

from .models import Conversation, Message

logger = logging.getLogger(__name__)

WHATSAPP_CHANNEL = 'whatsapp'
DEFAULT_AI_SYSTEM_PROMPT = 'Você é um assistente virtual prestativo da Silvertech.'


def _normalize_whatsapp_jid(remote_jid: str) -> str:
    """Remove o sufixo do JID e devolve apenas o numero."""
    return remote_jid.split('@', maxsplit=1)[0]


def _extract_evolution_text(message: dict[str, Any]) -> str | None:
    """Extrai texto simples dos formatos suportados pela Evolution."""
    conversation = message.get('conversation')
    if conversation:
        return str(conversation)

    extended_text = message.get('extendedTextMessage')
    if isinstance(extended_text, dict):
        text = extended_text.get('text')
        if text:
            return str(text)

    return None


def build_conversation_context_for_ai(conversation_id) -> dict[str, Any] | None:
    """Monta o contexto de conversa para processamento por IA."""
    try:
        conversation = Conversation.objects.select_related('workspace', 'contact').get(
            id=conversation_id,
        )
    except Conversation.DoesNotExist:
        logger.warning(
            'Conversa nao encontrada para montar contexto de IA (conversation_id=%s)',
            conversation_id,
        )
        return None

    if conversation.is_human_handoff:
        logger.info(
            'Contexto de IA ignorado: conversa em handoff humano (conversation_id=%s)',
            conversation_id,
        )
        return None

    recent_messages = list(
        Message.objects.filter(conversation=conversation)
        .order_by('-created_at')[:15],
    )
    recent_messages.reverse()

    messages = []
    for message in recent_messages:
        role = 'user' if message.direction == Message.Direction.INBOUND else 'assistant'
        messages.append(
            {
                'role': role,
                'content': message.body,
            },
        )

    system_prompt = conversation.workspace.ai_system_prompt or DEFAULT_AI_SYSTEM_PROMPT

    return {
        'system_prompt': system_prompt,
        'chat_info': {
            'workspace_id': str(conversation.workspace.id),
            'conversation_id': str(conversation.id),
            'contact_name': conversation.contact.name,
            'contact_phone': conversation.contact.phone,
        },
        'messages': messages,
    }


def _upsert_inbound_message(
    *,
    workspace_id: str,
    phone: str,
    contact_name: str,
    body: str,
    external_id: str | None,
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
            external_id=external_id,
        )


def _process_evolution_message(data: dict[str, Any], workspace_id: str) -> None:
    """Processa um item `messages.upsert` da Evolution API."""
    key = data.get('key')
    if not isinstance(key, dict):
        return

    if key.get('fromMe') is True:
        return

    remote_jid = key.get('remoteJid')
    if not remote_jid:
        return

    remote_jid = str(remote_jid)
    if remote_jid.endswith('@g.us'):
        return

    message = data.get('message')
    if not isinstance(message, dict):
        return

    body = _extract_evolution_text(message)
    if not body:
        return

    phone = _normalize_whatsapp_jid(remote_jid)
    contact_name = str(data.get('pushName') or phone)
    external_id = key.get('id')

    _upsert_inbound_message(
        workspace_id=workspace_id,
        phone=phone,
        contact_name=contact_name,
        body=body,
        external_id=str(external_id) if external_id else None,
    )


def _process_messages_upsert(payload: dict[str, Any], workspace_id: str) -> None:
    """Processa evento `messages.upsert` da Evolution API."""
    data = payload.get('data')
    if isinstance(data, dict):
        _process_evolution_message(data, workspace_id)
        return

    if isinstance(data, list):
        for item in data:
            if isinstance(item, dict):
                _process_evolution_message(item, workspace_id)


def _process_connection_update(payload: dict[str, Any]) -> None:
    """Loga mudancas de estado da conexao Evolution."""
    data = payload.get('data')
    state = data.get('state') if isinstance(data, dict) else None
    instance = payload.get('instance')

    if state == 'close':
        logger.warning('Evolution desconectada (instance=%s, state=%s)', instance, state)
        return

    logger.info('Evolution connection.update (instance=%s, state=%s)', instance, state)


def process_whatsapp_payload(payload: dict[str, Any], workspace_id: str) -> None:
    """Processa webhooks da Evolution API."""
    event = payload.get('event')

    if event == 'messages.upsert':
        _process_messages_upsert(payload, workspace_id)
        return

    if event == 'connection.update':
        _process_connection_update(payload)
        return

    logger.info('Evento Evolution ignorado: %s', event)


def send_whatsapp_message(phone: str, text: str) -> dict[str, Any]:
    """
    Envia mensagem de texto via Evolution API.

    Raises:
        requests.exceptions.RequestException: falha de rede ou resposta HTTP da Evolution.
    """
    api_url = settings.EVOLUTION_API_URL.rstrip('/')
    api_key = settings.EVOLUTION_API_KEY
    instance_name = settings.EVOLUTION_INSTANCE_NAME

    if not api_url or not api_key or not instance_name:
        raise requests.exceptions.RequestException(
            'EVOLUTION_API_URL, EVOLUTION_API_KEY ou EVOLUTION_INSTANCE_NAME nao configurados.',
        )

    url = f'{api_url}/message/sendText/{instance_name}'
    payload = {
        'number': phone,
        'text': text,
    }
    headers = {
        'apikey': api_key,
        'Content-Type': 'application/json',
    }

    try:
        response = requests.post(url, json=payload, headers=headers, timeout=30)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as exc:
        logger.error('Falha ao enviar WhatsApp para %s: %s', phone, exc, exc_info=True)
        if getattr(exc, 'response', None) is not None:
            logger.error('Resposta Evolution: %s', exc.response.text)
        raise
