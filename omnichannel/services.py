"""
Regras de negocio do omnichannel (handlers de provedores externos).
"""
from __future__ import annotations

import logging
import re
from typing import Any

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone

from omnichannel.ai.exceptions import (
    AIProviderAuthenticationError,
    AIProviderError,
    AIProviderInvalidRequestError,
    AIProviderInvalidResponseError,
    AIProviderRateLimitError,
    AIProviderTimeoutError,
    AIProviderUnavailableError,
    UnsupportedAIProviderError,
)
from omnichannel.ai.registry import is_provider_supported
from omnichannel.inbound_routing import resolve_inbound_whatsapp_contact
from workspaces.models import Workspace, WorkspaceAIProviderConfig

from .evolution import (
    EvolutionAPIError,
    EvolutionAuthenticationError,
    EvolutionConfigurationError,
    EvolutionConflictError,
    EvolutionConnectionError,
    EvolutionInvalidRequestError,
    EvolutionInvalidResponseError,
    EvolutionNotFoundError,
    EvolutionRateLimitError,
    EvolutionTimeoutError,
    EvolutionUnavailableError,
    get_evolution_client,
)
from .models import (
    AIObservabilityEvent,
    AIProcessingRun,
    Conversation,
    Message,
    WhatsAppChannel,
)
from .observability import record_ai_observability_event_safe
from .whatsapp_recipient_validation import (
    RECIPIENT_IS_CHANNEL_PHONE,
    validate_conversation_whatsapp_recipient,
)

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
AI_SKIP_RECIPIENT_UNRESOLVED = 'RECIPIENT_UNRESOLVED'
AI_SKIP_RECIPIENT_SELF = 'RECIPIENT_IS_CHANNEL_PHONE'
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
AI_PROCESSING_ALREADY_RETRYING = 'ALREADY_RETRYING'
AI_PROCESSING_ALREADY_FAILED = 'ALREADY_FAILED'
AI_PROCESSING_ALREADY_SKIPPED = 'ALREADY_SKIPPED'
MAX_AI_PROVIDER_ATTEMPTS = 3
MAX_OUTBOUND_DELIVERY_ATTEMPTS = 3
AI_RETRY_BASE_SECONDS = 60
OUTBOUND_RETRY_BASE_SECONDS = 60
EVOLUTION_TIMEOUT = 'EVOLUTION_TIMEOUT'
EVOLUTION_CONNECTION_ERROR = 'EVOLUTION_CONNECTION_ERROR'
EVOLUTION_REQUEST_ERROR = 'EVOLUTION_REQUEST_ERROR'
EVOLUTION_INVALID_RESPONSE = 'EVOLUTION_INVALID_RESPONSE'
EVOLUTION_CONFIGURATION_ERROR = 'EVOLUTION_CONFIGURATION_ERROR'
EVOLUTION_AUTHENTICATION_ERROR = 'EVOLUTION_AUTHENTICATION_ERROR'
EVOLUTION_RATE_LIMIT = 'EVOLUTION_RATE_LIMIT'
EVOLUTION_UNAVAILABLE = 'EVOLUTION_UNAVAILABLE'
EVOLUTION_INVALID_REQUEST = 'EVOLUTION_INVALID_REQUEST'
EVOLUTION_NOT_FOUND = 'EVOLUTION_NOT_FOUND'
EVOLUTION_CONFLICT = 'EVOLUTION_CONFLICT'
EVOLUTION_UNKNOWN_ERROR = 'EVOLUTION_UNKNOWN_ERROR'


def calculate_exponential_backoff(
    attempt_number: int,
    *,
    base_seconds: int = AI_RETRY_BASE_SECONDS,
) -> int:
    """Retorna backoff deterministico para facilitar testes e operacao."""
    try:
        safe_attempt = int(attempt_number)
    except (TypeError, ValueError):
        safe_attempt = 1
    safe_attempt = max(safe_attempt, 1)

    if safe_attempt == 1:
        multiplier = 1
    elif safe_attempt == 2:
        multiplier = 5
    else:
        multiplier = 15

    return max(int(base_seconds), 0) * multiplier


