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
from workspaces.models import AIProvider, Member
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


def _test_url(workspace, config) -> str:
    return f'/api/workspaces/{workspace.id}/ai-providers/{config.id}/test/'


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
def test_unauthenticated_user_cannot_test_connection() -> None:
    config = WorkspaceAIProviderConfigFactory(is_active=False)

    response = APIClient().post(_test_url(config.workspace, config), {}, format='json')

    assert response.status_code == status.HTTP_401_UNAUTHORIZED


@pytest.mark.django_db
def test_non_member_cannot_test_connection() -> None:
    config = WorkspaceAIProviderConfigFactory(is_active=False)
    client = _client_for(UserFactory())

    response = client.post(_test_url(config.workspace, config), {}, format='json')

    assert response.status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.django_db
def test_agent_cannot_test_connection() -> None:
    config = WorkspaceAIProviderConfigFactory(is_active=False)
    user = UserFactory()
    MemberFactory(user=user, workspace=config.workspace, role=Member.Role.AGENT)
    client = _client_for(user)

    response = client.post(_test_url(config.workspace, config), {}, format='json')

    assert response.status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.django_db
def test_admin_tests_connection_with_saved_api_key() -> None:
    client, _, workspace = _admin_client()
    config = WorkspaceAIProviderConfigFactory(workspace=workspace, is_active=False)

    with patch('workspaces.views.test_ai_provider_connection', return_value=_success_result(config)) as mock_service:
        response = client.post(_test_url(workspace, config), {}, format='json')

    assert response.status_code == status.HTTP_200_OK
    assert response.json() == {
        'success': True,
        'provider': AIProvider.OPENAI,
        'model_name': config.model_name,
        'message': 'Credencial validada com sucesso.',
    }
    mock_service.assert_called_once()
    assert mock_service.call_args.kwargs['provider_config'] == config
    assert mock_service.call_args.kwargs['api_key_override'] is None


@pytest.mark.django_db
def test_owner_tests_connection_with_saved_api_key() -> None:
    client, _, workspace = _admin_client(role=Member.Role.OWNER)
    config = WorkspaceAIProviderConfigFactory(workspace=workspace, is_active=False)

    with patch('workspaces.views.test_ai_provider_connection', return_value=_success_result(config)):
        response = client.post(_test_url(workspace, config), {}, format='json')

    assert response.status_code == status.HTTP_200_OK


@pytest.mark.django_db
def test_inactive_config_can_be_tested() -> None:
    client, _, workspace = _admin_client()
    config = WorkspaceAIProviderConfigFactory(workspace=workspace, is_active=False)

    with patch('workspaces.views.test_ai_provider_connection', return_value=_success_result(config)):
        response = client.post(_test_url(workspace, config), {}, format='json')

    assert response.status_code == status.HTTP_200_OK


@pytest.mark.django_db
def test_other_workspace_config_cannot_be_tested() -> None:
    client, _, workspace = _admin_client()
    other_config = WorkspaceAIProviderConfigFactory(is_active=False)

    response = client.post(_test_url(workspace, other_config), {}, format='json')

    assert response.status_code == status.HTTP_404_NOT_FOUND


@pytest.mark.django_db
def test_temporary_api_key_is_used_but_not_saved() -> None:
    client, _, workspace = _admin_client()
    config = WorkspaceAIProviderConfigFactory(
        workspace=workspace,
        api_key='sk-saved-connection-key',
        is_active=False,
    )

    with patch('workspaces.views.test_ai_provider_connection', return_value=_success_result(config)) as mock_service:
        response = client.post(
            _test_url(workspace, config),
            {'api_key': 'sk-temporary-connection-key'},
            format='json',
        )

    assert response.status_code == status.HTTP_200_OK
    config.refresh_from_db()
    assert config.api_key == 'sk-saved-connection-key'
    assert mock_service.call_args.kwargs['api_key_override'] == 'sk-temporary-connection-key'


@pytest.mark.django_db
def test_without_api_key_uses_saved_key() -> None:
    client, _, workspace = _admin_client()
    config = WorkspaceAIProviderConfigFactory(workspace=workspace, is_active=False)

    with patch('workspaces.views.test_ai_provider_connection', return_value=_success_result(config)) as mock_service:
        response = client.post(_test_url(workspace, config), {}, format='json')

    assert response.status_code == status.HTTP_200_OK
    assert mock_service.call_args.kwargs['api_key_override'] is None


@pytest.mark.django_db
@pytest.mark.parametrize('api_key', ['', 'line\nbreak-key', ' sk-with-space', 'sk-with-space '])
def test_invalid_temporary_api_key_fails(api_key: str) -> None:
    client, _, workspace = _admin_client()
    config = WorkspaceAIProviderConfigFactory(workspace=workspace, is_active=False)

    response = client.post(_test_url(workspace, config), {'api_key': api_key}, format='json')

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert 'api_key' not in _response_text(response)


