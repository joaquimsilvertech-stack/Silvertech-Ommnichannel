from __future__ import annotations

import hashlib
import json
import logging
import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Callable
from uuid import UUID

from django.conf import settings
from django.db import DatabaseError, IntegrityError, transaction
from django.utils import timezone

from omnichannel.evolution_qr_cache import (
    EvolutionQRCodeCacheError,
    delete_evolution_qr_code,
    extract_evolution_qr_code,
    store_evolution_qr_code,
)
from omnichannel.inbound_routing import resolve_inbound_whatsapp_route
from omnichannel.models import (
    AIObservabilityEvent,
    Conversation,
    EvolutionWebhookEvent,
    Message,
    WhatsAppChannel,
)
from omnichannel.observability import (
    CONNECTION_ERROR_REASON,
    record_channel_observability_event_safe,
)

logger = logging.getLogger(__name__)

# Mapa de status de conexao -> evento de observabilidade de ciclo de vida.
_CONNECTION_OBSERVABILITY_EVENTS = {
    WhatsAppChannel.Status.CONNECTED: AIObservabilityEvent.EventType.CHANNEL_CONNECTED,
    WhatsAppChannel.Status.DISCONNECTED: AIObservabilityEvent.EventType.CHANNEL_DISCONNECTED,
    WhatsAppChannel.Status.ERROR: AIObservabilityEvent.EventType.CHANNEL_ERROR,
}

QRCODE_UPDATED = 'QRCODE_UPDATED'
CONNECTION_UPDATE = 'CONNECTION_UPDATE'
MESSAGES_UPSERT = 'MESSAGES_UPSERT'
MESSAGES_UPDATE = 'MESSAGES_UPDATE'
SEND_MESSAGE = 'SEND_MESSAGE'
SEND_MESSAGE_UPDATE = 'SEND_MESSAGE_UPDATE'
UNSUPPORTED_EVENT = 'UNSUPPORTED_EVENT'
MESSAGE_STATUS_EVENT = 'MESSAGE_STATUS'

SUPPORTED_EVENT_TYPES = {
    QRCODE_UPDATED,
    CONNECTION_UPDATE,
    MESSAGES_UPSERT,
    MESSAGES_UPDATE,
    SEND_MESSAGE,
    SEND_MESSAGE_UPDATE,
}

_CONNECTION_STATE_MAP = {
    'open': WhatsAppChannel.Status.CONNECTED,
    'connected': WhatsAppChannel.Status.CONNECTED,
    'connecting': WhatsAppChannel.Status.CONNECTING,
    'reconnecting': WhatsAppChannel.Status.RECONNECTING,
    'close': WhatsAppChannel.Status.DISCONNECTED,
    'closed': WhatsAppChannel.Status.DISCONNECTED,
    'disconnected': WhatsAppChannel.Status.DISCONNECTED,
    'qr': WhatsAppChannel.Status.WAITING_QR,
    'qrcode': WhatsAppChannel.Status.WAITING_QR,
    'waiting_qr': WhatsAppChannel.Status.WAITING_QR,
    'error': WhatsAppChannel.Status.ERROR,
}

_MESSAGE_STATUS_MAP = {
    'PENDING': Message.Status.PENDING,
    'SENT': Message.Status.SENT,
    'SERVER_ACK': Message.Status.SENT,
    'DELIVERED': Message.Status.DELIVERED,
    'DELIVERY_ACK': Message.Status.DELIVERED,
    'READ': Message.Status.READ,
    'READ_ACK': Message.Status.READ,
    'PLAYED': Message.Status.READ,
    'FAILED': Message.Status.FAILED,
    'ERROR': Message.Status.FAILED,
}

_STATUS_RANK = {
    Message.Status.PENDING: 0,
    Message.Status.SENT: 1,
    Message.Status.DELIVERED: 2,
    Message.Status.READ: 3,
}

_SAFE_EXTERNAL_REASON = re.compile(r'^[A-Za-z][A-Za-z0-9_.-]{0,63}$')
_SAFE_TIMESTAMP = re.compile(r'^[0-9TZ:+.\-]{1,64}$')
_PHONE_PATTERN = re.compile(r'^\d{8,20}$')
_DIRECT_INDIVIDUAL_JID_SUFFIXES = {'s.whatsapp.net', 'c.us'}
_INDIVIDUAL_JID_SUFFIXES = {*_DIRECT_INDIVIDUAL_JID_SUFFIXES, 'lid'}


class EvolutionEventProcessingError(Exception):
    """Erro operacional sem conteudo recebido ou credencial em sua mensagem."""

    def __init__(
        self,
        error_code: str,
        *,
        retryable: bool,
        event_id: UUID | str | None = None,
    ) -> None:
        super().__init__('Evolution event processing failed.')
        self.error_code = _sanitize_error_code(error_code)
        self.retryable = bool(retryable)
        self.event_id = str(event_id) if event_id is not None else None


@dataclass(frozen=True)
class EvolutionEventClaim:
    event: EvolutionWebhookEvent
    should_process: bool
    duplicate: bool