def is_retryable_ai_provider_error(exc: Exception) -> bool:
    return isinstance(
        exc,
        (
            AIProviderRateLimitError,
            AIProviderTimeoutError,
            AIProviderUnavailableError,
        ),
    )


def map_ai_provider_exception_to_error_code(exc: Exception) -> str:
    if isinstance(exc, AIProviderRateLimitError):
        return 'AI_PROVIDER_RATE_LIMIT'
    if isinstance(exc, AIProviderTimeoutError):
        return 'AI_PROVIDER_TIMEOUT'
    if isinstance(exc, AIProviderUnavailableError):
        return 'AI_PROVIDER_UNAVAILABLE'
    if isinstance(exc, AIProviderAuthenticationError):
        return 'AI_PROVIDER_AUTHENTICATION'
    if isinstance(exc, AIProviderInvalidRequestError):
        return 'AI_PROVIDER_INVALID_REQUEST'
    if isinstance(exc, UnsupportedAIProviderError):
        return 'UNSUPPORTED_PROVIDER'
    if isinstance(exc, AIProviderInvalidResponseError):
        return 'AI_PROVIDER_INVALID_RESPONSE'
    if isinstance(exc, AIProviderError):
        return 'AI_PROVIDER_ERROR'
    return _sanitize_ai_processing_error_code(type(exc).__name__)


def map_evolution_exception_to_error_code(exc: Exception) -> str:
    if isinstance(exc, EvolutionConfigurationError):
        return EVOLUTION_CONFIGURATION_ERROR
    if isinstance(exc, EvolutionAuthenticationError):
        return EVOLUTION_AUTHENTICATION_ERROR
    if isinstance(exc, EvolutionRateLimitError):
        return EVOLUTION_RATE_LIMIT
    if isinstance(exc, EvolutionTimeoutError):
        return EVOLUTION_TIMEOUT
    if isinstance(exc, EvolutionConnectionError):
        return EVOLUTION_CONNECTION_ERROR
    if isinstance(exc, EvolutionUnavailableError):
        return EVOLUTION_UNAVAILABLE
    if isinstance(exc, EvolutionInvalidRequestError):
        return EVOLUTION_INVALID_REQUEST
    if isinstance(exc, EvolutionNotFoundError):
        return EVOLUTION_NOT_FOUND
    if isinstance(exc, EvolutionConflictError):
        return EVOLUTION_CONFLICT
    if isinstance(exc, EvolutionInvalidResponseError):
        return EVOLUTION_INVALID_RESPONSE
    if isinstance(exc, EvolutionAPIError):
        return EVOLUTION_REQUEST_ERROR
    return EVOLUTION_UNKNOWN_ERROR


def is_retryable_evolution_error(exc: Exception) -> bool:
    return isinstance(exc, EvolutionAPIError) and bool(exc.retryable)


def _resolve_legacy_whatsapp_identity(
    remote_jid: object,
    *,
    remote_jid_alt: object = None,
) -> tuple[str, str] | None:
    """Separa identidade do provider e telefone no webhook legado."""
    if (
        not isinstance(remote_jid, str)
        or not remote_jid
        or remote_jid != remote_jid.strip()
        or remote_jid.count('@') != 1
    ):
        return None

    local, suffix = remote_jid.rsplit('@', maxsplit=1)
    if not local or not suffix:
        return None

    if suffix == 'lid':
        if re.fullmatch(r'\d{8,20}', local) is None:
            return None
        resolved_phone = _normalize_legacy_direct_phone_jid(remote_jid_alt) or ''
        return remote_jid, resolved_phone

    if suffix not in {'s.whatsapp.net', 'c.us'}:
        return None
    resolved_phone = _normalize_legacy_direct_phone_jid(remote_jid)
    if resolved_phone is None:
        return None
    return resolved_phone, resolved_phone


