from __future__ import annotations

import logging
import re
from datetime import timedelta
from time import perf_counter
from typing import Any

from django.db import transaction
from django.db.models import Avg, Count, Q, QuerySet
from django.db.models.functions import Coalesce, TruncDay, TruncHour
from django.utils import timezone

from omnichannel.models import AIObservabilityEvent

logger = logging.getLogger(__name__)

PERIOD_DELTAS = {
    '24h': timedelta(hours=24),
    '7d': timedelta(days=7),
    '30d': timedelta(days=30),
}
MAX_RECENT_EVENTS_LIMIT = 100
DEFAULT_RECENT_EVENTS_LIMIT = 25
# reason_code canonico para distinguir a origem de um CHANNEL_ERROR nas metricas
# (provisionamento vs. atualizacao de conexao via webhook). Sanitizado pelo
# proprio record; mantido em caixa alta para casar com sanitize_observability_code.
_PROVISIONING_ERROR_REASON = 'PROVISIONING'
CONNECTION_ERROR_REASON = 'CONNECTION'
PROVISIONING_ERROR_REASON = _PROVISIONING_ERROR_REASON
ALLOWED_METADATA_KEYS = {
    'retry_countdown',
    'is_retryable',
    'provider_supported',
    'has_api_key',
    'message_type',
    'direction',
    'from_me',
    'is_group',
    'http_status',
    'delivery_status',
    'source',
    'action',
}
BLOCKED_METADATA_KEY_FRAGMENTS = {
    'key',
    'api_key',
    'token',
    'secret',
    'authorization',
    'header',
    'payload',
    'body',
    'prompt',
    'text',
    'content',
    'phone',
    'email',
    'raw',
    'response',
}

# Tipos observados nos fluxos/fixtures da Evolution e nos tipos de conteudo que
# o pipeline classifica explicitamente. Valores externos fora desta allowlist
# nunca sao copiados para observabilidade.
ALLOWED_MESSAGE_TYPES = frozenset(
    {
        'conversation',
        'extendedTextMessage',
        'audioMessage',
        'documentMessage',
        'imageMessage',
        'reactionMessage',
        'stickerMessage',
        'videoMessage',
    },
)
UNKNOWN_MESSAGE_TYPE = 'unknown'


def sanitize_observability_code(value: str | None) -> str:
    sanitized = re.sub(r'[^A-Z0-9_]+', '_', str(value or '').upper()).strip('_')
    return sanitized[:64]


