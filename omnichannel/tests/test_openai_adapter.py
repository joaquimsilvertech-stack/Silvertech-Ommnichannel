from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import httpx
import openai
import pytest

from omnichannel.ai.exceptions import (
    AIProviderAuthenticationError,
    AIProviderInvalidRequestError,
    AIProviderInvalidResponseError,
    AIProviderRateLimitError,
    AIProviderTimeoutError,
    AIProviderUnavailableError,
)
from omnichannel.ai.providers.openai import OpenAIAdapter
from omnichannel.ai.types import AIProviderResult
from workspaces.models import AIProvider


def _openai_response(
    content: str | None = 'Resposta normalizada.',
    *,
    response_id: str = 'chatcmpl-test',
    model: str = 'gpt-4o-mini-2026',
):
    return SimpleNamespace(
        id=response_id,
        model=model,
        usage=SimpleNamespace(
            prompt_tokens=11,
            completion_tokens=7,
            total_tokens=18,
        ),
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(content=content),
            ),
        ],
    )


def _client_with_response(response=None):
    create = MagicMock(return_value=response or _openai_response())
    client = SimpleNamespace(
        chat=SimpleNamespace(
            completions=SimpleNamespace(create=create),
        ),
    )
    return client, create


def _httpx_response(status_code: int = 400) -> httpx.Response:
    request = httpx.Request('POST', 'https://api.openai.example.test')
    return httpx.Response(status_code=status_code, request=request)


def test_openai_adapter_instantiates_sdk_with_api_key() -> None:
    with patch('omnichannel.ai.providers.openai.openai.OpenAI') as mock_openai:
        OpenAIAdapter(api_key='sk-openai-adapter')

    mock_openai.assert_called_once_with(api_key='sk-openai-adapter')


def test_openai_adapter_sends_model_messages_and_allowed_settings() -> None:
    client, mock_create = _client_with_response()

    with patch('omnichannel.ai.providers.openai.openai.OpenAI', return_value=client):
        adapter = OpenAIAdapter(api_key='sk-openai-adapter')
        result = adapter.generate_response(
            model_name='gpt-4o-mini',
            system_prompt='Prompt ja presente nas mensagens',
            messages=[
                {'role': 'system', 'content': 'Prompt ja presente nas mensagens'},
                {'role': 'user', 'content': 'Ola'},
            ],
            settings={
                'temperature': 0.3,
                'top_p': 0.9,
                'max_tokens': 120,
                'frequency_penalty': 0,
                'presence_penalty': 1.2,
                'timeout': 30,
            },
        )

    mock_create.assert_called_once_with(
        model='gpt-4o-mini',
        messages=[
            {'role': 'system', 'content': 'Prompt ja presente nas mensagens'},
            {'role': 'user', 'content': 'Ola'},
        ],
        temperature=0.3,
        top_p=0.9,
        max_tokens=120,
        frequency_penalty=0,
        presence_penalty=1.2,
        timeout=30,
    )
    assert isinstance(result, AIProviderResult)
    assert result.text == 'Resposta normalizada.'
    assert result.provider == AIProvider.OPENAI
    assert result.model_name == 'gpt-4o-mini-2026'
    assert result.external_id == 'chatcmpl-test'
    assert result.prompt_tokens == 11
    assert result.completion_tokens == 7
    assert result.total_tokens == 18


def test_openai_adapter_does_not_duplicate_system_prompt() -> None:
    client, mock_create = _client_with_response()

    with patch('omnichannel.ai.providers.openai.openai.OpenAI', return_value=client):
        adapter = OpenAIAdapter(api_key='sk-openai-adapter')
        adapter.generate_response(
            model_name='gpt-4o-mini',
            system_prompt='Prompt oficial',
            messages=[{'role': 'system', 'content': 'Prompt oficial'}],
            settings={},
        )

    assert mock_create.call_args.kwargs['messages'] == [
        {'role': 'system', 'content': 'Prompt oficial'},
    ]


