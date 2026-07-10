from __future__ import annotations

import logging
from unittest.mock import patch

import pytest
from django.conf import settings
from rest_framework import status
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import AccessToken

from omnichannel.ai.connection_test import AIProviderConnectionTestResult
from omnichannel.models import Message
from workspaces.factories import (
    MemberFactory,
    UserFactory,
    WorkspaceAIProviderConfigFactory,
    WorkspaceFactory,
)
from workspaces.models import AIProvider, Member, WorkspaceAIProviderConfig
from workspaces.views import WorkspaceAIProviderConfigViewSet


def _client_for(user) -> APIClient:
    client = APIClient()
    token = AccessToken.for_user(user)
    client.credentials(HTTP_AUTHORIZATION=f'Bearer {token}')
    return client


def _admin_client(workspace=None, *, role=Member.Role.ADMIN):
    user = UserFactory()
    workspace = workspace or WorkspaceFactory()
    MemberFactory(user=user, workspace=workspace, role=role)
    return _client_for(user), user, workspace


def _activate_url(workspace, config) -> str:
    return f'/api/workspaces/{workspace.id}/ai-providers/{config.id}/activate/'


def _deactivate_url(workspace, config) -> str:
    return f'/api/workspaces/{workspace.id}/ai-providers/{config.id}/deactivate/'


def _detail_url(workspace, config) -> str:
    return f'/api/workspaces/{workspace.id}/ai-providers/{config.id}/'


def _success_result(config) -> AIProviderConnectionTestResult:
    return AIProviderConnectionTestResult(
        success=True,
        provider=config.provider,
        model_name=config.model_name,
        message='Credencial validada com sucesso.',
    )


def _error_result(config, error_code: str) -> AIProviderConnectionTestResult:
    return AIProviderConnectionTestResult(
        success=False,
        provider=config.provider,
        model_name=config.model_name,
        error_code=error_code,
        message='Mensagem sanitizada do erro.',
    )


def _response_text(response) -> str:
    return response.content.decode('utf-8')


@pytest.mark.django_db
def test_unauthenticated_user_cannot_activate_provider() -> None:
    config = WorkspaceAIProviderConfigFactory(is_active=False)

    response = APIClient().post(_activate_url(config.workspace, config), {}, format='json')

    assert response.status_code == status.HTTP_401_UNAUTHORIZED


@pytest.mark.django_db
def test_non_member_cannot_activate_provider() -> None:
    config = WorkspaceAIProviderConfigFactory(is_active=False)
    client = _client_for(UserFactory())

    response = client.post(_activate_url(config.workspace, config), {}, format='json')

    assert response.status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.django_db
def test_agent_cannot_activate_or_deactivate_provider() -> None:
    config = WorkspaceAIProviderConfigFactory(is_active=False)
    user = UserFactory()
    MemberFactory(user=user, workspace=config.workspace, role=Member.Role.AGENT)
    client = _client_for(user)

    activate_response = client.post(_activate_url(config.workspace, config), {}, format='json')
    deactivate_response = client.post(_deactivate_url(config.workspace, config), {}, format='json')

    assert activate_response.status_code == status.HTTP_403_FORBIDDEN
    assert deactivate_response.status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.django_db
@pytest.mark.parametrize('role', [Member.Role.ADMIN, Member.Role.OWNER])
def test_admin_or_owner_can_activate_provider_with_valid_connection(role: str) -> None:
    client, _, workspace = _admin_client(role=role)
    config = WorkspaceAIProviderConfigFactory(workspace=workspace, is_active=False)

    with patch('workspaces.views.test_ai_provider_connection', return_value=_success_result(config)):
        response = client.post(_activate_url(workspace, config), {}, format='json')

    assert response.status_code == status.HTTP_200_OK
    body = response.json()
    assert body['success'] is True
    assert body['is_active'] is True
    assert body['provider'] == AIProvider.OPENAI
    config.refresh_from_db()
    assert config.is_active is True


