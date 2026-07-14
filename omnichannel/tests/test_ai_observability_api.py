from __future__ import annotations

from datetime import timedelta

import pytest
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import AccessToken

from omnichannel.models import AIObservabilityEvent
from omnichannel.observability import record_ai_observability_event
from workspaces.factories import MemberFactory, UserFactory, WorkspaceFactory
from workspaces.models import Member, Workspace


def _client_for(user) -> APIClient:
    client = APIClient()
    token = AccessToken.for_user(user)
    client.credentials(HTTP_AUTHORIZATION=f'Bearer {token}')
    return client


def _summary_url(workspace: Workspace) -> str:
    return f'/api/workspaces/{workspace.id}/ai-observability/summary/'


def _timeseries_url(workspace: Workspace) -> str:
    return f'/api/workspaces/{workspace.id}/ai-observability/timeseries/'


def _events_url(workspace: Workspace) -> str:
    return f'/api/workspaces/{workspace.id}/ai-observability/events/'


@pytest.mark.django_db
def test_owner_can_access_observability_summary(api_client: APIClient, tenant_workspace: Workspace) -> None:
    record_ai_observability_event(
        workspace=tenant_workspace,
        event_type=AIObservabilityEvent.EventType.AI_SCHEDULED,
        status=AIObservabilityEvent.Status.PENDING,
    )

    response = api_client.get(_summary_url(tenant_workspace))

    assert response.status_code == status.HTTP_200_OK
    assert response.json()['totals']['ai_scheduled'] == 1


@pytest.mark.django_db
def test_admin_can_access_observability_summary() -> None:
    workspace = WorkspaceFactory()
    user = UserFactory()
    MemberFactory(user=user, workspace=workspace, role=Member.Role.ADMIN)

    response = _client_for(user).get(_summary_url(workspace))

    assert response.status_code == status.HTTP_200_OK


@pytest.mark.django_db
def test_agent_and_non_member_cannot_access_observability_summary() -> None:
    workspace = WorkspaceFactory()
    agent = UserFactory()
    non_member = UserFactory()
    MemberFactory(user=agent, workspace=workspace, role=Member.Role.AGENT)

    agent_response = _client_for(agent).get(_summary_url(workspace))
    non_member_response = _client_for(non_member).get(_summary_url(workspace))

    assert agent_response.status_code == status.HTTP_403_FORBIDDEN
    assert non_member_response.status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.django_db
def test_summary_does_not_leak_other_workspace_data(api_client: APIClient, tenant_workspace: Workspace) -> None:
    other_workspace = WorkspaceFactory()
    record_ai_observability_event(
        workspace=tenant_workspace,
        event_type=AIObservabilityEvent.EventType.AI_PROVIDER_SUCCESS,
        status=AIObservabilityEvent.Status.SUCCESS,
        provider='openai',
    )
    record_ai_observability_event(
        workspace=other_workspace,
        event_type=AIObservabilityEvent.EventType.AI_PROVIDER_FAILED,
        status=AIObservabilityEvent.Status.FAILED,
        provider='openai',
        error_code='OTHER_WORKSPACE_ERROR',
    )

    response = api_client.get(_summary_url(tenant_workspace))

    assert response.status_code == status.HTTP_200_OK
    body = response.json()
    assert body['totals']['ai_provider_success'] == 1
    assert body['totals']['ai_provider_failed'] == 0
    assert body['errors'] == []


@pytest.mark.django_db
def test_invalid_period_returns_400(api_client: APIClient, tenant_workspace: Workspace) -> None:
    response = api_client.get(_summary_url(tenant_workspace), {'period': '90d'})

    assert response.status_code == status.HTTP_400_BAD_REQUEST


@pytest.mark.django_db
def test_period_filter_and_provider_filter(api_client: APIClient, tenant_workspace: Workspace) -> None:
    old_event = record_ai_observability_event(
        workspace=tenant_workspace,
        event_type=AIObservabilityEvent.EventType.AI_PROVIDER_SUCCESS,
        status=AIObservabilityEvent.Status.SUCCESS,
        provider='openai',
    )
    AIObservabilityEvent.objects.filter(id=old_event.id).update(
        created_at=timezone.now() - timedelta(days=8),
    )
    record_ai_observability_event(
        workspace=tenant_workspace,
        event_type=AIObservabilityEvent.EventType.AI_PROVIDER_SUCCESS,
        status=AIObservabilityEvent.Status.SUCCESS,
        provider='openai',
    )
    record_ai_observability_event(
        workspace=tenant_workspace,
        event_type=AIObservabilityEvent.EventType.AI_PROVIDER_SUCCESS,
        status=AIObservabilityEvent.Status.SUCCESS,
        provider='google',
    )

    response = api_client.get(_summary_url(tenant_workspace), {'period': '7d', 'provider': 'openai'})

    assert response.status_code == status.HTTP_200_OK
    assert response.json()['totals']['ai_provider_success'] == 1


@pytest.mark.django_db
def test_events_respect_limit_and_do_not_return_sensitive_fields(
    api_client: APIClient,
    tenant_workspace: Workspace,
) -> None:
    for index in range(3):
        record_ai_observability_event(
            workspace=tenant_workspace,
            event_type=AIObservabilityEvent.EventType.AI_SKIPPED,
            status=AIObservabilityEvent.Status.SKIPPED,
            reason_code=f'reason-{index}',
            metadata={
                'source': 'webhook',
                'api_key': 'sk-secret',
                'body': 'conteudo',
            },
        )

    response = api_client.get(_events_url(tenant_workspace), {'limit': 2})

    assert response.status_code == status.HTTP_200_OK
    results = response.json()['results']
    assert len(results) == 2
    response_text = response.content.decode('utf-8')
    assert 'api_key' not in response_text
    assert 'sk-secret' not in response_text
    assert 'conteudo' not in response_text
    assert 'body' not in response_text


@pytest.mark.django_db
def test_timeseries_returns_bucketed_points(api_client: APIClient, tenant_workspace: Workspace) -> None:
    record_ai_observability_event(
        workspace=tenant_workspace,
        event_type=AIObservabilityEvent.EventType.AI_PROVIDER_FAILED,
        status=AIObservabilityEvent.Status.FAILED,
    )

    response = api_client.get(_timeseries_url(tenant_workspace), {'period': '24h'})

    assert response.status_code == status.HTTP_200_OK
    body = response.json()
    assert body['bucket'] == 'hour'
    assert body['points'][0]['ai_failed'] == 1
