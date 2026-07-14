from __future__ import annotations

import pytest

from omnichannel.models import AIObservabilityEvent
from omnichannel.observability import record_ai_observability_event
from workspaces.factories import WorkspaceFactory


@pytest.mark.django_db
def test_ai_observability_event_creates_event_with_workspace() -> None:
    workspace = WorkspaceFactory()

    event = record_ai_observability_event(
        workspace=workspace,
        event_type=AIObservabilityEvent.EventType.AI_SCHEDULED,
        status=AIObservabilityEvent.Status.PENDING,
        metadata={'source': 'webhook'},
    )

    assert event.workspace == workspace
    assert event.event_type == AIObservabilityEvent.EventType.AI_SCHEDULED
    assert event.status == AIObservabilityEvent.Status.PENDING
    assert event.metadata == {'source': 'webhook'}


def test_ai_observability_event_does_not_define_sensitive_fields() -> None:
    field_names = {field.name for field in AIObservabilityEvent._meta.fields}

    assert 'api_key' not in field_names
    assert 'payload' not in field_names
    assert 'raw_payload' not in field_names
    assert 'body' not in field_names
    assert 'prompt' not in field_names
    assert 'response' not in field_names
    assert 'headers' not in field_names


@pytest.mark.django_db
def test_ai_observability_event_rejects_negative_latency() -> None:
    workspace = WorkspaceFactory()

    with pytest.raises(ValueError):
        record_ai_observability_event(
            workspace=workspace,
            event_type=AIObservabilityEvent.EventType.AI_PROVIDER_FAILED,
            status=AIObservabilityEvent.Status.FAILED,
            latency_ms=-1,
        )