@pytest.mark.parametrize(
    'setting_payload',
    [
        {'api_key': 'sk-should-not-pass'},
        {'headers': {'Authorization': 'Bearer secret'}},
        {'temperature': 3},
        {'top_p': -0.1},
        {'max_tokens': True},
        {'max_completion_tokens': 0},
        {'frequency_penalty': -3},
        {'presence_penalty': 3},
        {'timeout': 0},
    ],
)
def test_openai_adapter_rejects_invalid_settings(setting_payload) -> None:
    client, _ = _client_with_response()

    with patch('omnichannel.ai.providers.openai.openai.OpenAI', return_value=client):
        adapter = OpenAIAdapter(api_key='sk-openai-adapter')
        with pytest.raises(AIProviderInvalidRequestError) as exc_info:
            adapter.generate_response(
                model_name='gpt-4o-mini',
                system_prompt='Prompt',
                messages=[{'role': 'user', 'content': 'Ola'}],
                settings=setting_payload,
            )

    assert 'sk-openai-adapter' not in str(exc_info.value)
    assert 'sk-should-not-pass' not in str(exc_info.value)
    assert 'Bearer secret' not in str(exc_info.value)


@pytest.mark.parametrize('content', [None, '', '   '])
def test_openai_adapter_rejects_empty_text_response(content: str | None) -> None:
    client, _ = _client_with_response(_openai_response(content=content))

    with patch('omnichannel.ai.providers.openai.openai.OpenAI', return_value=client):
        adapter = OpenAIAdapter(api_key='sk-openai-adapter')
        with pytest.raises(AIProviderInvalidResponseError):
            adapter.generate_response(
                model_name='gpt-4o-mini',
                system_prompt='Prompt',
                messages=[{'role': 'user', 'content': 'Ola'}],
                settings={},
            )


def test_openai_adapter_rejects_unexpected_response_shape() -> None:
    client, _ = _client_with_response(SimpleNamespace(choices=[]))

    with patch('omnichannel.ai.providers.openai.openai.OpenAI', return_value=client):
        adapter = OpenAIAdapter(api_key='sk-openai-adapter')
        with pytest.raises(AIProviderInvalidResponseError):
            adapter.generate_response(
                model_name='gpt-4o-mini',
                system_prompt='Prompt',
                messages=[{'role': 'user', 'content': 'Ola'}],
                settings={},
            )


@pytest.mark.parametrize(
    ('sdk_error', 'internal_error'),
    [
        (
            openai.AuthenticationError(
                'auth failed',
                response=_httpx_response(401),
                body=None,
            ),
            AIProviderAuthenticationError,
        ),
        (
            openai.RateLimitError(
                'rate limited',
                response=_httpx_response(429),
                body=None,
            ),
            AIProviderRateLimitError,
        ),
        (
            openai.APITimeoutError(request=httpx.Request('POST', 'https://api.openai.example.test')),
            AIProviderTimeoutError,
        ),
        (
            openai.APIConnectionError(
                request=httpx.Request('POST', 'https://api.openai.example.test'),
            ),
            AIProviderUnavailableError,
        ),
        (
            openai.InternalServerError(
                'server error',
                response=_httpx_response(500),
                body=None,
            ),
            AIProviderUnavailableError,
        ),
        (
            openai.BadRequestError(
                'bad request',
                response=_httpx_response(400),
                body=None,
            ),
            AIProviderInvalidRequestError,
        ),
    ],
)
def test_openai_adapter_maps_sdk_errors(sdk_error, internal_error) -> None:
    create = MagicMock(side_effect=sdk_error)
    client = SimpleNamespace(
        chat=SimpleNamespace(
            completions=SimpleNamespace(create=create),
        ),
    )

    with patch('omnichannel.ai.providers.openai.openai.OpenAI', return_value=client):
        adapter = OpenAIAdapter(api_key='sk-sensitive-key')
        with pytest.raises(internal_error) as exc_info:
            adapter.generate_response(
                model_name='gpt-4o-mini',
                system_prompt='Prompt',
                messages=[{'role': 'user', 'content': 'Ola'}],
                settings={},
            )

    assert 'sk-sensitive-key' not in str(exc_info.value)
