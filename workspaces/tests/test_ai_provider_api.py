from __future__ import annotations

import logging
from unittest.mock import patch

import pytest
from rest_framework import status
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import AccessToken

from workspaces.factories import (
    MemberFactory,
    UserFactory,
    WorkspaceAIProviderConfigFactory,
    WorkspaceFactory,
)
from workspaces.models import AIProvider, Member, WorkspaceAIProviderConfig


def _client_for(user) -> APIClient:
    client = APIClient()
    token = AccessToken.for_user(user)
    client.credentials(HTTP_AUTHORIZATION=f'Bearer {token}')
    return client


def _list_url(workspace) -> str:
    return f'/api/workspaces/{workspace.id}/ai-providers/'


def _detail_url(workspace, config) -> str:
    return f'/api/workspaces/{workspace.id}/ai-providers/{config.id}/'


def _old_duplicate_list_url(workspace) -> str:
    return f'/api/workspaces/workspaces/{workspace.id}/ai-providers/'


def _payload(**overrides):
    data = {
        'provider': AIProvider.OPENAI,
        'model_name': 'gpt-4o-mini',
        'system_prompt': 'Seja conciso.',
        'settings': {},
        'is_active': False,
        'api_key': 'sk-valid-api-key',
    }
    data.update(overrides)
    return data


def _admin_client(workspace=None):
    user = UserFactory()
    workspace = workspace or WorkspaceFactory()
    MemberFactory(user=user, workspace=workspace, role=Member.Role.ADMIN)
    return _client_for(user), user, workspace


def _response_text(response) -> str:
    return response.content.decode('utf-8')


@pytest.mark.django_db
def test_unauthenticated_user_cannot_list_configs() -> None:
    workspace = WorkspaceFactory()

    response = APIClient().get(_list_url(workspace))

    assert response.status_code == status.HTTP_401_UNAUTHORIZED


@pytest.mark.django_db
def test_non_member_cannot_list_workspace_configs() -> None:
    client = _client_for(UserFactory())
    workspace = WorkspaceFactory()

    response = client.get(_list_url(workspace))

    assert response.status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.django_db
def test_agent_member_cannot_list_or_write_configs() -> None:
    user = UserFactory()
    workspace = WorkspaceFactory()
    MemberFactory(user=user, workspace=workspace, role=Member.Role.AGENT)
    client = _client_for(user)

    list_response = client.get(_list_url(workspace))
    create_response = client.post(_list_url(workspace), _payload(), format='json')

    assert list_response.status_code == status.HTTP_403_FORBIDDEN
    assert create_response.status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.django_db
def test_admin_can_list_configs() -> None:
    client, _, workspace = _admin_client()
    config = WorkspaceAIProviderConfigFactory(workspace=workspace, is_active=False)

    response = client.get(_list_url(workspace))

    assert response.status_code == status.HTTP_200_OK
    assert response.json()[0]['id'] == str(config.id)


@pytest.mark.django_db
def test_old_duplicate_list_route_no_longer_exists() -> None:
    client, _, workspace = _admin_client()

    response = client.get(_old_duplicate_list_url(workspace))

    assert response.status_code == status.HTTP_404_NOT_FOUND


@pytest.mark.django_db
def test_list_returns_only_configs_from_url_workspace() -> None:
    client, user, first_workspace = _admin_client()
    second_workspace = WorkspaceFactory()
    MemberFactory(user=user, workspace=second_workspace, role=Member.Role.ADMIN)
    visible = WorkspaceAIProviderConfigFactory(workspace=first_workspace, is_active=False)
    hidden = WorkspaceAIProviderConfigFactory(workspace=second_workspace, is_active=False)

    response = client.get(_list_url(first_workspace))

    assert response.status_code == status.HTTP_200_OK
    ids = {item['id'] for item in response.json()}
    assert ids == {str(visible.id)}
    assert str(hidden.id) not in ids


@pytest.mark.django_db
def test_list_never_returns_api_key() -> None:
    client, _, workspace = _admin_client()
    secret = 'sk-list-secret-key'
    WorkspaceAIProviderConfigFactory(workspace=workspace, api_key=secret, is_active=False)

    response = client.get(_list_url(workspace))

    assert response.status_code == status.HTTP_200_OK
    assert 'api_key' not in response.json()[0]
    assert secret not in _response_text(response)


