"""
Regras de negocio do omnichannel (handlers de provedores externos).
"""
from __future__ import annotations

import logging
from typing import Any

import requests
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone

from crm.models import Contact
from omnichannel.ai.registry import is_provider_supported
from workspaces.models import Workspace, WorkspaceAIProviderConfig

from .models import AIProcessingRun, Conversation, Message

logger = logging.getLogger(__name__)

WHATSAPP_CHANNEL = 'whatsapp'
RECENT_AI_MESSAGES_LIMIT = 15
AI_SKIP_NO_ACTIVE_PROVIDER = 'NO_ACTIVE_PROVIDER'
AI_SKIP_UNSUPPORTED_PROVIDER = 'UNSUPPORTED_PROVIDER'
AI_SKIP_MISSING_API_KEY = 'MISSING_API_KEY'
AI_SKIP_CONVERSATION_HANDOFF = 'CONVERSATION_HANDOFF'
AI_SKIP_MESSAGE_NOT_INBOUND = 'MESSAGE_NOT_INBOUND'
AI_SKIP_MESSAGE_FROM_ME = 'MESSAGE_FROM_ME'
AI_SKIP_UNSUPPORTED_GROUP_MESSAGE = 'UNSUPPORTED_GROUP_MESSAGE'
AI_SKIP_EMPTY_CONTENT = 'EMPTY_CONTENT'
AI_SKIP_NON_PROCESSABLE_CONTENT = 'NON_PROCESSABLE_CONTENT'
NON_PROCESSABLE_MESSAGE_TYPES = {
    'audioMessage',
    'documentMessage',
    'imageMessage',
    'reactionMessage',
    'stickerMessage',
    'videoMessage',
}
AI_PROCESSING_ALREADY_SUCCEEDED = 'ALREADY_SUCCEEDED'
AI_PROCESSING_ALREADY_RUNNING = 'ALREADY_RUNNING'
AI_PROCESSING_ALREADY_FAILED = 'ALREADY_FAILED'
AI_PROCESSING_ALREADY_SKIPPED = 'ALREADY_SKIPPED'
EVOLUTION_TIMEOUT = 'EVOLUTION_TIMEOUT'
EVOLUTION_REQUEST_ERROR = 'EVOLUTION_REQUEST_ERROR'
EVOLUTION_INVALID_RESPONSE = 'EVOLUTION_INVALID_RESPONSE'
EVOLUTION_UNKNOWN_ERROR = 'EVOLUTION_UNKNOWN_ERROR'


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


def is_message_processable_for_ai(message: Message) -> tuple[bool, str | None]:
    """Retorna se uma mensagem salva pode ser enviada ao motor de IA."""
    body = message.body
    if body is None or not str(body).strip():
        return False, AI_SKIP_EMPTY_CONTENT

    message_type = getattr(message, 'ai_message_type', None)
    if message_type in NON_PROCESSABLE_MESSAGE_TYPES:
        return False, AI_SKIP_NON_PROCESSABLE_CONTENT

    return True, None


def should_schedule_ai_response(
    *,
    workspace: Workspace,
    conversation: Conversation,
    message: Message,
) -> tuple[bool, str | None]:
    """Decide localmente se uma inbound pode agendar resposta automatica de IA."""
    if message.direction != Message.Direction.INBOUND:
        return False, AI_SKIP_MESSAGE_NOT_INBOUND

    if getattr(message, 'ai_from_me', False):
        return False, AI_SKIP_MESSAGE_FROM_ME

    remote_jid = getattr(message, 'ai_remote_jid', '')
    if isinstance(remote_jid, str) and remote_jid.endswith('@g.us'):
        return False, AI_SKIP_UNSUPPORTED_GROUP_MESSAGE

    is_processable, reason_code = is_message_processable_for_ai(message)
    if not is_processable:
        return False, reason_code

    if conversation.is_human_handoff:
        return False, AI_SKIP_CONVERSATION_HANDOFF

    provider_config = (
        WorkspaceAIProviderConfig.objects.filter(
            workspace=workspace,
            is_active=True,
        )
        .only('api_key', 'provider')
        .first()
    )
    if provider_config is None:
        return False, AI_SKIP_NO_ACTIVE_PROVIDER

    if not is_provider_supported(provider_config.provider):
        return False, AI_SKIP_UNSUPPORTED_PROVIDER

    if not provider_config.api_key:
        return False, AI_SKIP_MISSING_API_KEY

    return True, None


