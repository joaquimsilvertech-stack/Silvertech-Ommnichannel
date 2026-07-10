from __future__ import annotations

import logging
from unittest.mock import patch

import pytest

from workspaces.factories import WorkspaceAIProviderConfigFactory, WorkspaceFactory
from workspaces.models import AIProvider, WorkspaceAIProviderConfig
from workspaces.serializers import WorkspaceAIProviderConfigSerializer


def _payload(**overrides):
    data = {
        'provider': AIProvider.OPENAI,
        'model_name': 'gpt-4o-mini',
        'system_prompt': 'Seja conciso.',
        'settings': {},
        'api_key': 'sk-valid-test-key',
    }
    data.update(overrides)
    return data


@pytest.mark.django_db
def test_serializer_does_not_return_api_key() -> None:
    config = WorkspaceAIProviderConfigFactory(api_key='sk-secret-value')

    data = WorkspaceAIProviderConfigSerializer(config).data

    assert 'api_key' not in data
    assert 'sk-secret-value' not in str(data)


@pytest.mark.django_db
def test_serializer_returns_has_api_key_true_when_key_exists() -> None:
    config = WorkspaceAIProviderConfigFactory(api_key='sk-secret-value')

    data = WorkspaceAIProviderConfigSerializer(config).data

    assert data['has_api_key'] is True


@pytest.mark.django_db
def test_serializer_returns_has_api_key_false_without_key() -> None:
    config = WorkspaceAIProviderConfigFactory(api_key='')

    data = WorkspaceAIProviderConfigSerializer(config).data

    assert data['has_api_key'] is False


@pytest.mark.django_db
def test_serializer_returns_is_supported_true_for_openai() -> None:
    config = WorkspaceAIProviderConfigFactory(provider=AIProvider.OPENAI)

    data = WorkspaceAIProviderConfigSerializer(config).data

    assert data['is_supported'] is True


@pytest.mark.django_db
@pytest.mark.parametrize('provider', [AIProvider.ANTHROPIC, AIProvider.GOOGLE])
def test_serializer_returns_is_supported_false_for_unregistered_providers(provider: str) -> None:
    config = WorkspaceAIProviderConfigFactory(provider=provider, is_active=False)

    data = WorkspaceAIProviderConfigSerializer(config).data

    assert data['is_supported'] is False


@pytest.mark.django_db
def test_create_uses_workspace_from_context() -> None:
    workspace = WorkspaceFactory()
    payload_workspace = WorkspaceFactory()
    serializer = WorkspaceAIProviderConfigSerializer(
        data=_payload(),
        context={'workspace': workspace},
    )

    assert serializer.is_valid(), serializer.errors
    config = serializer.save()

    assert config.workspace == workspace
    assert config.workspace != payload_workspace


@pytest.mark.django_db
@pytest.mark.parametrize('workspace_key', ['workspace', 'workspace_id'])
def test_payload_with_workspace_is_rejected(workspace_key: str) -> None:
    workspace = WorkspaceFactory()
    serializer = WorkspaceAIProviderConfigSerializer(
        data=_payload(**{workspace_key: str(WorkspaceFactory().id)}),
        context={'workspace': workspace},
    )

    assert not serializer.is_valid()
    assert 'api_key' not in str(serializer.errors)
    assert 'sk-valid-test-key' not in str(serializer.errors)


@pytest.mark.django_db
def test_create_without_workspace_context_fails() -> None:
    serializer = WorkspaceAIProviderConfigSerializer(data=_payload())

    assert not serializer.is_valid()
    assert 'Workspace context is required.' in str(serializer.errors)


@pytest.mark.django_db
def test_create_without_api_key_fails() -> None:
    serializer = WorkspaceAIProviderConfigSerializer(
        data=_payload(api_key=''),
        context={'workspace': WorkspaceFactory()},
    )

    assert not serializer.is_valid()
    assert 'sk-valid-test-key' not in str(serializer.errors)


@pytest.mark.django_db
def test_create_with_valid_api_key_creates_config() -> None:
    workspace = WorkspaceFactory()
    serializer = WorkspaceAIProviderConfigSerializer(
        data=_payload(api_key='sk-valid-create-key'),
        context={'workspace': workspace},
    )

    assert serializer.is_valid(), serializer.errors
    config = serializer.save()

    assert config.workspace == workspace
    assert config.api_key == 'sk-valid-create-key'


@pytest.mark.django_db
def test_api_key_is_not_returned_after_create() -> None:
    serializer = WorkspaceAIProviderConfigSerializer(
        data=_payload(api_key='sk-valid-create-key'),
        context={'workspace': WorkspaceFactory()},
    )

    assert serializer.is_valid(), serializer.errors
    config = serializer.save()

    data = WorkspaceAIProviderConfigSerializer(config).data
    assert 'api_key' not in data
    assert 'sk-valid-create-key' not in str(data)