@pytest.mark.django_db
def test_activate_provider_deactivates_other_provider_in_same_workspace_only() -> None:
    client, _, workspace = _admin_client()
    other_workspace_active = WorkspaceAIProviderConfigFactory(is_active=True)
    same_workspace_active = WorkspaceAIProviderConfigFactory(
        workspace=workspace,
        provider=AIProvider.ANTHROPIC,
        is_active=True,
    )
    target = WorkspaceAIProviderConfigFactory(
        workspace=workspace,
        provider=AIProvider.OPENAI,
        is_active=False,
    )

    with patch('workspaces.views.test_ai_provider_connection', return_value=_success_result(target)):
        response = client.post(_activate_url(workspace, target), {}, format='json')

    assert response.status_code == status.HTTP_200_OK
    same_workspace_active.refresh_from_db()
    other_workspace_active.refresh_from_db()
    target.refresh_from_db()
    assert same_workspace_active.is_active is False
    assert target.is_active is True
    assert other_workspace_active.is_active is True
    assert WorkspaceAIProviderConfig.objects.filter(workspace=workspace, is_active=True).count() == 1


@pytest.mark.django_db
def test_activate_other_workspace_config_returns_404() -> None:
    client, _, workspace = _admin_client()
    other_config = WorkspaceAIProviderConfigFactory(is_active=False)

    response = client.post(_activate_url(workspace, other_config), {}, format='json')

    assert response.status_code == status.HTTP_404_NOT_FOUND


@pytest.mark.django_db
def test_unsupported_provider_does_not_activate() -> None:
    client, _, workspace = _admin_client()
    config = WorkspaceAIProviderConfigFactory(
        workspace=workspace,
        provider=AIProvider.ANTHROPIC,
        is_active=False,
    )

    with patch('workspaces.views.test_ai_provider_connection') as mock_test:
        response = client.post(_activate_url(workspace, config), {}, format='json')

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert response.json()['error_code'] == 'UNSUPPORTED_PROVIDER'
    mock_test.assert_not_called()
    config.refresh_from_db()
    assert config.is_active is False


@pytest.mark.django_db
def test_provider_without_api_key_does_not_activate() -> None:
    client, _, workspace = _admin_client()
    config = WorkspaceAIProviderConfigFactory(workspace=workspace, api_key='', is_active=False)

    with patch('workspaces.views.test_ai_provider_connection') as mock_test:
        response = client.post(_activate_url(workspace, config), {}, format='json')

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert response.json()['error_code'] == 'MISSING_API_KEY'
    mock_test.assert_not_called()
    config.refresh_from_db()
    assert config.is_active is False


@pytest.mark.django_db
@pytest.mark.parametrize(
    ('error_code', 'status_code'),
    [
        ('INVALID_CREDENTIALS', status.HTTP_400_BAD_REQUEST),
        ('RATE_LIMITED', status.HTTP_429_TOO_MANY_REQUESTS),
        ('PROVIDER_TIMEOUT', status.HTTP_504_GATEWAY_TIMEOUT),
        ('PROVIDER_UNAVAILABLE', status.HTTP_503_SERVICE_UNAVAILABLE),
        ('INVALID_REQUEST', status.HTTP_400_BAD_REQUEST),
        ('PROVIDER_ERROR', status.HTTP_502_BAD_GATEWAY),
    ],
)
def test_connection_failure_does_not_activate(error_code: str, status_code: int) -> None:
    client, _, workspace = _admin_client()
    config = WorkspaceAIProviderConfigFactory(workspace=workspace, is_active=False)

    with patch('workspaces.views.test_ai_provider_connection', return_value=_error_result(config, error_code)):
        response = client.post(_activate_url(workspace, config), {}, format='json')

    assert response.status_code == status_code
    assert response.json()['success'] is False
    assert response.json()['error_code'] == error_code
    config.refresh_from_db()
    assert config.is_active is False


