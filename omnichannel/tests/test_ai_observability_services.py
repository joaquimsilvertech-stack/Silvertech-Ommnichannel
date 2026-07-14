from __future__ import annotations

import logging
from unittest.mock import patch

import pytest

from omnichannel.models import AIObservabilityEvent
from omnichannel.observability import (
    get_ai_observability_summary,
    record_ai_observability_event,
    record_ai_observability_event_safe,
    sanitize_observability_code,
    sanitize_observability_metadata,
)
from workspaces.factories import WorkspaceFactory


def test_sanitize_observability_metadata_uses_allowlist_and_blocks_sensitive_keys() -> None:
    metadata = sanitize_observability_metadata(
        {
            'source': 'webhook',
            'retry_countdown': 60,
            'api_key': 'sk-secret',
            'raw_payload': {'event': 'messages.upsert'},
            'body': 'conteudo da conversa',
            'prompt': 'system prompt',
            'phone': '5511999999999',
            'unknown': 'ignored',
        },
    )

    assert metadata == {'source': 'webhook', 'retry_countdown': 60}
    assert 'sk-secret' not in str(metadata)
    assert 'conteudo da conversa' not in str(metadata)


def test_sanitize_observability_code_normalizes_and_limits_values() -> None:
    assert sanitize_observability_code('ai provider timeout!') == 'AI_PROVIDER_TIMEOUT'
    assert sanitize_observability_code('sk_secret_api_key_timeout') == 'SK_SECRET_API_KEY_TIMEOUT'
    assert len(sanitize_observability_code('x' * 100)) == 64


@pytest.mark.django_db
def test_summary_counts_only_current_workspace() -> None:
    workspace = WorkspaceFactory()
    other_workspace = WorkspaceFactory()
    record_ai_observability_event(
        workspace=workspace,
        event_type=AIObservabilityEvent.EventType.AI_PROVIDER_SUCCESS,
        status=AIObservabilityEvent.Status.SUCCESS,
        provider='openai',
        model_name='gpt-4o-mini',
        latency_ms=120,
    )
    record_ai_observability_event(
        workspace=other_workspace,
        event_type=AIObservabilityEvent.EventType.AI_PROVIDER_FAILED,
        status=AIObservabilityEvent.Status.FAILED,
        provider='openai',
        error_code='OTHER_WORKSPACE',
    )

    summary = get_ai_observability_summary(workspace=workspace)

    assert summary['totals']['ai_provider_success'] == 1
    assert summary['totals']['ai_provider_failed'] == 0
    assert summary['latency']['ai_avg_latency_ms'] == 120
    assert summary['errors'] == []


@pytest.mark.django_db
def test_safe_record_does_not_propagate_exception_or_log_secret(caplog) -> None:
    workspace = WorkspaceFactory()
    caplog.set_level(logging.WARNING)

    with patch(
        'omnichannel.observability.record_ai_observability_event',
        side_effect=RuntimeError('api_key sk-secret raw_payload message.body'),
    ):
        result = record_ai_observability_event_safe(
            workspace=workspace,
            event_type=AIObservabilityEvent.EventType.AI_PROVIDER_FAILED,
            status=AIObservabilityEvent.Status.FAILED,
            metadata={'source': 'test', 'api_key': 'sk-secret'},
        )

    assert result is None
    assert 'sk-secret' not in caplog.text
    assert 'raw_payload' not in caplog.text
    assert 'message.body' not in caplog.text
