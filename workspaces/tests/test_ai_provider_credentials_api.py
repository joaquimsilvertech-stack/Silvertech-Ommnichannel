from __future__ import annotations

from unittest.mock import patch

import pytest
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


def _replace_url(workspace, config) -> str:
    return f'/api/workspaces/{workspace.id}/ai-providers/{config.id}/credentials/replace/'


def _revoke_url(workspace, config) -> str:
    return f'/api/workspaces/{workspace.id}/ai-providers/{config.id}/credentials/revoke/'


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
def test_unauthenticated_user_cannot_replace_or_revoke_credentials() -> None:
    config = WorkspaceAIProviderConfigFactory(is_active=False)

    replace_response = APIClient().post(
        _replace_url(config.workspace, config),
        {'api_key': 'sk-new-provider-key'},
        format='json',
    )
    revoke_response = APIClient().post(_revoke_url(config.workspace, config), {}, format='json')

    assert replace_response.status_code == status.HTTP_401_UNAUTHORIZED
    assert revoke_response.status_code == status.HTTP_401_UNAUTHORIZED


@pytest.mark.django_db
def test_agent_cannot_replace_or_revoke_credentials() -> None:
    config = WorkspaceAIProviderConfigFactory(is_active=False)
    user = UserFactory()
    MemberFactory(user=user, workspace=config.workspace, role=Member.Role.AGENT)
    client = _client_for(user)

    replace_response = client.post(
        _replace_url(config.workspace, config),
        {'api_key': 'sk-new-provider-key'},
        format='json',
    )
    revoke_response = client.post(_revoke_url(config.workspace, config), {}, format='json')

    assert replace_response.status_code == status.HTTP_403_FORBIDDEN
    assert revoke_response.status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.django_db
@pytest.mark.parametrize('role', [Member.Role.ADMIN, Member.Role.OWNER])
def test_admin_or_owner_can_replace_credentials_after_successful_test(role: str) -> None:
    client, _, workspace = _admin_client(role=role)
    secret = 'sk-new-provider-key'
    config = WorkspaceAIProviderConfigFactory(
        workspace=workspace,
        api_key='sk-old-provider-key',
        is_active=False,
        settings={'temperature': 0.2},
    )

    with patch(
        'workspaces.services.test_ai_provider_connection',
        return_value=_success_result(config),
    ) as mock_test:
        response = client.post(_replace_url(workspace, config), {'api_key': secret}, format='json')

    assert response.status_code == status.HTTP_200_OK
    body = response.json()
    assert body['id'] == str(config.id)
    assert body['has_api_key'] is True
    assert body['is_active'] is False
    assert body['settings'] == {'temperature': 0.2}
    assert 'api_key' not in body
    assert secret not in _response_text(response)
    config.refresh_from_db()
    assert config.api_key == secret
    assert config.is_active is False
    mock_test.assert_called_once_with(provider_config=config, api_key_override=secret)


@pytest.mark.django_db
def test_replace_credentials_failure_keeps_old_key_and_state() -> None:
    client, _, workspace = _admin_client()
    config = WorkspaceAIProviderConfigFactory(
        workspace=workspace,
        api_key='sk-old-provider-key',
        is_active=True,
    )

    with patch(
        'workspaces.services.test_ai_provider_connection',
        return_value=_error_result(config, 'INVALID_CREDENTIALS'),
    ):
        response = client.post(
            _replace_url(workspace, config),
            {'api_key': 'sk-invalid-provider-key'},
            format='json',
        )

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert response.json()['error_code'] == 'INVALID_CREDENTIALS'
    config.refresh_from_db()
    assert config.api_key == 'sk-old-provider-key'
    assert config.is_active is True


@pytest.mark.django_db
@pytest.mark.parametrize(
    ('error_code', 'status_code'),
    [
        ('INVALID_CREDENTIALS', status.HTTP_400_BAD_REQUEST),
        ('RATE_LIMITED', status.HTTP_429_TOO_MANY_REQUESTS),
        ('PROVIDER_TIMEOUT', status.HTTP_504_GATEWAY_TIMEOUT),
        ('PROVIDER_UNAVAILABLE', status.HTTP_503_SERVICE_UNAVAILABLE),
        ('PROVIDER_ERROR', status.HTTP_502_BAD_GATEWAY),
        ('INVALID_REQUEST', status.HTTP_502_BAD_GATEWAY),
    ],
)
def test_replace_credentials_error_codes_map_to_sanitized_http_status(
    error_code: str,
    status_code: int,
) -> None:
    client, _, workspace = _admin_client()
    config = WorkspaceAIProviderConfigFactory(workspace=workspace, is_active=False)

    with patch(
        'workspaces.services.test_ai_provider_connection',
        return_value=_error_result(config, error_code),
    ):
        response = client.post(
            _replace_url(workspace, config),
            {'api_key': 'sk-new-provider-key'},
            format='json',
        )

    assert response.status_code == status_code
    assert response.json()['success'] is False
    assert response.json()['error_code'] in {error_code, 'PROVIDER_ERROR'}
    assert 'Traceback' not in _response_text(response)


