from __future__ import annotations

from unittest.mock import patch

import pytest
from rest_framework import status

from omnichannel.ai.connection_test import AIProviderConnectionTestResult
from tests.security_helpers import (
    assert_not_found_or_forbidden,
    assert_response_does_not_contain,
    auth_client_for,
    make_user_with_membership,
)
from workspaces.factories import UserFactory, WorkspaceAIProviderConfigFactory, WorkspaceFactory
from workspaces.models import AIProvider, Member, WorkspaceAIProviderConfig


def _list_url(workspace) -> str:
    return f'/api/workspaces/{workspace.id}/ai-providers/'


def _detail_url(workspace, config) -> str:
    return f'/api/workspaces/{workspace.id}/ai-providers/{config.id}/'


def _action_url(workspace, config, action: str) -> str:
    return f'/api/workspaces/{workspace.id}/ai-providers/{config.id}/{action}/'


def _success_result(config) -> AIProviderConnectionTestResult:
    return AIProviderConnectionTestResult(
        success=True,
        provider=config.provider,
        model_name=config.model_name,
        message='Credencial validada com sucesso.',
    )


@pytest.mark.django_db
def test_owner_cannot_list_other_workspace_ai_provider() -> None:
    workspace_a = WorkspaceFactory()
    workspace_b = WorkspaceFactory()
    owner_a = make_user_with_membership(workspace_a, Member.Role.OWNER)
    config_a = WorkspaceAIProviderConfigFactory(workspace=workspace_a, model_name='model-a')
    config_b = WorkspaceAIProviderConfigFactory(workspace=workspace_b, model_name='model-b-secret')

    response = auth_client_for(owner_a).get(_list_url(workspace_a))

    assert response.status_code == status.HTTP_200_OK
    body = response.content.decode('utf-8')
    assert str(config_a.id) in body
    assert str(config_b.id) not in body
    assert 'model-b-secret' not in body
    assert '"api_key"' not in body
    assert 'sk-' not in body


@pytest.mark.django_db
@pytest.mark.parametrize('method', ['get', 'patch', 'put'])
def test_admin_cannot_access_or_modify_provider_from_other_workspace(method: str) -> None:
    workspace_a = WorkspaceFactory()
    workspace_b = WorkspaceFactory()
    admin_a = make_user_with_membership(workspace_a, Member.Role.ADMIN)
    config_b = WorkspaceAIProviderConfigFactory(
        workspace=workspace_b,
        api_key='sk-workspace-b-secret',
        model_name='model-b-secret',
    )
    client = auth_client_for(admin_a)
    payload = {
        'provider': AIProvider.OPENAI,
        'model_name': 'changed-by-a',
        'system_prompt': 'changed',
        'settings': {},
    }

    response = getattr(client, method)(_detail_url(workspace_a, config_b), payload, format='json')

    assert_not_found_or_forbidden(response)
    config_b.refresh_from_db()
    assert config_b.model_name == 'model-b-secret'
    assert config_b.api_key == 'sk-workspace-b-secret'
    assert_response_does_not_contain(response, ['model-b-secret', 'sk-workspace-b-secret'])


@pytest.mark.django_db
@pytest.mark.parametrize(
    ('action', 'payload'),
    [
        ('test', {}),
        ('activate', {}),
        ('deactivate', {}),
        ('credentials/replace', {'api_key': 'sk-test-new-key'}),
        ('credentials/revoke', {}),
    ],
)
def test_owner_cannot_run_provider_actions_for_other_workspace(action: str, payload: dict) -> None:
    workspace_a = WorkspaceFactory()
    workspace_b = WorkspaceFactory()
    owner_a = make_user_with_membership(workspace_a, Member.Role.OWNER)
    config_b = WorkspaceAIProviderConfigFactory(
        workspace=workspace_b,
        api_key='sk-workspace-b-secret',
        model_name='model-b-secret',
        is_active=True,
    )

    with patch('workspaces.views.test_ai_provider_connection') as mock_view_test, patch(
        'workspaces.services.test_ai_provider_connection',
    ) as mock_service_test:
        response = auth_client_for(owner_a).post(
            _action_url(workspace_a, config_b, action),
            payload,
            format='json',
        )

    assert_not_found_or_forbidden(response)
    config_b.refresh_from_db()
    assert config_b.api_key == 'sk-workspace-b-secret'
    assert config_b.model_name == 'model-b-secret'
    assert config_b.is_active is True
    mock_view_test.assert_not_called()
    mock_service_test.assert_not_called()
    assert_response_does_not_contain(response, ['model-b-secret', 'sk-workspace-b-secret'])


