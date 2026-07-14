from __future__ import annotations

import logging
import re
from datetime import timedelta
from time import perf_counter
from typing import Any

from django.db.models import Avg, Count, Q, QuerySet
from django.db.models.functions import TruncDay, TruncHour
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
        if isinstance(value, (bool, int, float)) or value is None:
            sanitized[safe_key] = value
        elif isinstance(value, str):
            sanitized[safe_key] = value[:128]
    return sanitized


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

    return AIObservabilityEvent.objects.create(
        workspace=workspace,
        provider_config=provider_config,
        conversation=conversation,
        source_message=source_message,
        output_message=output_message,
        ai_processing_run=ai_processing_run,
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


def _rate(numerator: int | None, denominator: int | None) -> float:
    if not denominator:
        return 0.0
    return round((numerator or 0) / denominator, 2)


def _avg_to_int(value) -> int | None:
    if value is None:
        return None
    return int(value)
