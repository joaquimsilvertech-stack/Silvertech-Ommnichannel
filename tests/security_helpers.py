from __future__ import annotations

from collections.abc import Iterable

from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import AccessToken

from workspaces.factories import MemberFactory, UserFactory, WorkspaceFactory
from workspaces.models import Member


def auth_client_for(user) -> APIClient:
    client = APIClient()
    token = AccessToken.for_user(user)
    client.credentials(HTTP_AUTHORIZATION=f'Bearer {token}')
    return client


def make_user_with_membership(workspace, role: str = Member.Role.OWNER):
    user = UserFactory()
    MemberFactory(user=user, workspace=workspace, role=role)
    return user


def make_workspace_pair():
    return WorkspaceFactory(), WorkspaceFactory()


def assert_not_found_or_forbidden(response) -> None:
    assert response.status_code in {403, 404}


def assert_response_does_not_contain(response, forbidden_values: Iterable[object]) -> None:
    body = response.content.decode('utf-8', errors='ignore')
    for value in forbidden_values:
        if value in (None, ''):
            continue
        assert str(value) not in body


def assert_no_cross_workspace_mutation(
    model,
    workspace,
    expected_count: int,
    *,
    workspace_lookup: str = 'workspace',
) -> None:
    assert model.objects.filter(**{workspace_lookup: workspace}).count() == expected_count