@pytest.mark.django_db
def test_update_without_api_key_preserves_existing_key() -> None:
    config = WorkspaceAIProviderConfigFactory(api_key='sk-original-key', is_active=False)
    serializer = WorkspaceAIProviderConfigSerializer(
        config,
        data={'model_name': 'gpt-4.1-mini'},
        context={'workspace': config.workspace},
        partial=True,
    )

    assert serializer.is_valid(), serializer.errors
    serializer.save()
    config.refresh_from_db()

    assert config.api_key == 'sk-original-key'
    assert config.model_name == 'gpt-4.1-mini'


@pytest.mark.django_db
def test_update_with_new_api_key_replaces_existing_key() -> None:
    config = WorkspaceAIProviderConfigFactory(api_key='sk-original-key', is_active=False)
    serializer = WorkspaceAIProviderConfigSerializer(
        config,
        data={'api_key': 'sk-replacement-key'},
        context={'workspace': config.workspace},
        partial=True,
    )

    assert serializer.is_valid(), serializer.errors
    serializer.save()
    config.refresh_from_db()

    assert config.api_key == 'sk-replacement-key'


@pytest.mark.django_db
@pytest.mark.parametrize('api_key', ['', '   ', ' short ', 'line\nbreak'])
def test_update_with_invalid_api_key_fails(api_key: str) -> None:
    config = WorkspaceAIProviderConfigFactory(api_key='sk-original-key', is_active=False)
    serializer = WorkspaceAIProviderConfigSerializer(
        config,
        data={'api_key': api_key},
        context={'workspace': config.workspace},
        partial=True,
    )

    assert not serializer.is_valid()
    assert 'api_key' not in str(serializer.errors)
    assert 'sk-original-key' not in str(serializer.errors)


@pytest.mark.django_db
def test_provider_is_immutable_on_update() -> None:
    config = WorkspaceAIProviderConfigFactory(provider=AIProvider.OPENAI, is_active=False)
    serializer = WorkspaceAIProviderConfigSerializer(
        config,
        data={'provider': AIProvider.ANTHROPIC},
        context={'workspace': config.workspace},
        partial=True,
    )

    assert not serializer.is_valid()


@pytest.mark.django_db
@pytest.mark.parametrize('provider', [AIProvider.ANTHROPIC, AIProvider.GOOGLE])
def test_unsupported_provider_cannot_be_created(provider: str) -> None:
    serializer = WorkspaceAIProviderConfigSerializer(
        data=_payload(provider=provider),
        context={'workspace': WorkspaceFactory()},
    )

    assert not serializer.is_valid()


@pytest.mark.django_db
def test_is_active_cannot_be_changed_by_serializer_update() -> None:
    config = WorkspaceAIProviderConfigFactory(provider=AIProvider.ANTHROPIC, is_active=False)
    serializer = WorkspaceAIProviderConfigSerializer(
        config,
        data={'is_active': True},
        context={'workspace': config.workspace},
        partial=True,
    )

    assert not serializer.is_valid()
    assert 'ativacao/desativacao' in str(serializer.errors)


@pytest.mark.django_db
def test_is_active_cannot_be_set_by_serializer_create() -> None:
    workspace = WorkspaceFactory()
    serializer = WorkspaceAIProviderConfigSerializer(
        data=_payload(provider=AIProvider.ANTHROPIC, is_active=True),
        context={'workspace': workspace},
    )

    with patch('workspaces.serializers.is_provider_supported', return_value=True):
        assert not serializer.is_valid()

    assert 'ativacao/desativacao' in str(serializer.errors)


@pytest.mark.django_db
def test_active_provider_in_other_workspace_does_not_block_create() -> None:
    WorkspaceAIProviderConfigFactory(is_active=True)
    serializer = WorkspaceAIProviderConfigSerializer(
        data=_payload(),
        context={'workspace': WorkspaceFactory()},
    )

    assert serializer.is_valid(), serializer.errors


@pytest.mark.django_db
def test_duplicate_provider_in_same_workspace_is_rejected() -> None:
    workspace = WorkspaceFactory()
    WorkspaceAIProviderConfigFactory(workspace=workspace, provider=AIProvider.OPENAI, is_active=False)
    serializer = WorkspaceAIProviderConfigSerializer(
        data=_payload(provider=AIProvider.OPENAI),
        context={'workspace': workspace},
    )

    assert not serializer.is_valid()


@pytest.mark.django_db
def test_same_provider_in_different_workspace_is_allowed() -> None:
    WorkspaceAIProviderConfigFactory(provider=AIProvider.OPENAI, is_active=False)
    serializer = WorkspaceAIProviderConfigSerializer(
        data=_payload(provider=AIProvider.OPENAI),
        context={'workspace': WorkspaceFactory()},
    )

    assert serializer.is_valid(), serializer.errors