@pytest.mark.django_db
def test_retrieve_returns_workspace_config() -> None:
    client, _, workspace = _admin_client()
    config = WorkspaceAIProviderConfigFactory(workspace=workspace, is_active=False)

    response = client.get(_detail_url(workspace, config))

    assert response.status_code == status.HTTP_200_OK
    assert response.json()['id'] == str(config.id)


@pytest.mark.django_db
def test_retrieve_other_workspace_config_fails() -> None:
    client, _, workspace = _admin_client()
    other_config = WorkspaceAIProviderConfigFactory(is_active=False)

    response = client.get(_detail_url(workspace, other_config))

    assert response.status_code == status.HTTP_404_NOT_FOUND


@pytest.mark.django_db
def test_retrieve_never_returns_api_key() -> None:
    client, _, workspace = _admin_client()
    secret = 'sk-retrieve-secret-key'
    config = WorkspaceAIProviderConfigFactory(workspace=workspace, api_key=secret, is_active=False)

    response = client.get(_detail_url(workspace, config))

    assert response.status_code == status.HTTP_200_OK
    assert 'api_key' not in response.json()
    assert secret not in _response_text(response)


@pytest.mark.django_db
def test_create_valid_openai_config() -> None:
    client, _, workspace = _admin_client()

    response = client.post(_list_url(workspace), _payload(), format='json')

    assert response.status_code == status.HTTP_201_CREATED
    config = WorkspaceAIProviderConfig.objects.get(workspace=workspace, provider=AIProvider.OPENAI)
    assert config.model_name == 'gpt-4o-mini'
    assert config.api_key == 'sk-valid-api-key'