def schedule_ai_response_after_commit(
    *,
    conversation: Conversation,
    source_message: Message,
) -> None:
    """Agenda a resposta de IA apenas apos commit da mensagem inbound."""

    def _enqueue() -> None:
        try:
            from omnichannel.tasks import process_ai_response

            process_ai_response.delay(
                conversation_id=str(conversation.id),
                source_message_id=str(source_message.id),
            )
        except Exception as exc:
            logger.exception(
                'Falha ao agendar resposta de IA',
                extra={
                    'workspace_id': str(conversation.workspace_id),
                    'conversation_id': str(conversation.id),
                    'source_message_id': str(source_message.id),
                    'exception_type': type(exc).__name__,
                },
            )

    transaction.on_commit(_enqueue)


def claim_ai_processing_run(
    *,
    source_message: Message,
    provider_config: WorkspaceAIProviderConfig,
) -> tuple[AIProcessingRun | None, str | None]:
    """Assume de forma idempotente o processamento de IA de uma inbound."""
    now = timezone.now()
    try:
        with transaction.atomic():
            run = AIProcessingRun.objects.create(
                workspace=source_message.conversation.workspace,
                conversation=source_message.conversation,
                source_message=source_message,
                provider_config=provider_config,
                status=AIProcessingRun.Status.RUNNING,
                attempt_count=1,
                started_at=now,
            )
            logger.info(
                'AIProcessingRun criado',
                extra={
                    'workspace_id': str(run.workspace_id),
                    'conversation_id': str(run.conversation_id),
                    'source_message_id': str(run.source_message_id),
                    'ai_processing_run_id': str(run.id),
                    'provider': provider_config.provider,
                    'model_name': provider_config.model_name,
                    'status': run.status,
                },
            )
            return run, None
    except IntegrityError:
        with transaction.atomic():
            run = AIProcessingRun.objects.select_for_update().get(
                source_message=source_message,
            )
            reason_code = {
                AIProcessingRun.Status.SUCCEEDED: AI_PROCESSING_ALREADY_SUCCEEDED,
                AIProcessingRun.Status.RUNNING: AI_PROCESSING_ALREADY_RUNNING,
                AIProcessingRun.Status.FAILED: AI_PROCESSING_ALREADY_FAILED,
                AIProcessingRun.Status.SKIPPED: AI_PROCESSING_ALREADY_SKIPPED,
            }.get(run.status, AI_PROCESSING_ALREADY_RUNNING)
            logger.info(
                'AIProcessingRun existente impede duplicidade',
                extra={
                    'workspace_id': str(run.workspace_id),
                    'conversation_id': str(run.conversation_id),
                    'source_message_id': str(run.source_message_id),
                    'ai_processing_run_id': str(run.id),
                    'status': run.status,
                    'reason_code': reason_code,
                },
            )
            return None, reason_code


def mark_ai_processing_succeeded(
    *,
    run: AIProcessingRun,
    output_message: Message,
) -> AIProcessingRun:
    with transaction.atomic():
        locked_run = AIProcessingRun.objects.select_for_update().get(id=run.id)
        locked_run.status = AIProcessingRun.Status.SUCCEEDED
        locked_run.output_message = output_message
        locked_run.error_code = ''
        locked_run.finished_at = timezone.now()
        locked_run.save(
            update_fields=[
                'status',
                'output_message',
                'error_code',
                'finished_at',
                'updated_at',
            ],
        )
        logger.info(
            'AIProcessingRun concluido',
            extra={
                'workspace_id': str(locked_run.workspace_id),
                'conversation_id': str(locked_run.conversation_id),
                'source_message_id': str(locked_run.source_message_id),
                'ai_processing_run_id': str(locked_run.id),
                'status': locked_run.status,
            },
        )
        return locked_run


def mark_ai_processing_failed(
    *,
    run: AIProcessingRun,
    error_code: str,
) -> AIProcessingRun:
    return _mark_ai_processing_finished(
        run=run,
        status=AIProcessingRun.Status.FAILED,
        error_code=error_code,
    )


