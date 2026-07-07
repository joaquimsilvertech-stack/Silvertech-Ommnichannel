from __future__ import annotations

import pytest
from django.contrib import admin
from django.urls import reverse

from workspaces.admin import WorkspaceAIProviderConfigAdmin
from workspaces.factories import UserFactory, WorkspaceAIProviderConfigFactory
from workspaces.models import WorkspaceAIConfig, WorkspaceAIProviderConfig

SENSITIVE_ADMIN_API_KEY = 'SENSITIVE_ADMIN_API_KEY_123'


def _decoded(response) -> str:
    return response.content.decode(response.charset or 'utf-8')


@pytest.fixture
def admin_user(db):
    return UserFactory(
        email='admin-ai-provider@example.com',
        is_staff=True,
        is_superuser=True,
    )


@pytest.fixture
def non_staff_user(db):
    return UserFactory(
        email='non-staff-ai-provider@example.com',
        is_staff=False,
        is_superuser=False,
    )


@pytest.fixture
def staff_user(db):
    return UserFactory(
        email='staff-ai-provider@example.com',
        is_active=True,
        is_staff=True,
        is_superuser=False,
    )


@pytest.fixture
def provider_config(db):
    return WorkspaceAIProviderConfigFactory(
        workspace__name='Admin Observability Workspace',
        workspace__slug='admin-observability-workspace',
        api_key=SENSITIVE_ADMIN_API_KEY,
        model_name='gpt-4o-mini-admin',
        is_active=True,
    )


@pytest.mark.django_db
def test_workspace_ai_provider_config_is_registered_and_legacy_is_not_registered() -> None:
    assert WorkspaceAIProviderConfig in admin.site._registry
    assert isinstance(admin.site._registry[WorkspaceAIProviderConfig], WorkspaceAIProviderConfigAdmin)
    assert WorkspaceAIConfig not in admin.site._registry


@pytest.mark.django_db
def test_workspace_ai_provider_admin_changelist_hides_api_key_and_shows_safe_fields(
    client,
    admin_user,
    provider_config,
) -> None:
    client.force_login(admin_user)

    response = client.get(reverse('admin:workspaces_workspaceaiproviderconfig_changelist'))

    content = _decoded(response)
    assert response.status_code == 200
    assert SENSITIVE_ADMIN_API_KEY not in content
    assert 'api_key' not in content
    assert 'Admin Observability Workspace' in content
    assert 'openai' in content
    assert 'gpt-4o-mini-admin' in content


@pytest.mark.django_db
def test_workspace_ai_provider_admin_detail_hides_api_key_and_shows_safe_fields(
    client,
    admin_user,
    provider_config,
) -> None:
    client.force_login(admin_user)

    response = client.get(
        reverse('admin:workspaces_workspaceaiproviderconfig_change', args=[provider_config.id]),
    )

    content = _decoded(response)
    assert response.status_code == 200
    assert SENSITIVE_ADMIN_API_KEY not in content
    assert 'api_key' not in content
    assert 'Admin Observability Workspace' in content
    assert 'gpt-4o-mini-admin' in content
    assert 'Save' not in content


@pytest.mark.django_db
def test_workspace_ai_provider_admin_blocks_add_change_and_delete_permissions(
    rf,
    admin_user,
    provider_config,
) -> None:
    request = rf.get('/')
    request.user = admin_user
    model_admin = admin.site._registry[WorkspaceAIProviderConfig]

    assert model_admin.has_view_permission(request, provider_config) is True
    assert model_admin.has_add_permission(request) is False
    assert model_admin.has_change_permission(request, provider_config) is False
    assert model_admin.has_delete_permission(request, provider_config) is False


@pytest.mark.django_db
def test_staff_non_superuser_cannot_view_workspace_ai_provider_changelist(
    client,
    staff_user,
    provider_config,
) -> None:
    client.force_login(staff_user)

    response = client.get(reverse('admin:workspaces_workspaceaiproviderconfig_changelist'))

    content = _decoded(response)
    assert response.status_code in {302, 403}
    assert response.status_code != 200
    assert SENSITIVE_ADMIN_API_KEY not in content
    assert 'Admin Observability Workspace' not in content
    assert 'gpt-4o-mini-admin' not in content


@pytest.mark.django_db
def test_staff_non_superuser_cannot_view_workspace_ai_provider_detail(
    client,
    staff_user,
    provider_config,
) -> None:
    client.force_login(staff_user)

    response = client.get(
        reverse('admin:workspaces_workspaceaiproviderconfig_change', args=[provider_config.pk]),
    )

    content = _decoded(response)
    assert response.status_code in {302, 403, 404}
    assert response.status_code != 200
    assert SENSITIVE_ADMIN_API_KEY not in content
    assert 'Admin Observability Workspace' not in content
    assert 'gpt-4o-mini-admin' not in content


@pytest.mark.django_db
def test_workspace_ai_provider_admin_add_view_is_forbidden(client, admin_user) -> None:
    client.force_login(admin_user)

    response = client.get(reverse('admin:workspaces_workspaceaiproviderconfig_add'))

    assert response.status_code == 403


@pytest.mark.django_db
def test_non_staff_user_cannot_access_workspace_ai_provider_admin(
    client,
    non_staff_user,
    provider_config,
) -> None:
    client.force_login(non_staff_user)

    response = client.get(reverse('admin:workspaces_workspaceaiproviderconfig_changelist'))

    assert response.status_code in {302, 403}
    assert SENSITIVE_ADMIN_API_KEY not in _decoded(response)