@pytest.mark.django_db
def test_activation_error_response_and_logs_do_not_expose_api_key(caplog) -> None:
    client, _, workspace = _admin_client()
    secret = 'sk-activation-secret-key'
    config = WorkspaceAIProviderConfigFactory(workspace=workspace, api_key=secret, is_active=False)
    caplog.set_level(logging.WARNING)

    with patch(
        'workspaces.views.test_ai_provider_connection',
        return_value=_error_result(config, 'INVALID_CREDENTIALS'),
    ):
        response = client.post(_activate_url(workspace, config), {}, format='json')

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert secret not in _response_text(response)
    assert secret not in caplog.text


@pytest.mark.django_db
def test_activating_already_active_provider_is_idempotent_and_skips_external_test() -> None:
    client, _, workspace = _admin_client()
    config = WorkspaceAIProviderConfigFactory(workspace=workspace, is_active=True)

    with patch('workspaces.views.test_ai_provider_connection') as mock_test:
        response = client.post(_activate_url(workspace, config), {}, format='json')

    assert response.status_code == status.HTTP_200_OK
    assert response.json()['is_active'] is True
    mock_test.assert_not_called()


@pytest.mark.django_db
def test_activate_rejects_temporary_api_key_and_uses_saved_key_only() -> None:
    client, _, workspace = _admin_client()
    secret = 'sk-temporary-activation-key'
    config = WorkspaceAIProviderConfigFactory(workspace=workspace, is_active=False)

    with patch('workspaces.views.test_ai_provider_connection') as mock_test:
        response = client.post(
            _activate_url(workspace, config),
            {'api_key': secret},
            format='json',
        )

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert response.json()['error_code'] == 'TEMPORARY_API_KEY_NOT_ALLOWED'
    assert secret not in _response_text(response)
    mock_test.assert_not_called()


@pytest.mark.django_db
def test_activate_calls_connection_test_with_saved_config_only() -> None:
    client, _, workspace = _admin_client()
    config = WorkspaceAIProviderConfigFactory(workspace=workspace, is_active=False)

    with patch('workspaces.views.test_ai_provider_connection', return_value=_success_result(config)) as mock_test:
        response = client.post(_activate_url(workspace, config), {}, format='json')

    assert response.status_code == status.HTTP_200_OK
    mock_test.assert_called_once_with(provider_config=config)


@pytest.mark.django_db
def test_get_and_delete_activate_endpoint_are_not_allowed() -> None:
    client, _, workspace = _admin_client()
    config = WorkspaceAIProviderConfigFactory(workspace=workspace, is_active=False)

    get_response = client.get(_activate_url(workspace, config))
    delete_response = client.delete(_activate_url(workspace, config))

    assert get_response.status_code == status.HTTP_405_METHOD_NOT_ALLOWED
    assert delete_response.status_code == status.HTTP_405_METHOD_NOT_ALLOWED


@pytest.mark.django_db
def test_unauthenticated_user_cannot_deactivate_provider() -> None:
    config = WorkspaceAIProviderConfigFactory(is_active=True)

    response = APIClient().post(_deactivate_url(config.workspace, config), {}, format='json')

    assert response.status_code == status.HTTP_401_UNAUTHORIZED


@pytest.mark.django_db
@pytest.mark.parametrize('role', [Member.Role.ADMIN, Member.Role.OWNER])
def test_admin_or_owner_can_deactivate_provider(role: str) -> None:
    client, _, workspace = _admin_client(role=role)
    config = WorkspaceAIProviderConfigFactory(workspace=workspace, is_active=True)

    with patch('workspaces.views.test_ai_provider_connection') as mock_test:
        response = client.post(_deactivate_url(workspace, config), {}, format='json')

    assert response.status_code == status.HTTP_200_OK
    assert response.json()['is_active'] is False
    mock_test.assert_not_called()
    config.refresh_from_db()
    assert config.is_active is False