def mark_ai_processing_skipped(
    *,
    run: AIProcessingRun,
    error_code: str,
) -> AIProcessingRun:
    return _mark_ai_processing_finished(
        run=run,
        status=AIProcessingRun.Status.SKIPPED,
        error_code=error_code,
    )


def _mark_ai_processing_finished(
    *,
    run: AIProcessingRun,
    status: str,
    error_code: str,
) -> AIProcessingRun:
    sanitized_error_code = _sanitize_ai_processing_error_code(error_code)
    with transaction.atomic():
        locked_run = AIProcessingRun.objects.select_for_update().get(id=run.id)
        locked_run.status = status
        locked_run.error_code = sanitized_error_code
        locked_run.finished_at = timezone.now()
        locked_run.save(
            update_fields=[
                'status',
                'error_code',
                'finished_at',
                'updated_at',
            ],
        )
        logger.info(
            'AIProcessingRun finalizado sem sucesso',
            extra={
                'workspace_id': str(locked_run.workspace_id),
                'conversation_id': str(locked_run.conversation_id),
                'source_message_id': str(locked_run.source_message_id),
                'ai_processing_run_id': str(locked_run.id),
                'status': locked_run.status,
                'error_code': locked_run.error_code,
            },
        )
        return locked_run


def _sanitize_ai_processing_error_code(error_code: str) -> str:
    sanitized = ''.join(
        char if char.isalnum() or char == '_' else '_'
        for char in str(error_code or 'UNKNOWN_ERROR').upper()
    )
    return sanitized[:64] or 'UNKNOWN_ERROR'


def create_pending_ai_message(
    *,
    conversation: Conversation,
    body: str,
) -> Message:
    """Cria a mensagem outbound da IA antes do envio externo."""
    return Message.objects.create(
        conversation=conversation,
        body=body,
        direction=Message.Direction.OUTBOUND,
        status=Message.Status.PENDING,
        external_id=None,
        send_error_code='',
    )


def mark_message_as_sent(
    *,
    message: Message,
    external_id: str | None = None,
) -> Message:
    with transaction.atomic():
        locked_message = Message.objects.select_for_update().get(id=message.id)
        locked_message.status = Message.Status.SENT
        if external_id:
            locked_message.external_id = external_id
        locked_message.send_error_code = ''
        locked_message.save(
            update_fields=[
                'status',
                'external_id',
                'send_error_code',
                'updated_at',
            ],
        )
        return locked_message


def mark_message_as_failed(
    *,
    message: Message,
    error_code: str,
) -> Message:
    with transaction.atomic():
        locked_message = Message.objects.select_for_update().get(id=message.id)
        locked_message.status = Message.Status.FAILED
        locked_message.send_error_code = sanitize_message_send_error_code(error_code)
        locked_message.save(
            update_fields=[
                'status',
                'send_error_code',
                'updated_at',
            ],
        )
        return locked_message


def extract_evolution_message_external_id(response_payload: dict[str, Any]) -> str | None:
    if not isinstance(response_payload, dict):
        return None

    candidate_paths = (
        ('key', 'id'),
        ('data', 'key', 'id'),
        ('message', 'key', 'id'),
        ('id',),
    )
    for path in candidate_paths:
        value: Any = response_payload
        for key in path:
            if not isinstance(value, dict):
                value = None
                break
            value = value.get(key)
        if value:
            return str(value)

    return None


def sanitize_message_send_error_code(error_code: str) -> str:
    sanitized = ''.join(
        char if char.isalnum() or char == '_' else '_'
        for char in str(error_code or EVOLUTION_UNKNOWN_ERROR).upper()
    )
    return sanitized[:64] or EVOLUTION_UNKNOWN_ERROR


