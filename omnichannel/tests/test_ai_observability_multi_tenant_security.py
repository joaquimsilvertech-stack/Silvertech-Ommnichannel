from __future__ import annotations

import pytest
from rest_framework import status

from omnichannel.models import AIObservabilityEvent
from omnichannel.observability import record_ai_observability_event
from tests.security_helpers import assert_response_does_not_contain, auth_client_for, make_user_with_membership
from workspaces.factories import UserFactory, WorkspaceFactory
from workspaces.models import Member


def _summary_url(workspace) -> str:
    return f'/api/workspaces/{workspace.id}/ai-observability/summary/'


def _timeseries_url(workspace) -> str:
    return f'/api/workspaces/{workspace.id}/ai-observability/timeseries/'


def _events_url(workspace) -> str:
    return f'/api/workspaces/{workspace.id}/ai-observability/events/'


@pytest.mark.django_db
def test_owner_and_admin_see_only_own_workspace_observability() -> None:
    workspace_a = WorkspaceFactory()
    workspace_b = WorkspaceFactory()
    owner_a = make_user_with_membership(workspace_a, Member.Role.OWNER)
    admin_a = make_user_with_membership(workspace_a, Member.Role.ADMIN)
    record_ai_observability_event(
        workspace=workspace_a,
        event_type=AIObservabilityEvent.EventType.AI_PROVIDER_SUCCESS,
        status=AIObservabilityEvent.Status.SUCCESS,
        provider='openai',
    )
    record_ai_observability_event(
        workspace=workspace_b,
        event_type=AIObservabilityEvent.EventType.AI_PROVIDER_FAILED,
        status=AIObservabilityEvent.Status.FAILED,
        provider='openai',
        error_code='WORKSPACE_B_SECRET_ERROR',
    )

    owner_response = auth_client_for(owner_a).get(_summary_url(workspace_a))
    admin_response = auth_client_for(admin_a).get(_summary_url(workspace_a))

    for response in (owner_response, admin_response):
        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        assert body['totals']['ai_provider_success'] == 1
        assert body['totals']['ai_provider_failed'] == 0
        assert_response_does_not_contain(response, ['WORKSPACE_B_SECRET_ERROR', str(workspace_b.id)])


@pytest.mark.django_db
def test_agent_and_non_member_cannot_access_observability() -> None:
    workspace = WorkspaceFactory()
    agent = make_user_with_membership(workspace, Member.Role.AGENT)
    non_member = UserFactory()

    agent_response = auth_client_for(agent).get(_summary_url(workspace))
    non_member_response = auth_client_for(non_member).get(_summary_url(workspace))

    assert agent_response.status_code == status.HTTP_403_FORBIDDEN
    assert non_member_response.status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.django_db
def test_timeseries_and_events_do_not_include_other_workspace_events() -> None:
    workspace_a = WorkspaceFactory()
    workspace_b = WorkspaceFactory()
    owner_a = make_user_with_membership(workspace_a, Member.Role.OWNER)
    event_a = record_ai_observability_event(
        workspace=workspace_a,
        event_type=AIObservabilityEvent.EventType.OUTBOUND_DELIVERY_SUCCESS,
        status=AIObservabilityEvent.Status.SUCCESS,
        provider='openai',
    )
    event_b = record_ai_observability_event(
        workspace=workspace_b,
        event_type=AIObservabilityEvent.EventType.OUTBOUND_DELIVERY_FAILED,
        status=AIObservabilityEvent.Status.FAILED,
        provider='google',
        error_code='B_ONLY',
    )

    client = auth_client_for(owner_a)
    timeseries_response = client.get(_timeseries_url(workspace_a))
    events_response = client.get(_events_url(workspace_a))

    assert timeseries_response.status_code == status.HTTP_200_OK
    assert timeseries_response.json()['points'][0]['delivery_success'] == 1
    assert timeseries_response.json()['points'][0]['delivery_failed'] == 0
    assert events_response.status_code == status.HTTP_200_OK
    body = events_response.content.decode('utf-8')
    assert str(event_a.id) in body
    assert str(event_b.id) not in body
    assert 'B_ONLY' not in body


@pytest.mark.django_db
def test_observability_filters_do_not_cross_tenant_and_limit_is_capped() -> None:
    workspace_a = WorkspaceFactory()
    workspace_b = WorkspaceFactory()
    owner_a = make_user_with_membership(workspace_a, Member.Role.OWNER)
    for index in range(105):
        record_ai_observability_event(
            workspace=workspace_a,
            event_type=AIObservabilityEvent.EventType.AI_SKIPPED,
            status=AIObservabilityEvent.Status.SKIPPED,
            provider='openai',
            error_code='A_ERROR' if index == 0 else '',
        )
    record_ai_observability_event(
        workspace=workspace_b,
        event_type=AIObservabilityEvent.EventType.AI_SKIPPED,
        status=AIObservabilityEvent.Status.SKIPPED,
        provider='openai',
        error_code='B_ERROR',
    )

    response = auth_client_for(owner_a).get(
        _events_url(workspace_a),
        {
            'provider': 'openai',
            'event_type': 'AI_SKIPPED',
            'status': 'skipped',
            'limit': 999,
        },
    )

    assert response.status_code == status.HTTP_200_OK
    assert len(response.json()['results']) == 100
    assert_response_does_not_contain(response, ['B_ERROR', str(workspace_b.id)])


@pytest.mark.django_db
def test_observability_invalid_period_returns_400() -> None:
    workspace = WorkspaceFactory()
    owner = make_user_with_membership(workspace, Member.Role.OWNER)

    response = auth_client_for(owner).get(_summary_url(workspace), {'period': '90d'})

    assert response.status_code == status.HTTP_400_BAD_REQUEST


@pytest.mark.django_db
def test_observability_events_response_sanitizes_malicious_metadata() -> None:
    workspace = WorkspaceFactory()
    owner = make_user_with_membership(workspace, Member.Role.OWNER)
    event = AIObservabilityEvent.objects.create(
        workspace=workspace,
        event_type=AIObservabilityEvent.EventType.AI_PROVIDER_FAILED,
        status=AIObservabilityEvent.Status.FAILED,
        metadata={
            'source': 'test',
            'api_key': 'sk-secret',
            'payload': {'raw': True},
            'raw_payload': 'raw data',
            'body': 'message.body secret',
            'prompt': 'system prompt secret',
            'phone': '5511999999999',
            'email': 'secret@example.com',
            'Authorization': 'Bearer secret',
            'headers': {'Authorization': 'Bearer secret'},
        },
    )

    response = auth_client_for(owner).get(_events_url(workspace))

    assert response.status_code == status.HTTP_200_OK
    assert str(event.id) in response.content.decode('utf-8')
    assert response.json()['results'][0]['metadata'] == {'source': 'test'}
    assert_response_does_not_contain(
        response,
        [
            'api_key',
            'sk-secret',
            'payload',
            'raw_payload',
            'message.body',
            'body',
            'prompt',
            'system_prompt',
            'result.text',
            '5511999999999',
            'secret@example.com',
            'Authorization',
            'headers',
        ],
    )