@dataclass(frozen=True)
class _InboundMessageData:
    external_id: str
    remote_jid: str
    provider_identity: str
    resolved_phone: str
    body: str
    contact_name: str
    message_type: str | None


def normalize_evolution_event_type(value: object) -> str:
    if not isinstance(value, str):
        return UNSUPPORTED_EVENT
    normalized = re.sub(r'[^A-Z0-9]+', '_', value.strip().upper()).strip('_')
    if normalized in SUPPORTED_EVENT_TYPES:
        return normalized
    return UNSUPPORTED_EVENT


def normalize_evolution_message_status(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = re.sub(r'[^A-Z0-9]+', '_', value.strip().upper()).strip('_')
    return _MESSAGE_STATUS_MAP.get(normalized)


def build_event_deduplication_key(*parts: object) -> str:
    canonical = json.dumps(
        parts,
        sort_keys=True,
        separators=(',', ':'),
        ensure_ascii=False,
        default=lambda value: type(value).__name__,
    ).encode('utf-8')
    return hashlib.sha256(canonical).hexdigest()


def build_provider_message_key(
    channel_id: UUID | str,
    external_id: str,
) -> str:
    source = f'evolution:{channel_id}:{external_id}'.encode('utf-8')
    return hashlib.sha256(source).hexdigest()


def claim_evolution_event(
    *,
    channel: WhatsAppChannel,
    event_type: str,
    deduplication_key: str,
    external_id: str = '',
) -> EvolutionEventClaim:
    now = timezone.now()
    stale_seconds = _positive_stale_seconds()
    stale_before = now - timedelta(seconds=stale_seconds)

    try:
        with transaction.atomic():
            event = (
                EvolutionWebhookEvent.objects.select_for_update()
                .filter(
                    whatsapp_channel=channel,
                    deduplication_key=deduplication_key,
                )
                .first()
            )
            if event is None:
                try:
                    with transaction.atomic():
                        event = EvolutionWebhookEvent.objects.create(
                            whatsapp_channel=channel,
                            event_type=event_type[:64],
                            deduplication_key=deduplication_key,
                            external_id=external_id[:255],
                            status=EvolutionWebhookEvent.Status.PROCESSING,
                            attempt_count=1,
                            started_at=now,
                        )
                    return EvolutionEventClaim(event, True, False)
                except IntegrityError:
                    event = EvolutionWebhookEvent.objects.select_for_update().get(
                        whatsapp_channel=channel,
                        deduplication_key=deduplication_key,
                    )

            if event.status in {
                EvolutionWebhookEvent.Status.PROCESSED,
                EvolutionWebhookEvent.Status.IGNORED,
            }:
                return EvolutionEventClaim(event, False, True)

            if (
                event.status == EvolutionWebhookEvent.Status.PROCESSING
                and event.started_at > stale_before
            ):
                return EvolutionEventClaim(event, False, True)

            if event.status in {
                EvolutionWebhookEvent.Status.FAILED,
                EvolutionWebhookEvent.Status.PROCESSING,
            }:
                event.status = EvolutionWebhookEvent.Status.PROCESSING
                event.attempt_count += 1
                event.error_code = ''
                event.started_at = now
                event.finished_at = None
                if external_id and not event.external_id:
                    event.external_id = external_id[:255]
                event.save(
                    update_fields=[
                        'status',
                        'attempt_count',
                        'error_code',
                        'started_at',
                        'finished_at',
                        'external_id',
                        'updated_at',
                    ],
                )
                return EvolutionEventClaim(event, True, False)

            return EvolutionEventClaim(event, False, True)
    except EvolutionEventProcessingError:
        raise
    except DatabaseError as exc:
        raise EvolutionEventProcessingError(
            'EVENT_RECEIPT_UNAVAILABLE',
            retryable=True,
        ) from exc


def mark_evolution_event_processed(
    event: EvolutionWebhookEvent,
) -> EvolutionWebhookEvent:
    return _mark_evolution_event_finished(
        event=event,
        status=EvolutionWebhookEvent.Status.PROCESSED,
        error_code='',
    )


def mark_evolution_event_ignored(
    event: EvolutionWebhookEvent,
    *,
    error_code: str,
) -> EvolutionWebhookEvent:
    return _mark_evolution_event_finished(
        event=event,
        status=EvolutionWebhookEvent.Status.IGNORED,
        error_code=error_code,
    )


def mark_evolution_event_failed(
    event: EvolutionWebhookEvent,
    *,
    error_code: str,
) -> EvolutionWebhookEvent:
    return _mark_evolution_event_finished(
        event=event,
        status=EvolutionWebhookEvent.Status.FAILED,
        error_code=error_code,
    )


def process_evolution_channel_event(
    *,
    channel: WhatsAppChannel,
    payload: dict[str, Any],
) -> None:
    if not isinstance(payload, dict):
        return None

    event_type = normalize_evolution_event_type(payload.get('event'))
    if event_type == QRCODE_UPDATED:
        process_qrcode_updated(channel=channel, payload=payload)
    elif event_type == CONNECTION_UPDATE:
        process_connection_update(channel=channel, payload=payload)
    elif event_type == MESSAGES_UPSERT:
        process_messages_upsert(channel=channel, payload=payload)
    elif event_type in {MESSAGES_UPDATE, SEND_MESSAGE, SEND_MESSAGE_UPDATE}:
        process_message_status_update(
            channel=channel,
            payload=payload,
            event_type=event_type,
        )
    else:
        _process_unsupported_event(channel=channel, payload=payload)
    return None


def process_qrcode_updated(
    *,
    channel: WhatsAppChannel,
    payload: dict[str, Any],
) -> None:
    qr_code = extract_evolution_qr_code(payload)
    key_material = qr_code if qr_code is not None else _canonical_digest(payload)
    claim = claim_evolution_event(
        channel=channel,
        event_type=QRCODE_UPDATED,
        deduplication_key=build_event_deduplication_key(
            QRCODE_UPDATED,
            str(channel.id),
            key_material,
        ),
    )

    if not claim.should_process:
        current_status = WhatsAppChannel.objects.filter(id=channel.id).values_list(
            'status',
            flat=True,
        ).first()
        if (
            claim.event.status == EvolutionWebhookEvent.Status.PROCESSED
            and current_status == WhatsAppChannel.Status.WAITING_QR
            and qr_code is not None
        ):
            try:
                store_evolution_qr_code(channel.id, qr_code)
            except EvolutionQRCodeCacheError:
                logger.warning(
                    'Falha ao renovar QR duplicado no cache',
                    extra=_event_log_context(claim.event, error_code='QR_CACHE_UNAVAILABLE'),
                )
        return

    def _handle(event: EvolutionWebhookEvent) -> None:
        if qr_code is None:
            mark_evolution_event_ignored(event, error_code='INVALID_QR_CODE')
            return

        current_status = WhatsAppChannel.objects.filter(id=channel.id).values_list(
            'status',
            flat=True,
        ).first()
        if current_status == WhatsAppChannel.Status.CONNECTED:
            mark_evolution_event_ignored(event, error_code='CHANNEL_ALREADY_CONNECTED')
            return

        try:
            store_evolution_qr_code(channel.id, qr_code)
        except EvolutionQRCodeCacheError as exc:
            raise EvolutionEventProcessingError(
                exc.error_code,
                retryable=exc.error_code != 'INVALID_QR_CODE',
                event_id=event.id,
            ) from exc

        remove_cached_qr = False
        try:
            with transaction.atomic():
                locked_event = EvolutionWebhookEvent.objects.select_for_update().get(id=event.id)
                locked_channel = WhatsAppChannel.objects.select_for_update().get(id=channel.id)
                if locked_channel.status == WhatsAppChannel.Status.CONNECTED:
                    remove_cached_qr = True
                    _finish_locked_event(
                        locked_event,
                        status=EvolutionWebhookEvent.Status.IGNORED,
                        error_code='CHANNEL_ALREADY_CONNECTED',
                    )
                else:
                    locked_channel.status = WhatsAppChannel.Status.WAITING_QR
                    locked_channel.last_error_code = ''
                    locked_channel.last_connection_update_at = timezone.now()
                    locked_channel.save(
                        update_fields=[
                            'status',
                            'last_error_code',
                            'last_connection_update_at',
                            'updated_at',
                        ],
                    )
                    _finish_locked_event(
                        locked_event,
                        status=EvolutionWebhookEvent.Status.PROCESSED,
                        error_code='',
                    )
        except Exception:
            _delete_qr_best_effort(channel_id=channel.id, event=event)
            raise
        if remove_cached_qr:
            _delete_qr_best_effort(channel_id=channel.id, event=event)

    _run_claimed_event(claim, _handle)


def process_connection_update(
    *,
    channel: WhatsAppChannel,
    payload: dict[str, Any],
) -> None:
    state = _extract_connection_state(payload)
    target_status = _CONNECTION_STATE_MAP.get(state)
    timestamp = _extract_external_timestamp(payload)
    data = payload.get('data')
    claim = claim_evolution_event(
        channel=channel,
        event_type=CONNECTION_UPDATE,
        deduplication_key=build_event_deduplication_key(
            CONNECTION_UPDATE,
            str(channel.id),
            state or 'UNKNOWN_STATE',
            timestamp or _canonical_digest(data),
        ),
    )
    if not claim.should_process:
        return

    def _handle(event: EvolutionWebhookEvent) -> None:
        if target_status is None:
            mark_evolution_event_ignored(event, error_code='UNSUPPORTED_CONNECTION_STATE')
            return

        remove_qr = False
        with transaction.atomic():
            locked_event = EvolutionWebhookEvent.objects.select_for_update().get(id=event.id)
            locked_channel = WhatsAppChannel.objects.select_for_update().get(id=channel.id)
            if (
                locked_channel.status == WhatsAppChannel.Status.CONNECTED
                and target_status in {
                    WhatsAppChannel.Status.CONNECTING,
                    WhatsAppChannel.Status.WAITING_QR,
                }
            ):
                _finish_locked_event(
                    locked_event,
                    status=EvolutionWebhookEvent.Status.IGNORED,
                    error_code='STALE_CONNECTION_STATE',
                )
                return

            now = timezone.now()
            update_fields = ['status', 'last_connection_update_at', 'updated_at']
            locked_channel.status = target_status
            locked_channel.last_connection_update_at = now

            if target_status == WhatsAppChannel.Status.CONNECTED:
                if locked_channel.connected_at is None:
                    locked_channel.connected_at = now
                    update_fields.append('connected_at')
                locked_channel.last_error_code = ''
                update_fields.append('last_error_code')
                phone_number = _extract_phone_number(payload)
                if phone_number is not None:
                    locked_channel.phone_number = phone_number
                    update_fields.append('phone_number')
                remove_qr = True
            elif target_status == WhatsAppChannel.Status.ERROR:
                locked_channel.last_error_code = _extract_connection_error_code(payload)
                update_fields.append('last_error_code')
            elif target_status == WhatsAppChannel.Status.DISCONNECTED:
                remove_qr = True

            locked_channel.save(update_fields=list(dict.fromkeys(update_fields)))
            _finish_locked_event(
                locked_event,
                status=EvolutionWebhookEvent.Status.PROCESSED,
                error_code='',
            )

        if remove_qr:
            _delete_qr_best_effort(channel_id=channel.id, event=event)

        observability_event = _CONNECTION_OBSERVABILITY_EVENTS.get(target_status)
        if observability_event is not None:
            is_error = target_status == WhatsAppChannel.Status.ERROR
            record_channel_observability_event_safe(
                workspace=channel.workspace,
                channel=channel,
                event_type=observability_event,
                status=(
                    AIObservabilityEvent.Status.FAILED
                    if is_error
                    else AIObservabilityEvent.Status.SUCCESS
                ),
                reason_code=CONNECTION_ERROR_REASON if is_error else '',
                metadata={'action': 'connection_update'},
            )

    _run_claimed_event(claim, _handle)


def process_messages_upsert(
    *,
    channel: WhatsAppChannel,
    payload: dict[str, Any],
) -> None:
    for item in _event_items(payload):
        _process_messages_upsert_item(channel=channel, item=item)


def process_message_status_update(
    *,
    channel: WhatsAppChannel,
    payload: dict[str, Any],
    event_type: str,
) -> None:
    for item in _event_items(payload):
        _process_message_status_item(
            channel=channel,
            item=item,
            event_type=event_type,
        )


def advance_outbound_message_status(
    *,
    message: Message,
    target_status: str,
    error_code: str = 'EVOLUTION_DELIVERY_FAILED',
) -> Message:
    with transaction.atomic():
        locked_message = Message.objects.select_for_update().get(id=message.id)
        accepted, changed = _apply_outbound_status_transition(
            message=locked_message,
            target_status=target_status,
            error_code=error_code,
        )
        if accepted and changed:
            locked_message.save(
                update_fields=[
                    'status',
                    'send_error_code',
                    'next_send_retry_at',
                    'updated_at',
                ],
            )
        return locked_message


def _process_messages_upsert_item(
    *,
    channel: WhatsAppChannel,
    item: object,
) -> None:
    parsed, validation_error = _parse_inbound_message(item)
    external_id = parsed.external_id if parsed is not None else _extract_external_id(item)
    deduplication_material = (
        external_id
        if external_id is not None
        else f'INVALID:{_canonical_digest(item)}'
    )
    claim = claim_evolution_event(
        channel=channel,
        event_type=MESSAGES_UPSERT,
        deduplication_key=build_event_deduplication_key(
            MESSAGES_UPSERT,
            str(channel.id),
            deduplication_material,
        ),
        external_id=external_id or '',
    )
    if not claim.should_process:
        return

    def _handle(event: EvolutionWebhookEvent) -> None:
        if parsed is None:
            mark_evolution_event_ignored(
                event,
                error_code=validation_error or 'INVALID_MESSAGE_ITEM',
            )
            return
        _create_inbound_message(channel=channel, event=event, parsed=parsed)

    _run_claimed_event(claim, _handle)


def _create_inbound_message(
    *,
    channel: WhatsAppChannel,
    event: EvolutionWebhookEvent,
    parsed: _InboundMessageData,
) -> None:
    from omnichannel.services import handle_inbound_ai_scheduling

    provider_key = build_provider_message_key(channel.id, parsed.external_id)
    with transaction.atomic():
        locked_event = EvolutionWebhookEvent.objects.select_for_update().get(id=event.id)
        locked_channel = WhatsAppChannel.objects.select_for_update().get(id=channel.id)
        if locked_channel.status == WhatsAppChannel.Status.DELETING:
            _finish_locked_event(
                locked_event,
                status=EvolutionWebhookEvent.Status.IGNORED,
                error_code='CHANNEL_DELETING',
            )
            return

        scoped_messages = Message.objects.filter(
            conversation__workspace_id=locked_channel.workspace_id,
            conversation__whatsapp_channel=locked_channel,
        )
        if scoped_messages.filter(provider_message_key=provider_key).exists():
            _finish_locked_event(
                locked_event,
                status=EvolutionWebhookEvent.Status.IGNORED,
                error_code='DUPLICATE_MESSAGE',
            )
            return

        route = resolve_inbound_whatsapp_route(
            channel=locked_channel,
            provider_identity=parsed.provider_identity,
            resolved_phone=parsed.resolved_phone,
            contact_name=parsed.contact_name,
        )
        contact = route.contact
        conversation = route.conversation

        try:
            with transaction.atomic():
                message = Message.objects.create(
                    conversation=conversation,
                    body=parsed.body,
                    direction=Message.Direction.INBOUND,
                    status=Message.Status.DELIVERED,
                    external_id=parsed.external_id,
                    provider_message_key=provider_key,
                )
        except IntegrityError:
            if scoped_messages.filter(provider_message_key=provider_key).exists():
                _finish_locked_event(
                    locked_event,
                    status=EvolutionWebhookEvent.Status.IGNORED,
                    error_code='DUPLICATE_MESSAGE',
                )
                return
            raise

        handle_inbound_ai_scheduling(
            workspace=locked_channel.workspace,
            conversation=conversation,
            message=message,
            remote_jid=parsed.remote_jid,
            from_me=False,
            message_type=parsed.message_type,
        )
        _finish_locked_event(
            locked_event,
            status=EvolutionWebhookEvent.Status.PROCESSED,
            error_code='',
        )

    # Volume inbound por canal — SEM body nem telefone (apenas contadores/tipo).
    record_channel_observability_event_safe(
        workspace=channel.workspace,
        channel=channel,
        event_type=AIObservabilityEvent.EventType.CHANNEL_INBOUND_RECEIVED,
        status=AIObservabilityEvent.Status.SUCCESS,
        metadata={
            'action': 'inbound',
            'direction': 'inbound',
            'message_type': parsed.message_type,
        },
    )

    logger.info(
        'Mensagem inbound Evolution processada',
        extra={
            **_event_log_context(event, status=EvolutionWebhookEvent.Status.PROCESSED),
            'contact_id': str(contact.id),
            'message_id': str(message.id),
            'conversation_id': str(conversation.id),
        },
    )


def _process_message_status_item(
    *,
    channel: WhatsAppChannel,
    item: object,
    event_type: str,
) -> None:
    external_id = _extract_external_id(item)
    target_status = _extract_message_status(item)
    if external_id is not None and target_status is not None:
        key_parts = (MESSAGE_STATUS_EVENT, str(channel.id), external_id, target_status)
    else:
        key_parts = (
            MESSAGE_STATUS_EVENT,
            str(channel.id),
            event_type,
            _canonical_digest(item),
        )
    claim = claim_evolution_event(
        channel=channel,
        event_type=event_type,
        deduplication_key=build_event_deduplication_key(*key_parts),
        external_id=external_id or '',
    )
    if not claim.should_process:
        return

    def _handle(event: EvolutionWebhookEvent) -> None:
        if external_id is None:
            mark_evolution_event_ignored(event, error_code='INVALID_EXTERNAL_ID')
            return
        if target_status is None:
            mark_evolution_event_ignored(event, error_code='UNSUPPORTED_MESSAGE_STATUS')
            return
        _update_outbound_message(
            channel=channel,
            event=event,
            external_id=external_id,
            target_status=target_status,
        )

    _run_claimed_event(claim, _handle)


def _update_outbound_message(
    *,
    channel: WhatsAppChannel,
    event: EvolutionWebhookEvent,
    external_id: str,
    target_status: str,
) -> None:
    provider_key = build_provider_message_key(channel.id, external_id)
    with transaction.atomic():
        locked_event = EvolutionWebhookEvent.objects.select_for_update().get(id=event.id)
        scoped = Message.objects.select_for_update().filter(
            conversation__workspace_id=channel.workspace_id,
            conversation__whatsapp_channel_id=channel.id,
            direction=Message.Direction.OUTBOUND,
        )
        message = scoped.filter(provider_message_key=provider_key).first()
        if message is None:
            candidates = list(scoped.filter(external_id=external_id).order_by('id')[:2])
            if len(candidates) != 1:
                _finish_locked_event(
                    locked_event,
                    status=EvolutionWebhookEvent.Status.IGNORED,
                    error_code='OUTBOUND_MESSAGE_NOT_FOUND',
                )
                return
            message = candidates[0]

        if message.provider_message_key not in (None, provider_key):
            _finish_locked_event(
                locked_event,
                status=EvolutionWebhookEvent.Status.IGNORED,
                error_code='PROVIDER_KEY_MISMATCH',
            )
            return
        if message.provider_message_key is None:
            try:
                with transaction.atomic():
                    message.provider_message_key = provider_key
                    message.save(update_fields=['provider_message_key', 'updated_at'])
            except IntegrityError:
                _finish_locked_event(
                    locked_event,
                    status=EvolutionWebhookEvent.Status.IGNORED,
                    error_code='PROVIDER_KEY_CONFLICT',
                )
                return

        accepted, changed = _apply_outbound_status_transition(
            message=message,
            target_status=target_status,
            error_code='EVOLUTION_DELIVERY_FAILED',
        )
        if not accepted:
            _finish_locked_event(
                locked_event,
                status=EvolutionWebhookEvent.Status.IGNORED,
                error_code='STATUS_REGRESSION',
            )
            return
        if changed:
            message.save(
                update_fields=[
                    'status',
                    'send_error_code',
                    'next_send_retry_at',
                    'updated_at',
                ],
            )
        _finish_locked_event(
            locked_event,
            status=EvolutionWebhookEvent.Status.PROCESSED,
            error_code='',
        )

    logger.info(
        'Status outbound Evolution processado',
        extra={
            **_event_log_context(event, status=EvolutionWebhookEvent.Status.PROCESSED),
            'message_id': str(message.id),
            'status': message.status,
        },
    )


def _apply_outbound_status_transition(
    *,
    message: Message,
    target_status: str,
    error_code: str,
) -> tuple[bool, bool]:
    current_status = message.status or Message.Status.PENDING
    if target_status == Message.Status.FAILED:
        accepted = current_status in {
            Message.Status.PENDING,
            Message.Status.SENT,
            Message.Status.FAILED,
        }
    elif current_status == Message.Status.FAILED:
        accepted = target_status in {
            Message.Status.SENT,
            Message.Status.DELIVERED,
            Message.Status.READ,
        }
    else:
        current_rank = _STATUS_RANK.get(current_status)
        target_rank = _STATUS_RANK.get(target_status)
        accepted = (
            current_rank is not None
            and target_rank is not None
            and target_rank >= current_rank
        )
    if not accepted:
        return False, False

    previous = (message.status, message.send_error_code, message.next_send_retry_at)
    message.status = target_status
    message.next_send_retry_at = None
    message.send_error_code = (
        _sanitize_error_code(error_code)
        if target_status == Message.Status.FAILED
        else ''
    )
    current = (message.status, message.send_error_code, message.next_send_retry_at)
    return True, current != previous


def _process_unsupported_event(
    *,
    channel: WhatsAppChannel,
    payload: dict[str, Any],
) -> None:
    claim = claim_evolution_event(
        channel=channel,
        event_type=UNSUPPORTED_EVENT,
        deduplication_key=build_event_deduplication_key(
            UNSUPPORTED_EVENT,
            str(channel.id),
            _canonical_digest(payload),
        ),
    )
    if not claim.should_process:
        return
    event = mark_evolution_event_ignored(
        claim.event,
        error_code=UNSUPPORTED_EVENT,
    )
    logger.info(
        'Evento Evolution nao suportado ignorado',
        extra=_event_log_context(event, status=event.status, error_code=event.error_code),
    )


def _run_claimed_event(
    claim: EvolutionEventClaim,
    handler: Callable[[EvolutionWebhookEvent], None],
) -> None:
    if not claim.should_process:
        return
    try:
        handler(claim.event)
    except EvolutionEventProcessingError as exc:
        _mark_failed_safely(claim.event, error_code=exc.error_code)
        raise
    except DatabaseError as exc:
        _mark_failed_safely(claim.event, error_code='EVENT_DATABASE_ERROR')
        raise EvolutionEventProcessingError(
            'EVENT_DATABASE_ERROR',
            retryable=True,
            event_id=claim.event.id,
        ) from exc
    except Exception as exc:
        _mark_failed_safely(claim.event, error_code='UNEXPECTED_PROCESSING_ERROR')
        logger.warning(
            'Falha inesperada no processamento de evento Evolution',
            extra={
                **_event_log_context(
                    claim.event,
                    status=EvolutionWebhookEvent.Status.FAILED,
                    error_code='UNEXPECTED_PROCESSING_ERROR',
                ),
                'exception_type': type(exc).__name__,
            },
        )
        raise


def _mark_evolution_event_finished(
    *,
    event: EvolutionWebhookEvent,
    status: str,
    error_code: str,
) -> EvolutionWebhookEvent:
    with transaction.atomic():
        locked_event = EvolutionWebhookEvent.objects.select_for_update().get(id=event.id)
        if locked_event.status != EvolutionWebhookEvent.Status.PROCESSING:
            return locked_event
        _finish_locked_event(locked_event, status=status, error_code=error_code)
        return locked_event


def _finish_locked_event(
    event: EvolutionWebhookEvent,
    *,
    status: str,
    error_code: str,
) -> None:
    event.status = status
    event.error_code = _sanitize_error_code(error_code) if error_code else ''
    event.finished_at = timezone.now()
    event.save(update_fields=['status', 'error_code', 'finished_at', 'updated_at'])


def _mark_failed_safely(event: EvolutionWebhookEvent, *, error_code: str) -> None:
    try:
        mark_evolution_event_failed(event, error_code=error_code)
    except Exception as exc:
        logger.warning(
            'Falha ao finalizar recibo Evolution',
            extra={
                **_event_log_context(event, error_code='EVENT_RECEIPT_FINALIZE_FAILED'),
                'exception_type': type(exc).__name__,
            },
        )


def _event_items(payload: dict[str, Any]) -> list[object]:
    data = payload.get('data')
    return list(data) if isinstance(data, list) else [data]


def _parse_inbound_message(
    item: object,
) -> tuple[_InboundMessageData | None, str | None]:
    if not isinstance(item, dict):
        return None, 'INVALID_MESSAGE_ITEM'
    key = item.get('key')
    if not isinstance(key, dict):
        return None, 'INVALID_MESSAGE_KEY'
    external_id = _validate_external_id(key.get('id'))
    if external_id is None:
        return None, 'INVALID_EXTERNAL_ID'
    from_me = key.get('fromMe')
    if from_me is True:
        return None, 'MESSAGE_FROM_ME'
    if from_me is not False:
        return None, 'INVALID_FROM_ME'

    remote_jid_value = key.get('remoteJid')
    jid_parts = _validated_jid_parts(remote_jid_value)
    if jid_parts is None:
        return None, 'INVALID_REMOTE_JID'
    _, remote_jid_suffix = jid_parts
    if remote_jid_suffix == 'g.us':
        return None, 'UNSUPPORTED_GROUP_MESSAGE'

    if remote_jid_suffix == 'lid':
        if _normalize_phone_jid(remote_jid_value) is None:
            return None, 'INVALID_REMOTE_JID'
        provider_identity = remote_jid_value
        alternate = key.get('remoteJidAlt')
        if alternate is None:
            alternate = item.get('remoteJidAlt')
        resolved_phone = _normalize_direct_phone_jid(alternate) or ''
    elif remote_jid_suffix in _DIRECT_INDIVIDUAL_JID_SUFFIXES:
        resolved_phone = _normalize_direct_phone_jid(remote_jid_value)
        if resolved_phone is None:
            return None, 'INVALID_REMOTE_JID'
        provider_identity = resolved_phone
    else:
        return None, 'UNSUPPORTED_REMOTE_JID'

    message = item.get('message')
    if not isinstance(message, dict):
        return None, 'INVALID_MESSAGE_CONTENT'
    body = _extract_message_text(message)
    if body is None:
        return None, 'UNSUPPORTED_MESSAGE_CONTENT'

    push_name = item.get('pushName')
    contact_name = resolved_phone or provider_identity
    if (
        isinstance(push_name, str)
        and push_name.strip() == push_name
        and push_name
        and push_name not in {resolved_phone, provider_identity}
        and _safe_text_value(push_name, 255)
    ):
        contact_name = push_name

    message_type = item.get('messageType')
    if message_type is None and len(message) == 1:
        message_type = next(iter(message))
    if not isinstance(message_type, str) or not _safe_text_value(message_type, 64):
        message_type = None

    return (
        _InboundMessageData(
            external_id=external_id,
            remote_jid=remote_jid_value,
            provider_identity=provider_identity,
            resolved_phone=resolved_phone,
            body=body,
            contact_name=contact_name,
            message_type=message_type,
        ),
        None,
    )


def _extract_message_text(message: dict[str, Any]) -> str | None:
    conversation = message.get('conversation')
    if isinstance(conversation, str) and conversation.strip():
        return conversation
    extended = message.get('extendedTextMessage')
    if isinstance(extended, dict):
        text = extended.get('text')
        if isinstance(text, str) and text.strip():
            return text
    return None


def _extract_connection_state(payload: dict[str, Any]) -> str | None:
    for path in (('data', 'state'), ('data', 'status'), ('state',), ('status',)):
        value = _value_at(payload, path)
        if isinstance(value, str):
            normalized = re.sub(r'[^a-z0-9]+', '_', value.strip().lower()).strip('_')
            if normalized:
                return normalized[:64]
    return None


def _extract_external_timestamp(payload: dict[str, Any]) -> str | None:
    for path in (
        ('data', 'eventTimestamp'),
        ('data', 'timestamp'),
        ('eventTimestamp',),
        ('timestamp',),
    ):
        value = _value_at(payload, path)
        if isinstance(value, int) and not isinstance(value, bool) and value > 0:
            return str(value)
        if not isinstance(value, str) or not _SAFE_TIMESTAMP.fullmatch(value):
            continue
        try:
            parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
        except ValueError:
            continue
        if parsed.tzinfo is not None:
            return value
    return None


def _extract_phone_number(payload: dict[str, Any]) -> str | None:
    for path in (
        ('data', 'wuid'),
        ('data', 'phoneNumber'),
        ('data', 'sender'),
        ('sender',),
    ):
        value = _value_at(payload, path)
        normalized = _normalize_phone_jid(value)
        if normalized is not None:
            return normalized
    return None


def _extract_connection_error_code(payload: dict[str, Any]) -> str:
    for path in (
        ('data', 'statusReason'),
        ('data', 'reason'),
        ('statusReason',),
        ('reason',),
    ):
        value = _value_at(payload, path)
        if isinstance(value, str) and _SAFE_EXTERNAL_REASON.fullmatch(value):
            return _sanitize_error_code(value)
    return 'EVOLUTION_CONNECTION_ERROR'


def _extract_external_id(item: object) -> str | None:
    if not isinstance(item, dict):
        return None
    for path in (
        ('key', 'id'),
        ('data', 'key', 'id'),
        ('message', 'key', 'id'),
        ('id',),
        # messages.update real da Evolution v2: id em data.keyId (== key.id do
        # upsert) e data.messageId. Fallbacks adicionais, sem remover os antigos.
        ('data', 'keyId'),
        ('keyId',),
        ('data', 'messageId'),
        ('messageId',),
    ):
        value = _value_at(item, path)
        external_id = _validate_external_id(value)
        if external_id is not None:
            return external_id
    return None


def _extract_message_status(item: object) -> str | None:
    if not isinstance(item, dict):
        return None
    for path in (
        ('status',),
        ('messageStatus',),
        ('update', 'status'),
        ('data', 'status'),
        ('message', 'status'),
    ):
        status = normalize_evolution_message_status(_value_at(item, path))
        if status is not None:
            return status
    return None


def _validate_external_id(value: object) -> str | None:
    if not isinstance(value, str) or not value or len(value) > 255:
        return None
    if value != value.strip() or _contains_control_character(value):
        return None
    return value


def _normalize_phone_jid(value: object) -> str | None:
    if not isinstance(value, str) or not value or len(value) > 255:
        return None
    if value != value.strip() or _contains_control_character(value):
        return None
    local, separator, suffix = value.partition('@')
    if separator and suffix not in _INDIVIDUAL_JID_SUFFIXES:
        return None
    local = local.split(':', maxsplit=1)[0].lstrip('+')
    return local if _PHONE_PATTERN.fullmatch(local) else None


def _normalize_direct_phone_jid(value: object) -> str | None:
    parts = _validated_jid_parts(value)
    if parts is None:
        return None
    local, suffix = parts
    if suffix not in _DIRECT_INDIVIDUAL_JID_SUFFIXES:
        return None
    normalized_local = local.split(':', maxsplit=1)[0].lstrip('+')
    return normalized_local if _PHONE_PATTERN.fullmatch(normalized_local) else None


def _validated_jid_parts(value: object) -> tuple[str, str] | None:
    if not isinstance(value, str) or not _safe_text_value(value, 255):
        return None
    if value != value.strip() or value.count('@') != 1:
        return None
    local, suffix = value.rsplit('@', maxsplit=1)
    if not local or not suffix:
        return None
    return local, suffix


def _safe_text_value(value: str, max_length: int) -> bool:
    return bool(value) and len(value) <= max_length and not _contains_control_character(value)


def _contains_control_character(value: str) -> bool:
    return any(unicodedata.category(character) == 'Cc' for character in value)


def _value_at(value: object, path: tuple[str, ...]) -> object:
    current = value
    for key in path:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def _canonical_digest(value: object) -> str:
    canonical = json.dumps(
        value,
        sort_keys=True,
        separators=(',', ':'),
        ensure_ascii=False,
        default=lambda item: type(item).__name__,
    ).encode('utf-8')
    return hashlib.sha256(canonical).hexdigest()


def _positive_stale_seconds() -> int:
    value = getattr(settings, 'EVOLUTION_EVENT_PROCESSING_STALE_SECONDS', None)
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise EvolutionEventProcessingError(
            'INVALID_EVENT_STALE_SETTING',
            retryable=False,
        )
    return value


def _sanitize_error_code(value: object) -> str:
    normalized = re.sub(r'[^A-Z0-9]+', '_', str(value or 'UNKNOWN_ERROR').upper()).strip('_')
    return normalized[:64] or 'UNKNOWN_ERROR'


def _delete_qr_best_effort(
    *,
    channel_id: UUID | str,
    event: EvolutionWebhookEvent,
) -> None:
    try:
        delete_evolution_qr_code(channel_id)
    except EvolutionQRCodeCacheError as exc:
        logger.warning(
            'Falha best-effort ao remover QR do cache',
            extra={
                **_event_log_context(event, error_code=exc.error_code),
                'exception_type': type(exc).__name__,
            },
        )


def _event_log_context(
    event: EvolutionWebhookEvent,
    *,
    status: str | None = None,
    error_code: str = '',
) -> dict[str, object]:
    return {
        'channel_id': str(event.whatsapp_channel_id),
        'workspace_id': str(event.whatsapp_channel.workspace_id),
        'evolution_event_id': str(event.id),
        'event_type': event.event_type,
        'status': status or event.status,
        'attempt_count': event.attempt_count,
        'error_code': _sanitize_error_code(error_code) if error_code else '',
    }