def build_conversation_context_for_ai(
    conversation: Conversation,
    *,
    system_prompt: str,
) -> list[dict[str, str]]:
    """Monta as mensagens para IA sem consultar configuracoes de prompt."""
    recent_messages = list(
        Message.objects.filter(conversation=conversation)
        .order_by('-created_at')[:RECENT_AI_MESSAGES_LIMIT],
    )
    recent_messages.reverse()

    messages: list[dict[str, str]] = []
    if system_prompt:
        messages.append(
            {
                'role': 'system',
                'content': system_prompt,
            },
        )

    for message in recent_messages:
        role = 'user' if message.direction == Message.Direction.INBOUND else 'assistant'
        messages.append(
            {
                'role': role,
                'content': message.body,
            },
        )

    return messages


def _upsert_inbound_message(
    *,
    workspace_id: str,
    phone: str,
    contact_name: str,
    body: str,
    external_id: str | None,
    remote_jid: str | None = None,
    from_me: bool = False,
    message_type: str | None = None,
) -> None:
    """Cria ou reutiliza Contact/Conversation e persiste Message inbound."""
    with transaction.atomic():
        try:
            workspace = Workspace.objects.filter(id=workspace_id).first()
        except (TypeError, ValueError, ValidationError):
            workspace = None
        if workspace is None:
            logger.info(
                'Webhook WhatsApp ignorado: workspace inexistente',
                extra={'workspace_id': str(workspace_id)},
            )
            return

        contact, created = Contact.objects.get_or_create(
            workspace=workspace,
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
                workspace=workspace,
                contact=contact,
                channel=WHATSAPP_CHANNEL,
                status=Conversation.Status.OPEN,
            )

        message = Message.objects.create(
            conversation=conversation,
            body=body,
            direction=Message.Direction.INBOUND,
            status=Message.Status.DELIVERED,
            external_id=external_id,
        )
        message.ai_from_me = from_me
        message.ai_remote_jid = remote_jid
        message.ai_message_type = message_type

        should_schedule, reason_code = should_schedule_ai_response(
            workspace=workspace,
            conversation=conversation,
            message=message,
        )
        if should_schedule:
            schedule_ai_response_after_commit(
                conversation=conversation,
                source_message=message,
            )
            return

        logger.info(
            'Resposta automatica de IA nao agendada',
            extra={
                'workspace_id': str(workspace.id),
                'conversation_id': str(conversation.id),
                'message_id': str(message.id),
                'reason_code': reason_code,
            },
        )


def _process_evolution_message(data: dict[str, Any], workspace_id: str) -> None:
    """Processa um item `messages.upsert` da Evolution API."""
    key = data.get('key')
    if not isinstance(key, dict):
        return

    if key.get('fromMe') is True:
        _log_ai_schedule_skip(
            workspace_id=workspace_id,
            reason_code=AI_SKIP_MESSAGE_FROM_ME,
        )
        return

    remote_jid = key.get('remoteJid')
    if not remote_jid:
        return

    remote_jid = str(remote_jid)
    if remote_jid.endswith('@g.us'):
        _log_ai_schedule_skip(
            workspace_id=workspace_id,
            reason_code=AI_SKIP_UNSUPPORTED_GROUP_MESSAGE,
        )
        return

    message = data.get('message')
    if not isinstance(message, dict):
        return

    message_type = data.get('messageType')
    if message_type is None and len(message) == 1:
        message_type = next(iter(message.keys()))

    body = _extract_evolution_text(message)
    if not body:
        reason_code = (
            AI_SKIP_NON_PROCESSABLE_CONTENT
            if message_type in NON_PROCESSABLE_MESSAGE_TYPES
            else AI_SKIP_EMPTY_CONTENT
        )
        _log_ai_schedule_skip(
            workspace_id=workspace_id,
            reason_code=reason_code,
        )
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
        remote_jid=remote_jid,
        from_me=False,
        message_type=str(message_type) if message_type else None,
    )


def _log_ai_schedule_skip(*, workspace_id: str, reason_code: str) -> None:
    logger.info(
        'Resposta automatica de IA nao agendada',
        extra={
            'workspace_id': str(workspace_id),
            'reason_code': reason_code,
        },
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
        response = getattr(exc, 'response', None)
        logger.error(
            'Falha no envio pela Evolution API',
            extra={
                'operation': 'send_whatsapp_message',
                'status_code': getattr(response, 'status_code', None),
                'exception_type': type(exc).__name__,
                'instance_name': instance_name,
            },
        )
        raise