@pytest.mark.django_db
def test_deactivate_inactive_provider_is_successful_and_keeps_config() -> None:
    client, _, workspace = _admin_client()
    config = WorkspaceAIProviderConfigFactory(
        workspace=workspace,
        api_key='sk-deactivate-kept-key',
        settings={'temperature': 0.1},
        is_active=False,
    )

    response = client.post(_deactivate_url(workspace, config), {}, format='json')

    assert response.status_code == status.HTTP_200_OK
    config.refresh_from_db()
    assert config.is_active is False
    assert config.api_key == 'sk-deactivate-kept-key'
    assert config.settings == {'temperature': 0.1}


@pytest.mark.django_db
def test_activate_and_deactivate_do_not_touch_message_celery_or_evolution() -> None:
    client, _, workspace = _admin_client()
    config = WorkspaceAIProviderConfigFactory(workspace=workspace, is_active=False)
    initial_message_count = Message.objects.count()

    with (
        patch('workspaces.views.test_ai_provider_connection', return_value=_success_result(config)),
        patch('omnichannel.tasks.process_ai_response.delay') as mock_celery,
        patch('omnichannel.services.send_whatsapp_message') as mock_evolution,
        patch('omnichannel.ai.providers.openai.openai.OpenAI') as mock_openai,
    ):
        activate_response = client.post(_activate_url(workspace, config), {}, format='json')
        deactivate_response = client.post(_deactivate_url(workspace, config), {}, format='json')

    assert activate_response.status_code == status.HTTP_200_OK
    assert deactivate_response.status_code == status.HTTP_200_OK
    assert Message.objects.count() == initial_message_count
    mock_celery.assert_not_called()
    mock_evolution.assert_not_called()
    mock_openai.assert_not_called()


@pytest.mark.django_db
@pytest.mark.parametrize('method', ['post', 'put', 'patch'])
def test_generic_endpoints_reject_is_active(method: str) -> None:
    client, _, workspace = _admin_client()
    if method == 'post':
        response = client.post(
            f'/api/workspaces/{workspace.id}/ai-providers/',
            {
                'provider': AIProvider.OPENAI,
                'model_name': 'gpt-4o-mini',
                'system_prompt': 'Seja conciso.',
                'settings': {},
                'api_key': 'sk-generic-create-key',
                'is_active': True,
            },
            format='json',
        )
    else:
        config = WorkspaceAIProviderConfigFactory(workspace=workspace, is_active=False)
        payload = {
            'provider': config.provider,
            'model_name': config.model_name,
            'system_prompt': config.system_prompt,
            'settings': config.settings,
            'is_active': True,
        }
        client_method = getattr(client, method)
        response = client_method(_detail_url(workspace, config), payload, format='json')

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert 'api_key' not in _response_text(response)


@pytest.mark.django_db
def test_generic_patch_without_is_active_still_updates_allowed_fields() -> None:
    client, _, workspace = _admin_client()
    config = WorkspaceAIProviderConfigFactory(workspace=workspace, is_active=False)

    response = client.patch(
        _detail_url(workspace, config),
        {
            'model_name': 'gpt-4.1-mini',
            'settings': {'temperature': 0.2},
            'api_key': 'sk-updated-generic-key',
        },
        format='json',
    )

    assert response.status_code == status.HTTP_200_OK
    config.refresh_from_db()
    assert config.model_name == 'gpt-4.1-mini'
    assert config.settings == {'temperature': 0.2}
    assert config.api_key == 'sk-updated-generic-key'
    assert config.is_active is False


def test_activation_endpoint_has_specific_throttle_scope() -> None:
    assert WorkspaceAIProviderConfigViewSet.activation_throttle_scope == 'ai_provider_activation'
    assert settings.REST_FRAMEWORK['DEFAULT_THROTTLE_RATES']['ai_provider_activation'] == '5/minute'