@pytest.mark.django_db
def test_create_uses_workspace_from_url_not_payload() -> None:
    client, _, workspace = _admin_client()
    other_workspace = WorkspaceFactory()

    response = client.post(
        _list_url(workspace),
        _payload(workspace_id=str(other_workspace.id)),
        format='json',
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert not WorkspaceAIProviderConfig.objects.filter(workspace=other_workspace).exists()


@pytest.mark.django_db
@pytest.mark.parametrize('workspace_key', ['workspace', 'workspace_id'])
def test_create_with_workspace_in_payload_fails(workspace_key: str) -> None:
    client, _, workspace = _admin_client()

    response = client.post(
        _list_url(workspace),
        _payload(**{workspace_key: str(WorkspaceFactory().id)}),
        format='json',
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST


@pytest.mark.django_db
def test_create_without_api_key_fails() -> None:
    client, _, workspace = _admin_client()
    data = _payload()
    data.pop('api_key')

    response = client.post(_list_url(workspace), data, format='json')

    assert response.status_code == status.HTTP_400_BAD_REQUEST


@pytest.mark.django_db
def test_create_response_has_no_api_key_and_has_boolean_has_api_key() -> None:
    client, _, workspace = _admin_client()
    secret = 'sk-create-secret-key'

    response = client.post(_list_url(workspace), _payload(api_key=secret), format='json')

    assert response.status_code == status.HTTP_201_CREATED
    body = response.json()
    assert 'api_key' not in body
    assert body['has_api_key'] is True
    assert isinstance(body['has_api_key'], bool)
    assert secret not in _response_text(response)


@pytest.mark.django_db
@pytest.mark.parametrize('provider', [AIProvider.ANTHROPIC, AIProvider.GOOGLE])
def test_create_unsupported_provider_fails(provider: str) -> None:
    client, _, workspace = _admin_client()

    response = client.post(_list_url(workspace), _payload(provider=provider), format='json')

    assert response.status_code == status.HTTP_400_BAD_REQUEST


@pytest.mark.django_db
def test_create_duplicate_provider_in_same_workspace_fails() -> None:
    client, _, workspace = _admin_client()
    WorkspaceAIProviderConfigFactory(workspace=workspace, provider=AIProvider.OPENAI, is_active=False)

    response = client.post(_list_url(workspace), _payload(provider=AIProvider.OPENAI), format='json')

    assert response.status_code == status.HTTP_400_BAD_REQUEST


@pytest.mark.django_db
def test_same_provider_in_other_workspace_is_allowed() -> None:
    WorkspaceAIProviderConfigFactory(provider=AIProvider.OPENAI, is_active=False)
    client, _, workspace = _admin_client()

    response = client.post(_list_url(workspace), _payload(provider=AIProvider.OPENAI), format='json')

    assert response.status_code == status.HTTP_201_CREATED


@pytest.mark.django_db
def test_patch_without_api_key_preserves_existing_key() -> None:
    client, _, workspace = _admin_client()
    config = WorkspaceAIProviderConfigFactory(
        workspace=workspace,
        api_key='sk-original-api-key',
        is_active=False,
    )

    response = client.patch(
        _detail_url(workspace, config),
        {'model_name': 'gpt-4.1-mini'},
        format='json',
    )

    assert response.status_code == status.HTTP_200_OK
    config.refresh_from_db()
    assert config.api_key == 'sk-original-api-key'
    assert config.model_name == 'gpt-4.1-mini'


@pytest.mark.django_db
def test_patch_with_new_api_key_replaces_existing_key() -> None:
    client, _, workspace = _admin_client()
    config = WorkspaceAIProviderConfigFactory(
        workspace=workspace,
        api_key='sk-original-api-key',
        is_active=False,
    )

    response = client.patch(
        _detail_url(workspace, config),
        {'api_key': 'sk-new-api-key'},
        format='json',
    )

    assert response.status_code == status.HTTP_200_OK
    config.refresh_from_db()
    assert config.api_key == 'sk-new-api-key'


@pytest.mark.django_db
def test_patch_never_returns_api_key() -> None:
    client, _, workspace = _admin_client()
    secret = 'sk-patch-secret-key'
    config = WorkspaceAIProviderConfigFactory(workspace=workspace, api_key='sk-original-key', is_active=False)

    response = client.patch(
        _detail_url(workspace, config),
        {'api_key': secret},
        format='json',
    )

    assert response.status_code == status.HTTP_200_OK
    assert 'api_key' not in response.json()
    assert secret not in _response_text(response)


@pytest.mark.django_db
def test_patch_trying_to_change_provider_fails() -> None:
    client, _, workspace = _admin_client()
    config = WorkspaceAIProviderConfigFactory(workspace=workspace, provider=AIProvider.OPENAI, is_active=False)

    response = client.patch(
        _detail_url(workspace, config),
        {'provider': AIProvider.ANTHROPIC},
        format='json',
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST


@pytest.mark.django_db
def test_patch_activating_second_active_provider_fails() -> None:
    client, _, workspace = _admin_client()
    WorkspaceAIProviderConfigFactory(workspace=workspace, provider=AIProvider.ANTHROPIC, is_active=True)
    config = WorkspaceAIProviderConfigFactory(workspace=workspace, provider=AIProvider.OPENAI, is_active=False)

    response = client.patch(
        _detail_url(workspace, config),
        {'is_active': True},
        format='json',
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST


@pytest.mark.django_db
def test_patch_deactivating_active_provider_works() -> None:
    client, _, workspace = _admin_client()
    config = WorkspaceAIProviderConfigFactory(workspace=workspace, is_active=True)

    response = client.patch(
        _detail_url(workspace, config),
        {'is_active': False},
        format='json',
    )

    assert response.status_code == status.HTTP_200_OK
    config.refresh_from_db()
    assert config.is_active is False


@pytest.mark.django_db
def test_patch_valid_settings_works() -> None:
    client, _, workspace = _admin_client()
    config = WorkspaceAIProviderConfigFactory(workspace=workspace, is_active=False)

    response = client.patch(
        _detail_url(workspace, config),
        {'settings': {'temperature': 0.2, 'max_tokens': 120}},
        format='json',
    )

    assert response.status_code == status.HTTP_200_OK
    config.refresh_from_db()
    assert config.settings == {'temperature': 0.2, 'max_tokens': 120}


@pytest.mark.django_db
def test_patch_settings_with_secret_fails_without_leaking_value(caplog) -> None:
    client, _, workspace = _admin_client()
    config = WorkspaceAIProviderConfigFactory(workspace=workspace, is_active=False)
    secret = 'Bearer hidden-token'
    caplog.set_level(logging.INFO)

    response = client.patch(
        _detail_url(workspace, config),
        {'settings': {'headers': {'Authorization': secret}}},
        format='json',
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert secret not in _response_text(response)
    assert secret not in caplog.text


@pytest.mark.django_db
def test_patch_conflicting_token_limits_fails() -> None:
    client, _, workspace = _admin_client()
    config = WorkspaceAIProviderConfigFactory(workspace=workspace, is_active=False)

    response = client.patch(
        _detail_url(workspace, config),
        {'settings': {'max_tokens': 100, 'max_completion_tokens': 100}},
        format='json',
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert '100' not in _response_text(response)


@pytest.mark.django_db
def test_delete_is_not_allowed() -> None:
    client, _, workspace = _admin_client()
    config = WorkspaceAIProviderConfigFactory(workspace=workspace, is_active=False)

    response = client.delete(_detail_url(workspace, config))

    assert response.status_code == status.HTTP_405_METHOD_NOT_ALLOWED


@pytest.mark.django_db
def test_errors_do_not_expose_api_key_or_logs(caplog) -> None:
    client, _, workspace = _admin_client()
    secret = 'sk-error-secret-key'
    caplog.set_level(logging.INFO)

    response = client.post(
        _list_url(workspace),
        _payload(api_key=secret, settings={'headers': {'Authorization': 'Bearer forbidden'}}),
        format='json',
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert secret not in _response_text(response)
    assert secret not in caplog.text
    assert 'Bearer forbidden' not in _response_text(response)
    assert 'Bearer forbidden' not in caplog.text


@pytest.mark.django_db
def test_admin_of_workspace_a_cannot_access_workspace_b_configs() -> None:
    client, _, first_workspace = _admin_client()
    second_workspace = WorkspaceFactory()
    WorkspaceAIProviderConfigFactory(workspace=first_workspace, is_active=False)
    hidden = WorkspaceAIProviderConfigFactory(workspace=second_workspace, is_active=False)

    list_response = client.get(_list_url(second_workspace))
    detail_response = client.get(_detail_url(first_workspace, hidden))

    assert list_response.status_code == status.HTTP_403_FORBIDDEN
    assert detail_response.status_code == status.HTTP_404_NOT_FOUND


@pytest.mark.django_db
def test_admin_of_workspace_b_cannot_update_workspace_a_config() -> None:
    first_workspace = WorkspaceFactory()
    first_config = WorkspaceAIProviderConfigFactory(workspace=first_workspace, is_active=False)
    client, _, second_workspace = _admin_client()

    response = client.patch(
        _detail_url(second_workspace, first_config),
        {'model_name': 'gpt-4o'},
        format='json',
    )

    assert response.status_code == status.HTTP_404_NOT_FOUND


@pytest.mark.django_db
def test_same_user_member_of_two_workspaces_only_sees_url_workspace_configs() -> None:
    user = UserFactory()
    first_workspace = WorkspaceFactory()
    second_workspace = WorkspaceFactory()
    MemberFactory(user=user, workspace=first_workspace, role=Member.Role.ADMIN)
    MemberFactory(user=user, workspace=second_workspace, role=Member.Role.ADMIN)
    first_config = WorkspaceAIProviderConfigFactory(workspace=first_workspace, is_active=False)
    second_config = WorkspaceAIProviderConfigFactory(workspace=second_workspace, is_active=False)
    client = _client_for(user)

    response = client.get(_list_url(second_workspace))

    assert response.status_code == status.HTTP_200_OK
    ids = {item['id'] for item in response.json()}
    assert ids == {str(second_config.id)}
    assert str(first_config.id) not in ids


@pytest.mark.django_db
def test_active_provider_in_other_workspace_does_not_block_activation() -> None:
    WorkspaceAIProviderConfigFactory(is_active=True)
    client, _, workspace = _admin_client()
    config = WorkspaceAIProviderConfigFactory(workspace=workspace, is_active=False)

    response = client.patch(
        _detail_url(workspace, config),
        {'is_active': True},
        format='json',
    )

    assert response.status_code == status.HTTP_200_OK


@pytest.mark.django_db
def test_duplicate_provider_in_other_workspace_does_not_block_create() -> None:
    WorkspaceAIProviderConfigFactory(provider=AIProvider.OPENAI, is_active=False)
    client, _, workspace = _admin_client()

    response = client.post(_list_url(workspace), _payload(provider=AIProvider.OPENAI), format='json')

    assert response.status_code == status.HTTP_201_CREATED


@pytest.mark.django_db
def test_api_does_not_call_openai_when_saving_config() -> None:
    client, _, workspace = _admin_client()

    with patch('omnichannel.ai.providers.openai.openai.OpenAI') as mock_openai:
        response = client.post(_list_url(workspace), _payload(), format='json')

    assert response.status_code == status.HTTP_201_CREATED
    mock_openai.assert_not_called()