@pytest.mark.django_db
def test_agent_and_non_member_cannot_access_provider_admin_endpoints() -> None:
    workspace = WorkspaceFactory()
    agent = make_user_with_membership(workspace, Member.Role.AGENT)
    non_member = UserFactory()
    config = WorkspaceAIProviderConfigFactory(workspace=workspace)

    agent_response = auth_client_for(agent).get(_list_url(workspace))
    non_member_response = auth_client_for(non_member).get(_list_url(workspace))
    agent_action_response = auth_client_for(agent).post(_action_url(workspace, config, 'activate'), {}, format='json')

    assert agent_response.status_code == status.HTTP_403_FORBIDDEN
    assert non_member_response.status_code == status.HTTP_403_FORBIDDEN
    assert agent_action_response.status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.django_db
def test_payload_workspace_or_workspace_id_cannot_cross_tenant() -> None:
    workspace_a = WorkspaceFactory()
    workspace_b = WorkspaceFactory()
    owner_a = make_user_with_membership(workspace_a, Member.Role.OWNER)
    client = auth_client_for(owner_a)

    create_response = client.post(
        _list_url(workspace_a),
        {
            'workspace_id': str(workspace_b.id),
            'provider': AIProvider.OPENAI,
            'model_name': 'gpt-4o-mini',
            'system_prompt': 'Prompt A',
            'settings': {},
            'api_key': 'sk-test-create-key',
        },
        format='json',
    )

    assert create_response.status_code == status.HTTP_400_BAD_REQUEST
    assert not WorkspaceAIProviderConfig.objects.filter(workspace=workspace_b, model_name='gpt-4o-mini').exists()
    assert_response_does_not_contain(create_response, ['sk-test-create-key'])


@pytest.mark.django_db
@pytest.mark.parametrize(
    'payload',
    [
        {'is_active': True},
        {'api_key': 'sk-should-use-dedicated-endpoint'},
        {'workspace': 'malicious'},
    ],
)
def test_generic_update_rejects_sensitive_or_workspace_payload(payload: dict) -> None:
    workspace = WorkspaceFactory()
    owner = make_user_with_membership(workspace, Member.Role.OWNER)
    config = WorkspaceAIProviderConfigFactory(workspace=workspace, api_key='sk-original-key')

    response = auth_client_for(owner).patch(_detail_url(workspace, config), payload, format='json')

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    config.refresh_from_db()
    assert config.api_key == 'sk-original-key'
    assert_response_does_not_contain(response, ['sk-should-use-dedicated-endpoint', 'sk-original-key'])


@pytest.mark.django_db
def test_activate_provider_in_workspace_a_does_not_deactivate_workspace_b_provider() -> None:
    workspace_a = WorkspaceFactory()
    workspace_b = WorkspaceFactory()
    owner_a = make_user_with_membership(workspace_a, Member.Role.OWNER)
    config_a = WorkspaceAIProviderConfigFactory(workspace=workspace_a, is_active=False)
    config_b = WorkspaceAIProviderConfigFactory(workspace=workspace_b, is_active=True)

    with patch('workspaces.views.test_ai_provider_connection', return_value=_success_result(config_a)):
        response = auth_client_for(owner_a).post(_action_url(workspace_a, config_a, 'activate'), {}, format='json')

    assert response.status_code == status.HTTP_200_OK
    config_a.refresh_from_db()
    config_b.refresh_from_db()
    assert config_a.is_active is True
    assert config_b.is_active is True


@pytest.mark.django_db
def test_revoke_and_failed_replace_do_not_mutate_other_workspace_provider() -> None:
    workspace_a = WorkspaceFactory()
    workspace_b = WorkspaceFactory()
    owner_a = make_user_with_membership(workspace_a, Member.Role.OWNER)
    config_a = WorkspaceAIProviderConfigFactory(workspace=workspace_a, api_key='sk-a-old-key')
    config_b = WorkspaceAIProviderConfigFactory(workspace=workspace_b, api_key='sk-b-secret-key', is_active=True)
    client = auth_client_for(owner_a)

    replace_response = client.post(
        _action_url(workspace_a, config_a, 'credentials/replace'),
        {'api_key': ''},
        format='json',
    )
    revoke_response = client.post(_action_url(workspace_a, config_a, 'credentials/revoke'), {}, format='json')

    assert replace_response.status_code == status.HTTP_400_BAD_REQUEST
    assert revoke_response.status_code == status.HTTP_200_OK
    config_a.refresh_from_db()
    config_b.refresh_from_db()
    assert config_a.api_key == ''
    assert config_b.api_key == 'sk-b-secret-key'
    assert config_b.is_active is True
    assert_response_does_not_contain(replace_response, ['sk-a-old-key', 'sk-b-secret-key'])
    assert_response_does_not_contain(revoke_response, ['sk-a-old-key', 'sk-b-secret-key', '"api_key"'])
