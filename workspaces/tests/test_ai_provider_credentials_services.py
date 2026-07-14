from __future__ import annotations

import inspect
import logging
from unittest.mock import patch

import pytest

from omnichannel.ai.connection_test import AIProviderConnectionTestResult
from workspaces.factories import WorkspaceAIProviderConfigFactory
from workspaces.models import AIProvider
from workspaces.services import (
    AIProviderCredentialError,
    replace_ai_provider_credentials,
    revoke_ai_provider_credentials,
)


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


@pytest.mark.django_db
def test_replace_ai_provider_credentials_tests_before_saving_and_preserves_config() -> None:
    config = WorkspaceAIProviderConfigFactory(
        api_key='sk-old-provider-key',
        is_active=True,
        model_name='gpt-4o-mini',
        system_prompt='Prompt original.',
        settings={'temperature': 0.2},
    )

    with patch(
        'workspaces.services.test_ai_provider_connection',
        return_value=_success_result(config),
    ) as mock_test:
        replaced = replace_ai_provider_credentials(
            workspace=config.workspace,
            provider_config=config,
            api_key='sk-new-provider-key',
        )

    assert replaced.api_key == 'sk-new-provider-key'
    assert replaced.is_active is True
    assert replaced.model_name == 'gpt-4o-mini'
    assert replaced.system_prompt == 'Prompt original.'
    assert replaced.settings == {'temperature': 0.2}
    mock_test.assert_called_once_with(
        provider_config=config,
        api_key_override='sk-new-provider-key',
    )


@pytest.mark.django_db
def test_replace_ai_provider_credentials_keeps_old_key_when_provider_test_fails() -> None:
    config = WorkspaceAIProviderConfigFactory(api_key='sk-old-provider-key', is_active=False)

    with patch(
        'workspaces.services.test_ai_provider_connection',
        return_value=_error_result(config, 'INVALID_CREDENTIALS'),
    ):
        with pytest.raises(AIProviderCredentialError) as exc_info:
            replace_ai_provider_credentials(
                workspace=config.workspace,
                provider_config=config,
                api_key='sk-invalid-provider-key',
            )

    config.refresh_from_db()
    assert config.api_key == 'sk-old-provider-key'
    assert config.is_active is False
    assert exc_info.value.error_code == 'INVALID_CREDENTIALS'


@pytest.mark.django_db
def test_replace_ai_provider_credentials_rejects_unsupported_provider_without_external_call() -> None:
    config = WorkspaceAIProviderConfigFactory(
        provider=AIProvider.ANTHROPIC,
        api_key='sk-old-provider-key',
        is_active=False,
    )

    with patch('workspaces.services.test_ai_provider_connection') as mock_test:
        with pytest.raises(AIProviderCredentialError) as exc_info:
            replace_ai_provider_credentials(
                workspace=config.workspace,
                provider_config=config,
                api_key='sk-new-provider-key',
            )

    config.refresh_from_db()
    assert config.api_key == 'sk-old-provider-key'
    assert exc_info.value.error_code == 'UNSUPPORTED_PROVIDER'
    mock_test.assert_not_called()


def test_replace_ai_provider_credentials_uses_atomic_and_select_for_update() -> None:
    source = inspect.getsource(replace_ai_provider_credentials)

    assert 'transaction.atomic' in source
    assert 'select_for_update' in source


@pytest.mark.django_db
def test_revoke_ai_provider_credentials_clears_key_and_deactivates_without_touching_config() -> None:
    config = WorkspaceAIProviderConfigFactory(
        api_key='sk-provider-key',
        is_active=True,
        model_name='gpt-4o-mini',
        system_prompt='Prompt original.',
        settings={'temperature': 0.2},
    )

    with patch('workspaces.services.test_ai_provider_connection') as mock_test:
        revoked = revoke_ai_provider_credentials(
            workspace=config.workspace,
            provider_config=config,
        )

    assert revoked.api_key == ''
    assert revoked.is_active is False
    assert revoked.model_name == 'gpt-4o-mini'
    assert revoked.system_prompt == 'Prompt original.'
    assert revoked.settings == {'temperature': 0.2}
    mock_test.assert_not_called()


@pytest.mark.django_db
def test_revoke_ai_provider_credentials_is_idempotent() -> None:
    config = WorkspaceAIProviderConfigFactory(api_key='', is_active=False)

    revoked = revoke_ai_provider_credentials(
        workspace=config.workspace,
        provider_config=config,
    )

    assert revoked.api_key == ''
    assert revoked.is_active is False


def test_revoke_ai_provider_credentials_uses_atomic_and_select_for_update() -> None:
    source = inspect.getsource(revoke_ai_provider_credentials)

    assert 'transaction.atomic' in source
    assert 'select_for_update' in source


@pytest.mark.django_db
def test_credential_services_logs_do_not_expose_api_key(caplog) -> None:
    config = WorkspaceAIProviderConfigFactory(api_key='sk-old-provider-key', is_active=True)
    caplog.set_level(logging.INFO)

    with patch(
        'workspaces.services.test_ai_provider_connection',
        return_value=_success_result(config),
    ):
        replace_ai_provider_credentials(
            workspace=config.workspace,
            provider_config=config,
            api_key='sk-new-provider-key',
        )
        revoke_ai_provider_credentials(
            workspace=config.workspace,
            provider_config=config,
        )

    assert 'sk-old-provider-key' not in caplog.text
    assert 'sk-new-provider-key' not in caplog.text
    assert 'api_key' not in caplog.text
    actions = {getattr(record, 'action', None) for record in caplog.records}
    assert 'replace_credentials' in actions
    assert 'revoke_credentials' in actions


@pytest.mark.django_db
def test_replace_failure_log_does_not_expose_api_key(caplog) -> None:
    config = WorkspaceAIProviderConfigFactory(api_key='sk-old-provider-key', is_active=False)
    caplog.set_level(logging.WARNING)

    with patch(
        'workspaces.services.test_ai_provider_connection',
        return_value=_error_result(config, 'INVALID_CREDENTIALS'),
    ):
        with pytest.raises(AIProviderCredentialError):
            replace_ai_provider_credentials(
                workspace=config.workspace,
                provider_config=config,
                api_key='sk-invalid-provider-key',
            )

    assert 'sk-old-provider-key' not in caplog.text
    assert 'sk-invalid-provider-key' not in caplog.text
    assert 'api_key' not in caplog.text
    error_codes = {getattr(record, 'error_code', None) for record in caplog.records}
    assert 'INVALID_CREDENTIALS' in error_codes
