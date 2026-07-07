from __future__ import annotations

import pytest
from django.urls import reverse

from workspaces.factories import UserFactory, WorkspaceFactory
from workspaces.models import Workspace

LEGACY_SYSTEM_PROMPT = 'LEGACY_SYSTEM_PROMPT_SHOULD_NOT_APPEAR_123'


def _decoded(response) -> str:
    return response.content.decode(response.charset or 'utf-8')


@pytest.fixture
def admin_user(db):
    return UserFactory(
        email='workspace-admin@example.com',
        is_staff=True,
        is_superuser=True,
    )


@pytest.mark.django_db
def test_workspace_admin_add_form_does_not_show_ai_system_prompt(client, admin_user) -> None:
    client.force_login(admin_user)

    response = client.get(reverse('admin:workspaces_workspace_add'))

    content = _decoded(response)
    assert response.status_code == 200
    assert 'ai_system_prompt' not in content
    assert LEGACY_SYSTEM_PROMPT not in content


@pytest.mark.django_db
def test_workspace_admin_change_form_does_not_show_legacy_ai_system_prompt(
    client,
    admin_user,
) -> None:
    workspace = WorkspaceFactory(ai_system_prompt=LEGACY_SYSTEM_PROMPT)
    client.force_login(admin_user)

    response = client.get(reverse('admin:workspaces_workspace_change', args=[workspace.id]))

    content = _decoded(response)
    assert response.status_code == 200
    assert 'ai_system_prompt' not in content
    assert LEGACY_SYSTEM_PROMPT not in content


@pytest.mark.django_db
def test_workspace_admin_can_create_workspace_without_ai_system_prompt(client, admin_user) -> None:
    client.force_login(admin_user)

    response = client.post(
        reverse('admin:workspaces_workspace_add'),
        {
            'name': 'Workspace Admin Created',
            'slug': 'workspace-admin-created',
        },
    )

    assert response.status_code == 302
    workspace = Workspace.objects.get(slug='workspace-admin-created')
    assert workspace.name == 'Workspace Admin Created'
    assert workspace.ai_system_prompt is None


@pytest.mark.django_db
def test_workspace_admin_edit_does_not_modify_ai_system_prompt(client, admin_user) -> None:
    workspace = WorkspaceFactory(
        name='Workspace Before Admin Edit',
        slug='workspace-before-admin-edit',
        ai_system_prompt=LEGACY_SYSTEM_PROMPT,
    )
    client.force_login(admin_user)

    response = client.post(
        reverse('admin:workspaces_workspace_change', args=[workspace.id]),
        {
            'name': 'Workspace After Admin Edit',
            'slug': 'workspace-after-admin-edit',
        },
    )

    assert response.status_code == 302
    workspace.refresh_from_db()
    assert workspace.name == 'Workspace After Admin Edit'
    assert workspace.slug == 'workspace-after-admin-edit'
    assert workspace.ai_system_prompt == LEGACY_SYSTEM_PROMPT