@pytest.mark.django_db
def test_success_response_does_not_contain_api_key() -> None:
    client, _, workspace = _admin_client()
    config = WorkspaceAIProviderConfigFactory(workspace=workspace, is_active=False)
    secret = 'sk-temporary-success-key'

    with patch('workspaces.views.test_ai_provider_connection', return_value=_success_result(config)):
        response = client.post(_test_url(workspace, config), {'api_key': secret}, format='json')

    assert response.status_code == status.HTTP_200_OK
    assert secret not in _response_text(response)
    assert 'api_key' not in response.json()


@pytest.mark.django_db
def test_error_response_and_logs_do_not_contain_api_key(caplog) -> None:
    client, _, workspace = _admin_client()
    config = WorkspaceAIProviderConfigFactory(workspace=workspace, is_active=False)
    secret = 'sk-temporary-error-key'
    caplog.set_level(logging.WARNING)

    with patch(
        'workspaces.views.test_ai_provider_connection',
        return_value=_error_result(config, 'INVALID_CREDENTIALS'),
    ):
        response = client.post(_test_url(workspace, config), {'api_key': secret}, format='json')

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert secret not in _response_text(response)
    assert secret not in caplog.text
    assert response.json()['error_code'] == 'INVALID_CREDENTIALS'


@pytest.mark.django_db
@pytest.mark.parametrize(
    ('error_code', 'status_code'),
    [
        ('UNSUPPORTED_PROVIDER', status.HTTP_400_BAD_REQUEST),
        ('INVALID_CREDENTIALS', status.HTTP_400_BAD_REQUEST),
        ('RATE_LIMITED', status.HTTP_429_TOO_MANY_REQUESTS),
        ('PROVIDER_TIMEOUT', status.HTTP_504_GATEWAY_TIMEOUT),
        ('PROVIDER_UNAVAILABLE', status.HTTP_503_SERVICE_UNAVAILABLE),
        ('INVALID_REQUEST', status.HTTP_400_BAD_REQUEST),
        ('PROVIDER_ERROR', status.HTTP_502_BAD_GATEWAY),
    ],
)
def test_error_codes_map_to_sanitized_http_status(error_code: str, status_code: int) -> None:
    client, _, workspace = _admin_client()
    config = WorkspaceAIProviderConfigFactory(workspace=workspace, is_active=False)

    with patch('workspaces.views.test_ai_provider_connection', return_value=_error_result(config, error_code)):
        response = client.post(_test_url(workspace, config), {}, format='json')

    assert response.status_code == status_code
    body = response.json()
    assert body['success'] is False
    assert body['error_code'] == error_code
    assert 'Traceback' not in _response_text(response)


@pytest.mark.django_db
def test_get_on_connection_test_endpoint_returns_405() -> None:
    client, _, workspace = _admin_client()
    config = WorkspaceAIProviderConfigFactory(workspace=workspace, is_active=False)

    response = client.get(_test_url(workspace, config))

    assert response.status_code == status.HTTP_405_METHOD_NOT_ALLOWED


@pytest.mark.django_db
def test_delete_on_connection_test_endpoint_returns_405() -> None:
    client, _, workspace = _admin_client()
    config = WorkspaceAIProviderConfigFactory(workspace=workspace, is_active=False)

    response = client.delete(_test_url(workspace, config))

    assert response.status_code == status.HTTP_405_METHOD_NOT_ALLOWED


@pytest.mark.django_db
def test_connection_test_does_not_mutate_runtime_or_call_external_services() -> None:
    client, _, workspace = _admin_client()
    config = WorkspaceAIProviderConfigFactory(workspace=workspace, is_active=False)
    initial_message_count = Message.objects.count()

    with (
        patch('workspaces.views.test_ai_provider_connection', return_value=_success_result(config)),
        patch('omnichannel.tasks.process_ai_response.delay') as mock_celery,
        patch('omnichannel.services.send_whatsapp_message') as mock_evolution,
        patch('omnichannel.ai.providers.openai.openai.OpenAI') as mock_openai,
    ):
        response = client.post(_test_url(workspace, config), {}, format='json')

    assert response.status_code == status.HTTP_200_OK
    config.refresh_from_db()
    assert config.is_active is False
    assert Message.objects.count() == initial_message_count
    mock_celery.assert_not_called()
    mock_evolution.assert_not_called()
    mock_openai.assert_not_called()


def test_connection_test_endpoint_has_specific_throttle_scope() -> None:
    assert (
        WorkspaceAIProviderConfigViewSet.test_connection_throttle_scope
        == 'ai_provider_test_connection'
    )
    assert (
        settings.REST_FRAMEWORK['DEFAULT_THROTTLE_RATES']['ai_provider_test_connection']
        == '5/minute'
    )