@pytest.mark.django_db
@pytest.mark.parametrize('model_name', ['', '   ', 'gpt\n4o', ' gpt-4o', 'gpt-4o '])
def test_invalid_model_name_fails(model_name: str) -> None:
    serializer = WorkspaceAIProviderConfigSerializer(
        data=_payload(model_name=model_name),
        context={'workspace': WorkspaceFactory()},
    )

    assert not serializer.is_valid()


@pytest.mark.django_db
def test_omitted_settings_defaults_to_empty_dict() -> None:
    data = _payload()
    data.pop('settings')
    serializer = WorkspaceAIProviderConfigSerializer(
        data=data,
        context={'workspace': WorkspaceFactory()},
    )

    assert serializer.is_valid(), serializer.errors
    config = serializer.save()

    assert config.settings == {}


@pytest.mark.django_db
def test_null_settings_defaults_to_empty_dict() -> None:
    serializer = WorkspaceAIProviderConfigSerializer(
        data=_payload(settings=None),
        context={'workspace': WorkspaceFactory()},
    )

    assert serializer.is_valid(), serializer.errors
    config = serializer.save()

    assert config.settings == {}


@pytest.mark.django_db
@pytest.mark.parametrize('setting_payload', [['x'], 'x', 1, True])
def test_non_dict_settings_fail(setting_payload) -> None:
    serializer = WorkspaceAIProviderConfigSerializer(
        data=_payload(settings=setting_payload),
        context={'workspace': WorkspaceFactory()},
    )

    assert not serializer.is_valid()
    assert 'sk-valid-test-key' not in str(serializer.errors)


@pytest.mark.django_db
@pytest.mark.parametrize(
    'setting_payload',
    [
        {'api_key': 'sk-secret-in-settings'},
        {'Authorization': 'Bearer secret-token'},
        {'metadata': {'secret': 'nested-secret'}},
    ],
)
def test_sensitive_settings_fail_without_exposing_values(setting_payload) -> None:
    serializer = WorkspaceAIProviderConfigSerializer(
        data=_payload(settings=setting_payload),
        context={'workspace': WorkspaceFactory()},
    )

    assert not serializer.is_valid()
    rendered_errors = str(serializer.errors)
    assert 'sk-secret-in-settings' not in rendered_errors
    assert 'Bearer secret-token' not in rendered_errors
    assert 'nested-secret' not in rendered_errors


@pytest.mark.django_db
def test_valid_openai_settings_pass() -> None:
    serializer = WorkspaceAIProviderConfigSerializer(
        data=_payload(settings={'temperature': 0.2, 'top_p': 0.8, 'max_tokens': 128}),
        context={'workspace': WorkspaceFactory()},
    )

    assert serializer.is_valid(), serializer.errors


@pytest.mark.django_db
def test_unknown_openai_settings_fail() -> None:
    serializer = WorkspaceAIProviderConfigSerializer(
        data=_payload(settings={'unknown': 'value'}),
        context={'workspace': WorkspaceFactory()},
    )

    assert not serializer.is_valid()
    assert 'value' not in str(serializer.errors)


@pytest.mark.django_db
def test_conflicting_token_limit_settings_fail() -> None:
    serializer = WorkspaceAIProviderConfigSerializer(
        data=_payload(settings={'max_tokens': 100, 'max_completion_tokens': 100}),
        context={'workspace': WorkspaceFactory()},
    )

    assert not serializer.is_valid()
    assert '100' not in str(serializer.errors)


@pytest.mark.django_db
def test_secret_values_do_not_appear_in_errors_or_logs(caplog) -> None:
    secret = 'sk-ultra-sensitive-key'
    caplog.set_level(logging.INFO)
    serializer = WorkspaceAIProviderConfigSerializer(
        data=_payload(api_key=secret, settings={'headers': {'Authorization': 'Bearer hidden'}}),
        context={'workspace': WorkspaceFactory()},
    )

    assert not serializer.is_valid()
    assert secret not in str(serializer.errors)
    assert secret not in caplog.text
    assert 'Bearer hidden' not in str(serializer.errors)
    assert 'Bearer hidden' not in caplog.text


@pytest.mark.django_db
def test_raw_encrypted_value_is_not_returned_in_representation() -> None:
    config = WorkspaceAIProviderConfigFactory(api_key='sk-raw-secret')
    raw_value = config.__dict__['api_key']

    data = WorkspaceAIProviderConfigSerializer(config).data

    assert raw_value not in str(data)
    assert 'sk-raw-secret' not in str(data)


@pytest.mark.django_db
def test_serializer_public_fields_are_stable() -> None:
    config = WorkspaceAIProviderConfigFactory()

    data = WorkspaceAIProviderConfigSerializer(config).data

    assert set(data) == {
        'id',
        'provider',
        'model_name',
        'system_prompt',
        'settings',
        'is_active',
        'has_api_key',
        'is_supported',
        'created_at',
        'updated_at',
    }
