from __future__ import annotations

import logging
from unittest.mock import MagicMock, patch

import pytest

from omnichannel.ai.connection_test import (
    CONNECTIVITY_TEST_MESSAGES,
    AIProviderConnectionTestResult,
    get_connection_test_http_status,
    test_ai_provider_connection as run_ai_provider_connection,
)
from omnichannel.ai.exceptions import (
    AIProviderAuthenticationError,
    AIProviderError,
    AIProviderInvalidRequestError,
    AIProviderRateLimitError,
    AIProviderTimeoutError,
    AIProviderUnavailableError,
    UnsupportedAIProviderError,
)
from omnichannel.ai.types import AIProviderResult
from workspaces.factories import WorkspaceAIProviderConfigFactory
from workspaces.models import AIProvider


def _adapter() -> MagicMock:
    adapter = MagicMock()
    adapter.generate_response.return_value = AIProviderResult(
        text='OK',
        provider=AIProvider.OPENAI,
        model_name='gpt-4o-mini',
    )
    return adapter


@pytest.mark.django_db
def test_connection_service_uses_registry_adapter_and_saved_key() -> None:
    config = WorkspaceAIProviderConfigFactory(api_key='sk-saved-provider-key')
    adapter = _adapter()

    with patch('omnichannel.ai.connection_test.get_provider_adapter', return_value=adapter) as mock_registry:
        result = run_ai_provider_connection(provider_config=config)

    assert result == AIProviderConnectionTestResult(
        success=True,
        provider=AIProvider.OPENAI,
        model_name='gpt-4o-mini',
        message='Credencial validada com sucesso.',
    )
    mock_registry.assert_called_once_with(provider=AIProvider.OPENAI, api_key='sk-saved-provider-key')


@pytest.mark.django_db
def test_connection_service_uses_api_key_override_without_saving() -> None:
    config = WorkspaceAIProviderConfigFactory(api_key='sk-saved-provider-key')
    adapter = _adapter()

    with patch('omnichannel.ai.connection_test.get_provider_adapter', return_value=adapter) as mock_registry:
        run_ai_provider_connection(provider_config=config, api_key_override='sk-temporary-provider-key')

    config.refresh_from_db()
    assert config.api_key == 'sk-saved-provider-key'
    mock_registry.assert_called_once_with(provider=AIProvider.OPENAI, api_key='sk-temporary-provider-key')


@pytest.mark.django_db
def test_connection_service_passes_model_name_messages_and_safe_settings() -> None:
    config = WorkspaceAIProviderConfigFactory(
        model_name='gpt-4.1-mini',
        system_prompt='Prompt real do cliente que nao deve ir para o teste.',
        settings={'temperature': 1, 'max_tokens': 1000},
    )
    adapter = _adapter()

    with patch('omnichannel.ai.connection_test.get_provider_adapter', return_value=adapter):
        run_ai_provider_connection(provider_config=config)

    adapter.generate_response.assert_called_once()
    call_kwargs = adapter.generate_response.call_args.kwargs
    assert call_kwargs['model_name'] == 'gpt-4.1-mini'
    assert call_kwargs['messages'] == CONNECTIVITY_TEST_MESSAGES
    assert 'Prompt real do cliente' not in str(call_kwargs['messages'])
    assert call_kwargs['settings'] == {
        'temperature': 0,
        'max_tokens': 3,
        'timeout': 5,
    }
    assert 'max_completion_tokens' not in call_kwargs['settings']


@pytest.mark.django_db
@pytest.mark.parametrize(
    ('exception', 'error_code', 'status_code'),
    [
        (UnsupportedAIProviderError('unsupported'), 'UNSUPPORTED_PROVIDER', 400),
        (AIProviderAuthenticationError('auth'), 'INVALID_CREDENTIALS', 400),
        (AIProviderRateLimitError('rate'), 'RATE_LIMITED', 429),
        (AIProviderTimeoutError('timeout'), 'PROVIDER_TIMEOUT', 504),
        (AIProviderUnavailableError('unavailable'), 'PROVIDER_UNAVAILABLE', 503),
        (AIProviderInvalidRequestError('invalid'), 'INVALID_REQUEST', 400),
        (AIProviderError('provider'), 'PROVIDER_ERROR', 502),
        (RuntimeError('boom'), 'PROVIDER_ERROR', 502),
    ],
)
def test_connection_service_maps_errors_without_leaking_api_key(
    exception: Exception,
    error_code: str,
    status_code: int,
    caplog,
) -> None:
    config = WorkspaceAIProviderConfigFactory(api_key='sk-sensitive-service-key')
    caplog.set_level(logging.WARNING)
    adapter = _adapter()
    adapter.generate_response.side_effect = exception

    with patch('omnichannel.ai.connection_test.get_provider_adapter', return_value=adapter):
        result = run_ai_provider_connection(provider_config=config)

    assert result.success is False
    assert result.error_code == error_code
    assert get_connection_test_http_status(result) == status_code
    assert 'sk-sensitive-service-key' not in str(result)
    assert 'sk-sensitive-service-key' not in caplog.text


@pytest.mark.django_db
def test_connection_service_maps_registry_unsupported_provider() -> None:
    config = WorkspaceAIProviderConfigFactory(provider=AIProvider.ANTHROPIC, is_active=False)

    with patch(
        'omnichannel.ai.connection_test.get_provider_adapter',
        side_effect=UnsupportedAIProviderError('unsupported'),
    ):
        result = run_ai_provider_connection(provider_config=config)

    assert result.success is False
    assert result.error_code == 'UNSUPPORTED_PROVIDER'
    assert get_connection_test_http_status(result) == 400