def sanitize_observability_metadata(metadata: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(metadata, dict):
        return {}

    sanitized: dict[str, Any] = {}
    for key, value in metadata.items():
        safe_key = str(key)
        lowered_key = safe_key.lower()
        if safe_key not in ALLOWED_METADATA_KEYS:
            continue
        if safe_key != 'has_api_key' and any(
            fragment in lowered_key for fragment in BLOCKED_METADATA_KEY_FRAGMENTS
        ):
            continue
        if safe_key == 'message_type':
            sanitized[safe_key] = normalize_observability_message_type(value)
        elif isinstance(value, (bool, int, float)) or value is None:
            sanitized[safe_key] = value
        elif isinstance(value, str):
            sanitized[safe_key] = value[:128]
    return sanitized


def normalize_observability_message_type(value: Any) -> str:
    if isinstance(value, str) and value in ALLOWED_MESSAGE_TYPES:
        return value
    return UNKNOWN_MESSAGE_TYPE


def calculate_latency_ms(start_monotonic: float) -> int:
    elapsed_ms = int((perf_counter() - start_monotonic) * 1000)
    return max(elapsed_ms, 0)


def record_ai_observability_event(
    *,
    workspace,
    event_type: str,
    status: str,
    provider_config=None,
    conversation=None,
    source_message=None,
    output_message=None,
    ai_processing_run=None,
    whatsapp_channel=None,
    provider: str = '',
    model_name: str = '',
    reason_code: str = '',
    error_code: str = '',
    latency_ms: int | None = None,
    attempt_count: int | None = None,
    metadata: dict[str, Any] | None = None,
) -> AIObservabilityEvent:
    if latency_ms is not None and latency_ms < 0:
        raise ValueError('latency_ms must be positive.')

    if whatsapp_channel is not None and whatsapp_channel.workspace_id != workspace.id:
        raise ValueError('WhatsApp channel does not belong to workspace.')

    return AIObservabilityEvent.objects.create(
        workspace=workspace,
        provider_config=provider_config,
        conversation=conversation,
        source_message=source_message,
        output_message=output_message,
        ai_processing_run=ai_processing_run,
        whatsapp_channel=whatsapp_channel,
        whatsapp_channel_id_snapshot=(
            whatsapp_channel.id if whatsapp_channel is not None else None
        ),
        event_type=sanitize_observability_code(event_type),
        status=str(status or '')[:32],
        provider=(provider or getattr(provider_config, 'provider', '') or '')[:32],
        model_name=(model_name or getattr(provider_config, 'model_name', '') or '')[:128],
        reason_code=sanitize_observability_code(reason_code),
        error_code=sanitize_observability_code(error_code),
        latency_ms=latency_ms,
        attempt_count=attempt_count,
        metadata=sanitize_observability_metadata(metadata),
    )


def record_ai_observability_event_safe(**kwargs) -> AIObservabilityEvent | None:
    try:
        # O savepoint impede que uma falha de banco na telemetria contamine uma
        # transacao externa do fluxo principal.
        with transaction.atomic():
            return record_ai_observability_event(**kwargs)
    except Exception as exc:
        workspace = kwargs.get('workspace')
        logger.warning(
            'Falha ao registrar evento de observabilidade de IA',
            extra={
                'workspace_id': str(getattr(workspace, 'id', '') or ''),
                'event_type': sanitize_observability_code(kwargs.get('event_type')),
                'status': str(kwargs.get('status') or '')[:32],
                'exception_type': type(exc).__name__,
            },
        )
        return None


def record_channel_observability_event_safe(
    *,
    workspace,
    channel,
    event_type: str,
    status: str,
    reason_code: str = '',
    error_code: str = '',
    latency_ms: int | None = None,
    metadata: dict[str, Any] | None = None,
) -> AIObservabilityEvent | None:
    """
    Helper fino de observabilidade de ciclo de vida de canal WhatsApp.

    Delega ao `record_ai_observability_event_safe` ja existente (mesma
    sanitizacao de code/metadata e mesma garantia de "nunca quebra o fluxo
    principal"), apenas fixando `whatsapp_channel=channel`. Nao reimplementa
    sanitizacao nem try/except.
    """
    return record_ai_observability_event_safe(
        workspace=workspace,
        whatsapp_channel=channel,
        event_type=event_type,
        status=status,
        reason_code=reason_code,
        error_code=error_code,
        latency_ms=latency_ms,
        metadata=metadata,
    )


def get_period_start(period: str):
    if period not in PERIOD_DELTAS:
        raise ValueError('Periodo invalido.')
    return timezone.now() - PERIOD_DELTAS[period]


def get_ai_observability_queryset(
    *,
    workspace,
    period: str = '24h',
    provider: str = '',
    event_type: str = '',
    status: str = '',
    error_code: str = '',
) -> QuerySet[AIObservabilityEvent]:
    queryset = AIObservabilityEvent.objects.filter(
        workspace=workspace,
        created_at__gte=get_period_start(period),
    )
    if provider:
        queryset = queryset.filter(provider=provider)
    if event_type:
        queryset = queryset.filter(event_type=sanitize_observability_code(event_type))
    if status:
        queryset = queryset.filter(status=status)
    if error_code:
        queryset = queryset.filter(error_code=sanitize_observability_code(error_code))
    return queryset


def get_ai_observability_summary(*, workspace, period: str = '24h', **filters) -> dict[str, Any]:
    queryset = get_ai_observability_queryset(workspace=workspace, period=period, **filters)
    event_type = AIObservabilityEvent.EventType

    totals = queryset.aggregate(
        ai_scheduled=Count('id', filter=Q(event_type=event_type.AI_SCHEDULED)),
        ai_skipped=Count('id', filter=Q(event_type=event_type.AI_SKIPPED)),
        ai_provider_attempt=Count('id', filter=Q(event_type=event_type.AI_PROVIDER_ATTEMPT)),
        ai_provider_success=Count('id', filter=Q(event_type=event_type.AI_PROVIDER_SUCCESS)),
        ai_provider_failed=Count('id', filter=Q(event_type=event_type.AI_PROVIDER_FAILED)),
        ai_provider_retrying=Count('id', filter=Q(event_type=event_type.AI_PROVIDER_RETRYING)),
        outbound_delivery_attempt=Count('id', filter=Q(event_type=event_type.OUTBOUND_DELIVERY_ATTEMPT)),
        outbound_delivery_success=Count('id', filter=Q(event_type=event_type.OUTBOUND_DELIVERY_SUCCESS)),
        outbound_delivery_failed=Count('id', filter=Q(event_type=event_type.OUTBOUND_DELIVERY_FAILED)),
        outbound_delivery_retrying=Count('id', filter=Q(event_type=event_type.OUTBOUND_DELIVERY_RETRYING)),
    )
    latency = queryset.aggregate(
        ai_avg_latency_ms=Avg('latency_ms', filter=Q(event_type=event_type.AI_PROVIDER_SUCCESS)),
        delivery_avg_latency_ms=Avg('latency_ms', filter=Q(event_type=event_type.OUTBOUND_DELIVERY_SUCCESS)),
    )
    ai_total = (totals['ai_provider_success'] or 0) + (totals['ai_provider_failed'] or 0)
    delivery_total = (totals['outbound_delivery_success'] or 0) + (totals['outbound_delivery_failed'] or 0)

    by_provider = list(
        queryset.exclude(provider='')
        .values('provider', 'model_name')
        .annotate(
            success=Count('id', filter=Q(status=AIObservabilityEvent.Status.SUCCESS)),
            failed=Count('id', filter=Q(status=AIObservabilityEvent.Status.FAILED)),
            retrying=Count('id', filter=Q(status=AIObservabilityEvent.Status.RETRYING)),
        )
        .order_by('provider', 'model_name'),
    )
    errors = list(
        queryset.exclude(error_code='')
        .values('error_code')
        .annotate(count=Count('id'))
        .order_by('-count', 'error_code')[:20],
    )

    return {
        'workspace_id': str(workspace.id),
        'period': period,
        'totals': totals,
        'rates': {
            'ai_success_rate': _rate(totals['ai_provider_success'], ai_total),
            'delivery_success_rate': _rate(totals['outbound_delivery_success'], delivery_total),
        },
        'latency': {
            'ai_avg_latency_ms': _avg_to_int(latency['ai_avg_latency_ms']),
            'delivery_avg_latency_ms': _avg_to_int(latency['delivery_avg_latency_ms']),
        },
        'by_provider': by_provider,
        'errors': errors,
    }


def get_ai_observability_timeseries(*, workspace, period: str = '24h', **filters) -> dict[str, Any]:
    queryset = get_ai_observability_queryset(workspace=workspace, period=period, **filters)
    bucket_func = TruncHour if period == '24h' else TruncDay
    bucket = 'hour' if period == '24h' else 'day'
    event_type = AIObservabilityEvent.EventType

    points = list(
        queryset.annotate(bucket_ts=bucket_func('created_at'))
        .values('bucket_ts')
        .annotate(
            ai_success=Count('id', filter=Q(event_type=event_type.AI_PROVIDER_SUCCESS)),
            ai_failed=Count('id', filter=Q(event_type=event_type.AI_PROVIDER_FAILED)),
            delivery_success=Count('id', filter=Q(event_type=event_type.OUTBOUND_DELIVERY_SUCCESS)),
            delivery_failed=Count('id', filter=Q(event_type=event_type.OUTBOUND_DELIVERY_FAILED)),
        )
        .order_by('bucket_ts'),
    )

    return {
        'workspace_id': str(workspace.id),
        'period': period,
        'bucket': bucket,
        'points': [
            {
                'timestamp': item['bucket_ts'].isoformat() if item['bucket_ts'] else '',
                'ai_success': item['ai_success'],
                'ai_failed': item['ai_failed'],
                'delivery_success': item['delivery_success'],
                'delivery_failed': item['delivery_failed'],
            }
            for item in points
        ],
    }


def get_ai_observability_recent_events(
    *,
    workspace,
    period: str = '24h',
    limit: int = DEFAULT_RECENT_EVENTS_LIMIT,
    **filters,
) -> QuerySet[AIObservabilityEvent]:
    safe_limit = min(max(int(limit or DEFAULT_RECENT_EVENTS_LIMIT), 1), MAX_RECENT_EVENTS_LIMIT)
    queryset = get_ai_observability_queryset(workspace=workspace, period=period, **filters)
    return queryset.order_by('-created_at')[:safe_limit]


def get_channel_observability_summary(
    *,
    workspace,
    period: str = '24h',
    **filters,
) -> dict[str, Any]:
    """Metricas de ciclo de vida e trafego dos canais, escopadas por workspace."""
    queryset = get_ai_observability_queryset(workspace=workspace, period=period, **filters)
    event_type = AIObservabilityEvent.EventType

    event_totals = queryset.aggregate(
        channels_created=Count('id', filter=Q(event_type=event_type.CHANNEL_CREATED)),
        channels_provisioned=Count('id', filter=Q(event_type=event_type.CHANNEL_PROVISIONED)),
        webhooks_configured=Count('id', filter=Q(event_type=event_type.CHANNEL_WEBHOOK_CONFIGURED)),
        qr_generated=Count('id', filter=Q(event_type=event_type.CHANNEL_QR_GENERATED)),
        channel_connected_events=Count(
            'id',
            filter=Q(event_type=event_type.CHANNEL_CONNECTED),
        ),
        channel_disconnected_events=Count(
            'id',
            filter=Q(event_type=event_type.CHANNEL_DISCONNECTED),
        ),
        channels_reconnecting=Count('id', filter=Q(event_type=event_type.CHANNEL_RECONNECTING)),
        channels_error=Count('id', filter=Q(event_type=event_type.CHANNEL_ERROR)),
        provisioning_failed=Count(
            'id',
            filter=Q(event_type=event_type.CHANNEL_ERROR, reason_code=_PROVISIONING_ERROR_REASON),
        ),
        channels_removed=Count('id', filter=Q(event_type=event_type.CHANNEL_REMOVED)),
        inbound_received=Count('id', filter=Q(event_type=event_type.CHANNEL_INBOUND_RECEIVED)),
        outbound_attempt=Count('id', filter=Q(event_type=event_type.OUTBOUND_DELIVERY_ATTEMPT)),
        outbound_success=Count('id', filter=Q(event_type=event_type.OUTBOUND_DELIVERY_SUCCESS)),
        outbound_failed=Count('id', filter=Q(event_type=event_type.OUTBOUND_DELIVERY_FAILED)),
    )
    from omnichannel.models import WhatsAppChannel

    inventory = WhatsAppChannel.objects.filter(workspace=workspace).aggregate(
        channels_connected=Count(
            'id',
            filter=Q(status=WhatsAppChannel.Status.CONNECTED),
        ),
        channels_disconnected=Count(
            'id',
            filter=Q(status=WhatsAppChannel.Status.DISCONNECTED),
        ),
    )
    totals = {**event_totals, **inventory}
    latency = queryset.aggregate(
        avg_time_to_qr_ms=Avg('latency_ms', filter=Q(event_type=event_type.CHANNEL_QR_GENERATED)),
        avg_delivery_latency_ms=Avg(
            'latency_ms',
            filter=Q(event_type=event_type.OUTBOUND_DELIVERY_SUCCESS),
        ),
    )
    latency['avg_time_to_connection_ms'] = _avg_time_to_first_connection_ms(
        workspace=workspace,
        eligible_queryset=queryset,
    )
    outbound_total = (totals['outbound_success'] or 0) + (totals['outbound_failed'] or 0)

    by_channel = list(
        queryset.annotate(
            channel_identity=Coalesce(
                'whatsapp_channel_id',
                'whatsapp_channel_id_snapshot',
            ),
        )
        .filter(channel_identity__isnull=False)
        .values('channel_identity')
        .annotate(
            connected=Count('id', filter=Q(event_type=event_type.CHANNEL_CONNECTED)),
            disconnected=Count('id', filter=Q(event_type=event_type.CHANNEL_DISCONNECTED)),
            errors=Count('id', filter=Q(event_type=event_type.CHANNEL_ERROR)),
            inbound_received=Count('id', filter=Q(event_type=event_type.CHANNEL_INBOUND_RECEIVED)),
            outbound_success=Count('id', filter=Q(event_type=event_type.OUTBOUND_DELIVERY_SUCCESS)),
            outbound_failed=Count('id', filter=Q(event_type=event_type.OUTBOUND_DELIVERY_FAILED)),
        )
        .order_by('channel_identity'),
    )
    for row in by_channel:
        row['whatsapp_channel_id'] = str(row.pop('channel_identity'))

    errors = list(
        queryset.filter(event_type=event_type.CHANNEL_ERROR)
        .exclude(error_code='')
        .values('error_code')
        .annotate(count=Count('id'))
        .order_by('-count', 'error_code')[:20],
    )

    return {
        'workspace_id': str(workspace.id),
        'period': period,
        'totals': totals,
        'rates': {
            'outbound_success_rate': _rate(totals['outbound_success'], outbound_total),
        },
        'latency': {
            'avg_time_to_qr_ms': _avg_to_int(latency['avg_time_to_qr_ms']),
            'avg_time_to_connection_ms': latency['avg_time_to_connection_ms'],
            'avg_delivery_latency_ms': _avg_to_int(latency['avg_delivery_latency_ms']),
        },
        'by_channel': by_channel,
        'errors': errors,
    }


def get_channel_observability_timeseries(
    *,
    workspace,
    period: str = '24h',
    **filters,
) -> dict[str, Any]:
    """Serie temporal de eventos de canal, escopada por workspace."""
    queryset = get_ai_observability_queryset(workspace=workspace, period=period, **filters)
    bucket_func = TruncHour if period == '24h' else TruncDay
    bucket = 'hour' if period == '24h' else 'day'
    event_type = AIObservabilityEvent.EventType

    points = list(
        queryset.annotate(bucket_ts=bucket_func('created_at'))
        .values('bucket_ts')
        .annotate(
            connected=Count('id', filter=Q(event_type=event_type.CHANNEL_CONNECTED)),
            disconnected=Count('id', filter=Q(event_type=event_type.CHANNEL_DISCONNECTED)),
            errors=Count('id', filter=Q(event_type=event_type.CHANNEL_ERROR)),
            inbound_received=Count('id', filter=Q(event_type=event_type.CHANNEL_INBOUND_RECEIVED)),
            outbound_success=Count('id', filter=Q(event_type=event_type.OUTBOUND_DELIVERY_SUCCESS)),
            outbound_failed=Count('id', filter=Q(event_type=event_type.OUTBOUND_DELIVERY_FAILED)),
        )
        .order_by('bucket_ts'),
    )

    return {
        'workspace_id': str(workspace.id),
        'period': period,
        'bucket': bucket,
        'points': [
            {
                'timestamp': item['bucket_ts'].isoformat() if item['bucket_ts'] else '',
                'connected': item['connected'],
                'disconnected': item['disconnected'],
                'errors': item['errors'],
                'inbound_received': item['inbound_received'],
                'outbound_success': item['outbound_success'],
                'outbound_failed': item['outbound_failed'],
            }
            for item in points
        ],
    }


def _rate(numerator: int | None, denominator: int | None) -> float:
    if not denominator:
        return 0.0
    return round((numerator or 0) / denominator, 2)


def _avg_to_int(value) -> int | None:
    if value is None:
        return None
    return int(value)


def _avg_time_to_first_connection_ms(*, workspace, eligible_queryset) -> int | None:
    """Media CREATED -> primeira CONNECTED; a janela usa a primeira conexao."""
    event_type = AIObservabilityEvent.EventType
    eligible_connection_ids = set(
        eligible_queryset.filter(event_type=event_type.CHANNEL_CONNECTED).values_list(
            'id',
            flat=True,
        ),
    )
    if not eligible_connection_ids:
        return None

    lifecycle_events = (
        AIObservabilityEvent.objects.filter(
            workspace=workspace,
            event_type__in={event_type.CHANNEL_CREATED, event_type.CHANNEL_CONNECTED},
        )
        .annotate(
            channel_identity=Coalesce(
                'whatsapp_channel_id',
                'whatsapp_channel_id_snapshot',
            ),
        )
        .filter(channel_identity__isnull=False)
        .values('id', 'event_type', 'created_at', 'channel_identity')
        .order_by('created_at', 'id')
    )

    first_created: dict[Any, Any] = {}
    first_connected: dict[Any, dict[str, Any]] = {}
    for event in lifecycle_events:
        identity = event['channel_identity']
        if event['event_type'] == event_type.CHANNEL_CREATED:
            first_created.setdefault(identity, event['created_at'])
        else:
            first_connected.setdefault(identity, event)

    samples: list[int] = []
    for identity, connection in first_connected.items():
        created_at = first_created.get(identity)
        if (
            connection['id'] in eligible_connection_ids
            and created_at is not None
            and created_at <= connection['created_at']
        ):
            samples.append(int((connection['created_at'] - created_at).total_seconds() * 1000))
    if not samples:
        return None
    return int(sum(samples) / len(samples))
