from __future__ import annotations

import pytest
from rest_framework import status

from automations.models import Flow
from tests.security_helpers import (
    assert_not_found_or_forbidden,
    assert_response_does_not_contain,
    auth_client_for,
    make_user_with_membership,
)
from workspaces.factories import WorkspaceFactory
from workspaces.models import Member


@pytest.mark.django_db
def test_flow_list_and_filters_do_not_cross_workspace() -> None:
    workspace_a = WorkspaceFactory()
    workspace_b = WorkspaceFactory()
    owner_a = make_user_with_membership(workspace_a, Member.Role.OWNER)
    flow_a = Flow.objects.create(
        workspace=workspace_a,
        name='Flow A',
        trigger={'type': 'new_message'},
        nodes=[],
        is_active=True,
    )
    flow_b = Flow.objects.create(
        workspace=workspace_b,
        name='Flow B Secreto',
        trigger={'type': 'new_message'},
        nodes=[],
        is_active=True,
    )

    response = auth_client_for(owner_a).get('/api/automations/flows/', {'is_active': 'true'})

    assert response.status_code == status.HTTP_200_OK
    body = response.content.decode('utf-8')
    assert str(flow_a.id) in body
    assert str(flow_b.id) not in body
    assert 'Flow B Secreto' not in body


@pytest.mark.django_db
@pytest.mark.parametrize('method', ['get', 'patch', 'delete'])
def test_flow_detail_update_delete_other_workspace_is_blocked(method: str) -> None:
    workspace_a = WorkspaceFactory()
    workspace_b = WorkspaceFactory()
    owner_a = make_user_with_membership(workspace_a, Member.Role.OWNER)
    flow_b = Flow.objects.create(
        workspace=workspace_b,
        name='Flow B Secreto',
        trigger={'type': 'new_message'},
        nodes=[],
    )

    response = getattr(auth_client_for(owner_a), method)(
        f'/api/automations/flows/{flow_b.id}/',
        {'name': 'Changed'},
        format='json',
    )

    assert_not_found_or_forbidden(response)
    flow_b.refresh_from_db()
    assert flow_b.name == 'Flow B Secreto'
    assert_response_does_not_contain(response, ['Flow B Secreto', str(workspace_b.id)])


@pytest.mark.django_db
def test_flow_create_cannot_force_other_workspace() -> None:
    workspace_a = WorkspaceFactory()
    workspace_b = WorkspaceFactory()
    owner_a = make_user_with_membership(workspace_a, Member.Role.OWNER)

    response = auth_client_for(owner_a).post(
        '/api/automations/flows/',
        {
            'workspace_id': str(workspace_b.id),
            'name': 'Cross tenant flow',
            'trigger': {'type': 'new_message'},
            'nodes': [],
            'is_active': True,
        },
        format='json',
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert not Flow.objects.filter(workspace=workspace_b, name='Cross tenant flow').exists()


@pytest.mark.django_db
def test_agent_can_only_see_flows_from_own_workspace_if_allowed_by_module() -> None:
    workspace_a = WorkspaceFactory()
    workspace_b = WorkspaceFactory()
    agent_a = make_user_with_membership(workspace_a, Member.Role.AGENT)
    flow_a = Flow.objects.create(workspace=workspace_a, name='Agent Flow A')
    flow_b = Flow.objects.create(workspace=workspace_b, name='Agent Flow B Secret')

    response = auth_client_for(agent_a).get('/api/automations/flows/')

    assert response.status_code == status.HTTP_200_OK
    body = response.content.decode('utf-8')
    assert str(flow_a.id) in body
    assert str(flow_b.id) not in body
    assert 'Agent Flow B Secret' not in body
