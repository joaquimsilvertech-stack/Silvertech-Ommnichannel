from __future__ import annotations

import pytest
from rest_framework import status

from tests.security_helpers import (
    assert_not_found_or_forbidden,
    assert_response_does_not_contain,
    auth_client_for,
    make_user_with_membership,
)
from workspaces.factories import MemberFactory, UserFactory, WorkspaceFactory
from workspaces.models import Member, WorkspaceInvite


@pytest.mark.django_db
def test_non_member_cannot_access_other_workspace_detail(api_client) -> None:
    other_workspace = WorkspaceFactory(name='Workspace B confidencial')

    response = api_client.get(f'/api/workspaces/workspaces/{other_workspace.id}/')

    assert_not_found_or_forbidden(response)
    assert_response_does_not_contain(response, ['Workspace B confidencial'])


@pytest.mark.django_db
def test_workspace_list_returns_only_member_workspaces(api_client, tenant_workspace) -> None:
    other_workspace = WorkspaceFactory(name='Workspace B invisivel')

    response = api_client.get('/api/workspaces/workspaces/')

    assert response.status_code == status.HTTP_200_OK
    body = response.content.decode('utf-8')
    assert str(tenant_workspace.id) in body
    assert str(other_workspace.id) not in body
    assert 'Workspace B invisivel' not in body


@pytest.mark.django_db
def test_agent_cannot_use_member_or_invite_admin_endpoints(tenant_workspace) -> None:
    agent = make_user_with_membership(tenant_workspace, role=Member.Role.AGENT)
    client = auth_client_for(agent)

    members_response = client.get('/api/workspaces/members/')
    invite_response = client.post(
        '/api/workspaces/invites/',
        {
            'workspace_id': str(tenant_workspace.id),
            'email': 'new-agent@example.com',
            'role': Member.Role.AGENT,
        },
        format='json',
    )

    assert members_response.status_code == status.HTTP_200_OK
    assert members_response.json() == []
    assert invite_response.status_code == status.HTTP_403_FORBIDDEN
    assert not WorkspaceInvite.objects.filter(email='new-agent@example.com').exists()


@pytest.mark.django_db
def test_owner_cannot_create_member_in_other_workspace(tenant_workspace, tenant_member, auth_user) -> None:
    other_workspace = WorkspaceFactory()
    client = auth_client_for(auth_user)
    target_user = UserFactory()
    before_count = Member.objects.filter(workspace=other_workspace).count()

    response = client.post(
        '/api/workspaces/members/',
        {
            'workspace_id': str(other_workspace.id),
            'user_id': str(target_user.id),
            'role': Member.Role.ADMIN,
        },
        format='json',
    )

    assert response.status_code == status.HTTP_403_FORBIDDEN
    assert Member.objects.filter(workspace=other_workspace).count() == before_count


@pytest.mark.django_db
def test_owner_cannot_create_invite_in_other_workspace(tenant_workspace, tenant_member, auth_user) -> None:
    other_workspace = WorkspaceFactory(name='Workspace B invites')
    client = auth_client_for(auth_user)

    response = client.post(
        '/api/workspaces/invites/',
        {
            'workspace_id': str(other_workspace.id),
            'email': 'outside@example.com',
            'role': Member.Role.AGENT,
        },
        format='json',
    )

    assert response.status_code == status.HTTP_403_FORBIDDEN
    assert not WorkspaceInvite.objects.filter(workspace=other_workspace).exists()
    assert_response_does_not_contain(response, ['Workspace B invites'])


@pytest.mark.django_db
def test_member_detail_from_other_workspace_returns_404_or_403(tenant_workspace, tenant_member, auth_user) -> None:
    other_workspace = WorkspaceFactory()
    other_member = MemberFactory(workspace=other_workspace)
    client = auth_client_for(auth_user)

    response = client.get(f'/api/workspaces/members/{other_member.id}/')

    assert_not_found_or_forbidden(response)
    assert_response_does_not_contain(response, [other_member.user.email, str(other_workspace.id)])