def _normalize_legacy_direct_phone_jid(value: object) -> str | None:
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or value.count('@') != 1
    ):
        return None
    local, suffix = value.rsplit('@', maxsplit=1)
    if suffix not in {'s.whatsapp.net', 'c.us'}:
        return None
    local = local.split(':', maxsplit=1)[0]
    candidate = local.lstrip('+')
    return candidate if re.fullmatch(r'\d{8,20}', candidate) else None


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

    recipient_validation = validate_conversation_whatsapp_recipient(conversation)
    if not recipient_validation.is_valid:
        reason_code = (
            AI_SKIP_RECIPIENT_SELF
            if recipient_validation.status == RECIPIENT_IS_CHANNEL_PHONE
            else AI_SKIP_RECIPIENT_UNRESOLVED
        )
        return False, reason_code

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
                attempt_count=0,
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
                AIProcessingRun.Status.RETRYING: AI_PROCESSING_ALREADY_RETRYING,
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
        locked_run.last_error_code = ''
        locked_run.next_retry_at = None
        locked_run.finished_at = timezone.now()
        locked_run.save(
            update_fields=[
                'status',
                'output_message',
                'error_code',
                'last_error_code',
                'next_retry_at',
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


def mark_ai_processing_attempt_started(
    *,
    run: AIProcessingRun,
) -> AIProcessingRun:
    """Registra uma tentativa real antes de chamar o provider de IA."""
    with transaction.atomic():
        locked_run = AIProcessingRun.objects.select_for_update().get(id=run.id)
        locked_run.status = AIProcessingRun.Status.RUNNING
        locked_run.attempt_count += 1
        locked_run.last_attempt_at = timezone.now()
        if locked_run.started_at is None:
            locked_run.started_at = locked_run.last_attempt_at
        locked_run.next_retry_at = None
        locked_run.save(
            update_fields=[
                'status',
                'attempt_count',
                'last_attempt_at',
                'started_at',
                'next_retry_at',
                'updated_at',
            ],
        )
        return locked_run


def mark_ai_processing_retrying(
    *,
    run: AIProcessingRun,
    error_code: str,
    next_retry_at,
) -> AIProcessingRun:
    sanitized_error_code = _sanitize_ai_processing_error_code(error_code)
    with transaction.atomic():
        locked_run = AIProcessingRun.objects.select_for_update().get(id=run.id)
        locked_run.status = AIProcessingRun.Status.RETRYING
        locked_run.last_error_code = sanitized_error_code
        locked_run.next_retry_at = next_retry_at
        locked_run.error_code = ''
        locked_run.finished_at = None
        locked_run.save(
            update_fields=[
                'status',
                'last_error_code',
                'next_retry_at',
                'error_code',
                'finished_at',
                'updated_at',
            ],
        )
        logger.info(
            'AIProcessingRun aguardando retry',
            extra={
                'workspace_id': str(locked_run.workspace_id),
                'conversation_id': str(locked_run.conversation_id),
                'source_message_id': str(locked_run.source_message_id),
                'ai_processing_run_id': str(locked_run.id),
                'status': locked_run.status,
                'error_code': locked_run.last_error_code,
                'attempt_count': locked_run.attempt_count,
            },
        )
        return locked_run


def can_retry_ai_processing(
    *,
    run: AIProcessingRun,
    max_attempts: int = MAX_AI_PROVIDER_ATTEMPTS,
) -> bool:
    return run.attempt_count < max_attempts


def get_retryable_ai_processing_run(
    *,
    run_id: str,
    source_message: Message,
) -> AIProcessingRun | None:
    try:
        with transaction.atomic():
            run = AIProcessingRun.objects.select_for_update().get(id=run_id)
            if run.source_message_id != source_message.id:
                return None
            if run.conversation_id != source_message.conversation_id:
                return None
            if run.workspace_id != source_message.conversation.workspace_id:
                return None
            if run.status not in (
                AIProcessingRun.Status.RUNNING,
                AIProcessingRun.Status.RETRYING,
            ):
                return None
            return run
    except (AIProcessingRun.DoesNotExist, TypeError, ValueError, ValidationError):
        return None


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
        locked_run.next_retry_at = None
        locked_run.finished_at = timezone.now()
        locked_run.save(
            update_fields=[
                'status',
                'error_code',
                'next_retry_at',
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
    sanitized = _redact_sensitive_error_code_fragments(sanitized)
    return sanitized[:64] or 'UNKNOWN_ERROR'


def create_pending_outbound_message(
    *,
    conversation: Conversation,
    body: str,
) -> Message:
    """Persist an outbound message before any external delivery attempt."""
    return Message.objects.create(
        conversation=conversation,
        body=body,
        direction=Message.Direction.OUTBOUND,
        status=Message.Status.PENDING,
        external_id=None,
        send_error_code='',
    )


def create_pending_ai_message(
    *,
    conversation: Conversation,
    body: str,
) -> Message:
    """Compatibility wrapper for AI-generated outbound messages."""
    return create_pending_outbound_message(
        conversation=conversation,
        body=body,
    )


def schedule_outbound_message_after_commit(*, message: Message) -> None:
    """Schedule delivery with technical identifiers only after DB commit."""
    if message.pk is None or message.direction != Message.Direction.OUTBOUND:
        raise ValueError('A persisted outbound message is required for delivery.')

    message_id = str(message.id)
    channel_id = message.conversation.whatsapp_channel_id
    expected_channel_id = str(channel_id) if channel_id is not None else None
    workspace_id = str(message.conversation.workspace_id)
    conversation_id = str(message.conversation_id)

    def _enqueue() -> None:
        from omnichannel.tasks import send_outbound_whatsapp_message

        try:
            send_outbound_whatsapp_message.delay(
                message_id,
                expected_channel_id,
            )
        except Exception as exc:
            logger.warning(
                'Falha ao agendar delivery outbound',
                extra={
                    'workspace_id': workspace_id,
                    'conversation_id': conversation_id,
                    'message_id': message_id,
                    'whatsapp_channel_id': expected_channel_id or '',
                    'error_code': 'OUTBOUND_DELIVERY_ENQUEUE_FAILED',
                    'exception_type': type(exc).__name__,
                },
            )

    transaction.on_commit(_enqueue)


def claim_message_delivery_attempt(*, message_id) -> Message | None:
    """Atomically claim a still-pending Message and count one HTTP attempt."""
    with transaction.atomic():
        locked_message = Message.objects.select_for_update(of=('self',)).select_related(
            'conversation',
            'conversation__contact',
            'conversation__workspace',
            'conversation__whatsapp_channel',
        ).get(id=message_id)
        if locked_message.status != Message.Status.PENDING:
            return None

        locked_message.send_attempt_count += 1
        locked_message.last_send_attempt_at = timezone.now()
        locked_message.next_send_retry_at = None
        locked_message.save(
            update_fields=[
                'send_attempt_count',
                'last_send_attempt_at',
                'next_send_retry_at',
                'updated_at',
            ],
        )
        return locked_message


def mark_message_delivery_attempt_started(
    *,
    message: Message,
) -> Message:
    """Backward-compatible wrapper around the conditional delivery claim."""
    with transaction.atomic():
        locked_message = Message.objects.select_for_update().get(id=message.id)
        if locked_message.status != Message.Status.PENDING:
            return locked_message

        locked_message.send_attempt_count += 1
        locked_message.last_send_attempt_at = timezone.now()
        locked_message.next_send_retry_at = None
        locked_message.save(
            update_fields=[
                'send_attempt_count',
                'last_send_attempt_at',
                'next_send_retry_at',
                'updated_at',
            ],
        )
        return locked_message


def mark_message_delivery_retrying(
    *,
    message: Message,
    error_code: str,
    next_retry_at,
) -> Message:
    with transaction.atomic():
        locked_message = Message.objects.select_for_update().get(id=message.id)
        if locked_message.status != Message.Status.PENDING:
            return locked_message

        locked_message.send_error_code = sanitize_message_send_error_code(error_code)
        locked_message.next_send_retry_at = next_retry_at
        locked_message.save(
            update_fields=[
                'send_error_code',
                'next_send_retry_at',
                'updated_at',
            ],
        )
        return locked_message


def can_retry_message_delivery(
    *,
    message: Message,
    max_attempts: int = MAX_OUTBOUND_DELIVERY_ATTEMPTS,
) -> bool:
    return message.send_attempt_count < max_attempts


def mark_message_as_sent(
    *,
    message: Message,
    external_id: str | None = None,
) -> Message:
    with transaction.atomic():
        locked_message = Message.objects.select_for_update().get(id=message.id)
        update_fields: list[str] = []

        if locked_message.status in {Message.Status.PENDING, Message.Status.FAILED}:
            locked_message.status = Message.Status.SENT
            update_fields.append('status')

        if external_id and not locked_message.external_id:
            locked_message.external_id = external_id
            update_fields.append('external_id')

        if locked_message.status in {
            Message.Status.SENT,
            Message.Status.DELIVERED,
            Message.Status.READ,
        }:
            if locked_message.send_error_code:
                locked_message.send_error_code = ''
                update_fields.append('send_error_code')
            if locked_message.next_send_retry_at is not None:
                locked_message.next_send_retry_at = None
                update_fields.append('next_send_retry_at')

        if update_fields:
            locked_message.save(update_fields=[*update_fields, 'updated_at'])
        return locked_message


def mark_message_as_failed(
    *,
    message: Message,
    error_code: str,
) -> Message:
    with transaction.atomic():
        locked_message = Message.objects.select_for_update().get(id=message.id)
        if locked_message.status != Message.Status.PENDING:
            return locked_message

        locked_message.status = Message.Status.FAILED
        locked_message.send_error_code = sanitize_message_send_error_code(error_code)
        locked_message.next_send_retry_at = None
        locked_message.save(
            update_fields=[
                'status',
                'send_error_code',
                'next_send_retry_at',
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
    sanitized = _redact_sensitive_error_code_fragments(sanitized)
    return sanitized[:64] or EVOLUTION_UNKNOWN_ERROR


def _redact_sensitive_error_code_fragments(error_code: str) -> str:
    redacted = re.sub(r'SK_[A-Z0-9_]*', 'REDACTED', error_code)
    for fragment in (
        'OPENAI_API_KEY',
        'API_KEY',
        'AUTHORIZATION',
        'HEADER',
        'RAW_PAYLOAD',
        'PAYLOAD',
    ):
        redacted = redacted.replace(fragment, 'REDACTED')
    return redacted


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


def handle_inbound_ai_scheduling(
    *,
    workspace: Workspace,
    conversation: Conversation,
    message: Message,
    remote_jid: str | None,
    from_me: bool,
    message_type: str | None,
) -> tuple[bool, str | None]:
    """Preserva a decisao, observabilidade e fila de IA dos fluxos inbound."""
    message.ai_from_me = from_me
    message.ai_remote_jid = remote_jid
    message.ai_message_type = message_type

    should_schedule, reason_code = should_schedule_ai_response(
        workspace=workspace,
        conversation=conversation,
        message=message,
    )
    provider_config = _get_active_provider_config_for_observability(workspace)
    _record_ai_schedule_observability_after_commit(
        workspace=workspace,
        conversation=conversation,
        message=message,
        provider_config=provider_config,
        event_type=(
            AIObservabilityEvent.EventType.AI_SCHEDULED
            if should_schedule
            else AIObservabilityEvent.EventType.AI_SKIPPED
        ),
        status=(
            AIObservabilityEvent.Status.PENDING
            if should_schedule
            else AIObservabilityEvent.Status.SKIPPED
        ),
        reason_code='' if should_schedule else reason_code or 'UNKNOWN_SKIP',
        metadata=_build_ai_schedule_metadata(
            message_type=message_type,
            direction=message.direction,
            from_me=from_me,
            is_group=isinstance(remote_jid, str) and remote_jid.endswith('@g.us'),
            provider_config=provider_config,
        ),
    )
    if should_schedule:
        schedule_ai_response_after_commit(
            conversation=conversation,
            source_message=message,
        )
        return True, None

    logger.info(
        'Resposta automatica de IA nao agendada',
        extra={
            'workspace_id': str(workspace.id),
            'conversation_id': str(conversation.id),
            'message_id': str(message.id),
            'reason_code': reason_code,
        },
    )
    return False, reason_code


def _upsert_inbound_message(
    *,
    workspace_id: str,
    provider_identity: str,
    resolved_phone: str,
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

        contact = resolve_inbound_whatsapp_contact(
            workspace_id=workspace.id,
            provider_identity=provider_identity,
            resolved_phone=resolved_phone,
            contact_name=contact_name,
        )

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
        handle_inbound_ai_scheduling(
            workspace=workspace,
            conversation=conversation,
            message=message,
            remote_jid=remote_jid,
            from_me=from_me,
            message_type=message_type,
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
            metadata={
                'source': 'webhook',
                'from_me': True,
                'is_group': False,
            },
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
            metadata={
                'source': 'webhook',
                'from_me': False,
                'is_group': True,
            },
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
            metadata={
                'source': 'webhook',
                'message_type': str(message_type or ''),
                'from_me': False,
                'is_group': False,
            },
        )
        return

    remote_jid_alt = key.get('remoteJidAlt')
    if remote_jid_alt is None:
        remote_jid_alt = data.get('remoteJidAlt')
    identity = _resolve_legacy_whatsapp_identity(
        remote_jid,
        remote_jid_alt=remote_jid_alt,
    )
    if identity is None:
        return
    provider_identity, resolved_phone = identity
    contact_name = str(data.get('pushName') or resolved_phone or provider_identity)
    external_id = key.get('id')

    _upsert_inbound_message(
        workspace_id=workspace_id,
        provider_identity=provider_identity,
        resolved_phone=resolved_phone,
        contact_name=contact_name,
        body=body,
        external_id=str(external_id) if external_id else None,
        remote_jid=remote_jid,
        from_me=False,
        message_type=str(message_type) if message_type else None,
    )


def _log_ai_schedule_skip(
    *,
    workspace_id: str,
    reason_code: str,
    metadata: dict[str, Any] | None = None,
) -> None:
    logger.info(
        'Resposta automatica de IA nao agendada',
        extra={
            'workspace_id': str(workspace_id),
            'reason_code': reason_code,
        },
    )
    try:
        workspace = Workspace.objects.filter(id=workspace_id).first()
    except (TypeError, ValueError, ValidationError):
        workspace = None

    if workspace is not None:
        record_ai_observability_event_safe(
            workspace=workspace,
            event_type=AIObservabilityEvent.EventType.AI_SKIPPED,
            status=AIObservabilityEvent.Status.SKIPPED,
            reason_code=reason_code,
            metadata={'source': 'webhook', **(metadata or {})},
        )


def _get_active_provider_config_for_observability(
    workspace: Workspace,
) -> WorkspaceAIProviderConfig | None:
    return (
        WorkspaceAIProviderConfig.objects.filter(
            workspace=workspace,
            is_active=True,
        )
        .only('api_key', 'provider', 'model_name')
        .first()
    )


def _build_ai_schedule_metadata(
    *,
    message_type: str | None,
    direction: str,
    from_me: bool,
    is_group: bool,
    provider_config: WorkspaceAIProviderConfig | None,
) -> dict[str, Any]:
    return {
        'source': 'webhook',
        'message_type': message_type or '',
        'direction': direction,
        'from_me': bool(from_me),
        'is_group': bool(is_group),
        'provider_supported': (
            is_provider_supported(provider_config.provider)
            if provider_config is not None
            else False
        ),
        'has_api_key': bool(getattr(provider_config, 'api_key', '')),
    }


def _record_ai_schedule_observability_after_commit(
    *,
    workspace: Workspace,
    conversation: Conversation,
    message: Message,
    provider_config: WorkspaceAIProviderConfig | None,
    event_type: str,
    status: str,
    reason_code: str,
    metadata: dict[str, Any],
) -> None:
    transaction.on_commit(
        lambda: record_ai_observability_event_safe(
            workspace=workspace,
            provider_config=provider_config,
            conversation=conversation,
            source_message=message,
            event_type=event_type,
            status=status,
            provider=getattr(provider_config, 'provider', ''),
            model_name=getattr(provider_config, 'model_name', ''),
            reason_code=reason_code,
            metadata=metadata,
        ),
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

    if state == 'close':
        logger.warning('Evolution desconectada', extra={'status': str(state or '')})
        return

    logger.info(
        'Evolution connection.update',
        extra={'status': str(state or '')},
    )


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


def send_whatsapp_message(
    *,
    channel: WhatsAppChannel,
    phone: str,
    text: str,
) -> dict[str, Any]:
    """Envia texto pelo client central usando a instancia persistida do canal."""
    client = get_evolution_client()
    return client.send_text(
        instance_name=channel.instance_name,
        number=phone,
        text=text,
    )