@pytest.mark.django_db
def test_replace_credentials_rejects_unsupported_provider_without_external_call() -> None:
    client, _, workspace = _admin_client()
    config = WorkspaceAIProviderConfigFactory(
        workspace=workspace,
        provider=AIProvider.ANTHROPIC,
        api_key='sk-old-provider-key',
        is_active=False,
    )

    with patch('workspaces.services.test_ai_provider_connection') as mock_test:
        response = client.post(
            _replace_url(workspace, config),
            {'api_key': 'sk-new-provider-key'},
            format='json',
        )

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert response.json()['error_code'] == 'UNSUPPORTED_PROVIDER'
    mock_test.assert_not_called()
    config.refresh_from_db()
    assert config.api_key == 'sk-old-provider-key'


@pytest.mark.django_db
@pytest.mark.parametrize(
    ('payload', 'error_code'),
    [
        ({}, 'MISSING_API_KEY'),
        ({'api_key': ''}, 'MISSING_API_KEY'),
        ({'api_key': '   '}, 'MISSING_API_KEY'),
        ({'api_key': 'short'}, 'INVALID_CREDENTIALS'),
        ({'api_key': 'line\nbreak-key'}, 'INVALID_CREDENTIALS'),
    ],
)
def test_replace_credentials_validates_request_body(payload: dict, error_code: str) -> None:
    client, _, workspace = _admin_client()
    config = WorkspaceAIProviderConfigFactory(workspace=workspace, api_key='sk-old-provider-key')

    with patch('workspaces.services.test_ai_provider_connection') as mock_test:
        response = client.post(_replace_url(workspace, config), payload, format='json')

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert response.json()['error_code'] == error_code
    assert 'api_key' not in _response_text(response)
    mock_test.assert_not_called()
    config.refresh_from_db()
    assert config.api_key == 'sk-old-provider-key'


@pytest.mark.django_db
def test_replace_credentials_other_workspace_config_returns_404() -> None:
    client, _, workspace = _admin_client()
    other_config = WorkspaceAIProviderConfigFactory(is_active=False)

    response = client.post(
        _replace_url(workspace, other_config),
        {'api_key': 'sk-new-provider-key'},
        format='json',
    )

    assert response.status_code == status.HTTP_404_NOT_FOUND


@pytest.mark.django_db
def test_revoke_credentials_clears_key_deactivates_and_preserves_config() -> None:
    client, _, workspace = _admin_client()
    config = WorkspaceAIProviderConfigFactory(
        workspace=workspace,
        api_key='sk-provider-key',
        is_active=True,
        model_name='gpt-4o-mini',
        system_prompt='Prompt original.',
        settings={'temperature': 0.2},
    )

    with patch('workspaces.services.test_ai_provider_connection') as mock_test:
        response = client.post(_revoke_url(workspace, config), {}, format='json')

    assert response.status_code == status.HTTP_200_OK
    body = response.json()
    assert body['has_api_key'] is False
    assert body['is_active'] is False
    assert body['model_name'] == 'gpt-4o-mini'
    assert body['system_prompt'] == 'Prompt original.'
    assert body['settings'] == {'temperature': 0.2}
    assert 'api_key' not in body
    mock_test.assert_not_called()
    config.refresh_from_db()
    assert config.api_key == ''
    assert config.is_active is False
    assert config.model_name == 'gpt-4o-mini'


@pytest.mark.django_db
def test_revoke_credentials_is_idempotent() -> None:
    client, _, workspace = _admin_client()
    config = WorkspaceAIProviderConfigFactory(
        workspace=workspace,
        api_key='',
        is_active=False,
    )

    first_response = client.post(_revoke_url(workspace, config), {}, format='json')
    second_response = client.post(_revoke_url(workspace, config), {}, format='json')

    assert first_response.status_code == status.HTTP_200_OK
    assert second_response.status_code == status.HTTP_200_OK
    assert second_response.json()['has_api_key'] is False
    assert second_response.json()['is_active'] is False


@pytest.mark.django_db
def test_credentials_endpoints_do_not_touch_messages_celery_evolution_or_openai() -> None:
    client, _, workspace = _admin_client()
    config = WorkspaceAIProviderConfigFactory(workspace=workspace, is_active=False)
    initial_message_count = Message.objects.count()

    with (
        patch('workspaces.services.test_ai_provider_connection', return_value=_success_result(config)),
        patch('omnichannel.tasks.process_ai_response.delay') as mock_celery,
        patch('omnichannel.services.send_whatsapp_message') as mock_evolution,
        patch('omnichannel.ai.providers.openai.openai.OpenAI') as mock_openai,
    ):
        replace_response = client.post(
            _replace_url(workspace, config),
            {'api_key': 'sk-new-provider-key'},
            format='json',
        )
        revoke_response = client.post(_revoke_url(workspace, config), {}, format='json')

    assert replace_response.status_code == status.HTTP_200_OK
    assert revoke_response.status_code == status.HTTP_200_OK
    assert Message.objects.count() == initial_message_count
    mock_celery.assert_not_called()
    mock_evolution.assert_not_called()
    mock_openai.assert_not_called()
