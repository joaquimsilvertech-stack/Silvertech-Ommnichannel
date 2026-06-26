from __future__ import annotations

import pytest
from rest_framework import status
from rest_framework.test import APIClient

from workspaces.factories import WorkspaceFactory
from workspaces.models import Member, Workspace


@pytest.mark.django_db
def test_unauthenticated_user_cannot_access_workspaces() -> None:
    client = APIClient()

    response = client.get('/api/workspaces/workspaces/')

    assert response.status_code == status.HTTP_401_UNAUTHORIZED


@pytest.mark.django_db
def test_authenticated_user_can_list_own_workspaces(
    api_client: APIClient,
    tenant_workspace: Workspace,
    tenant_member: Member,
) -> None:
    response = api_client.get('/api/workspaces/workspaces/')

    assert response.status_code == status.HTTP_200_OK
    response_data = response.json()
    workspace_ids = {item['id'] for item in response_data}
    assert str(tenant_workspace.id) in workspace_ids


@pytest.mark.django_db
def test_user_cannot_access_other_tenant_workspace(
    api_client: APIClient,
    auth_user,
) -> None:
    other_workspace = WorkspaceFactory()

    response = api_client.get(f'/api/workspaces/workspaces/{other_workspace.id}/')

    assert response.status_code in {
        status.HTTP_403_FORBIDDEN,
        status.HTTP_404_NOT_FOUND,
    }
