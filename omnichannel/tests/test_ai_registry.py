from __future__ import annotations

from unittest.mock import patch

import pytest

from omnichannel.ai.exceptions import UnsupportedAIProviderError
from omnichannel.ai.providers.openai import OpenAIAdapter
from omnichannel.ai.registry import get_provider_adapter, is_provider_supported
from workspaces.models import AIProvider


def test_registry_returns_openai_adapter() -> None:
    with patch('omnichannel.ai.providers.openai.openai.OpenAI'):
        adapter = get_provider_adapter(provider=AIProvider.OPENAI, api_key='sk-registry-key')

    assert isinstance(adapter, OpenAIAdapter)


@pytest.mark.parametrize(
    ('provider', 'expected'),
    [
        (AIProvider.OPENAI, True),
        (AIProvider.ANTHROPIC, False),
        (AIProvider.GOOGLE, False),
    ],
)
def test_is_provider_supported(provider: str, expected: bool) -> None:
    with patch('omnichannel.ai.providers.openai.openai.OpenAI') as mock_openai:
        assert is_provider_supported(provider) is expected

    mock_openai.assert_not_called()


@pytest.mark.parametrize('provider', [AIProvider.ANTHROPIC, AIProvider.GOOGLE, 'unknown'])
def test_registry_rejects_unsupported_providers(provider: str) -> None:
    with pytest.raises(UnsupportedAIProviderError) as exc_info:
        get_provider_adapter(provider=provider, api_key='sk-secret-key')

    assert 'sk-secret-key' not in str(exc_info.value)


def test_registry_returns_new_adapter_instances() -> None:
    with patch('omnichannel.ai.providers.openai.openai.OpenAI'):
        first = get_provider_adapter(provider=AIProvider.OPENAI, api_key='sk-first')
        second = get_provider_adapter(provider=AIProvider.OPENAI, api_key='sk-first')

    assert first is not second


def test_registry_passes_api_keys_to_isolated_adapter_instances() -> None:
    with patch('omnichannel.ai.providers.openai.openai.OpenAI') as mock_openai:
        first = get_provider_adapter(provider=AIProvider.OPENAI, api_key='sk-first')
        second = get_provider_adapter(provider=AIProvider.OPENAI, api_key='sk-second')

    assert first is not second
    assert mock_openai.call_args_list[0].kwargs == {'api_key': 'sk-first'}
    assert mock_openai.call_args_list[1].kwargs == {'api_key': 'sk-second'}


@pytest.mark.django_db
def test_registry_does_not_access_database(django_assert_num_queries) -> None:
    with patch('omnichannel.ai.providers.openai.openai.OpenAI'):
        with django_assert_num_queries(0):
            get_provider_adapter(provider=AIProvider.OPENAI, api_key='sk-no-db')
