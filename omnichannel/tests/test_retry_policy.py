from __future__ import annotations

import pytest
import requests

from omnichannel.ai.exceptions import (
    AIProviderAuthenticationError,
    AIProviderInvalidRequestError,
    AIProviderRateLimitError,
    AIProviderTimeoutError,
    AIProviderUnavailableError,
)
from omnichannel.services import (
    EVOLUTION_CONNECTION_ERROR,
    EVOLUTION_INVALID_RESPONSE,
    EVOLUTION_REQUEST_ERROR,
    EVOLUTION_TIMEOUT,
    EVOLUTION_UNKNOWN_ERROR,
    calculate_exponential_backoff,
    is_retryable_ai_provider_error,
    map_evolution_exception_to_error_code,
    sanitize_message_send_error_code,
)


@pytest.mark.parametrize(
    ('attempt_number', 'expected_seconds'),
    [
        (1, 60),
        (2, 300),
        (3, 900),
        (0, 60),
        (-1, 60),
    ],
)
def test_calculate_exponential_backoff_is_deterministic(attempt_number: int, expected_seconds: int) -> None:
    assert calculate_exponential_backoff(attempt_number) == expected_seconds


def test_calculate_exponential_backoff_never_returns_negative() -> None:
    assert calculate_exponential_backoff(1, base_seconds=-10) == 0


@pytest.mark.parametrize(
    'exception',
    [
        AIProviderRateLimitError('rate'),
        AIProviderTimeoutError('timeout'),
        AIProviderUnavailableError('unavailable'),
    ],
)
def test_retryable_ai_provider_errors(exception: Exception) -> None:
    assert is_retryable_ai_provider_error(exception) is True


@pytest.mark.parametrize(
    'exception',
    [
        AIProviderAuthenticationError('auth'),
        AIProviderInvalidRequestError('invalid'),
        Exception('generic'),
    ],
)
def test_permanent_ai_provider_errors(exception: Exception) -> None:
    assert is_retryable_ai_provider_error(exception) is False


@pytest.mark.parametrize(
    ('exception', 'expected_error_code'),
    [
        (requests.exceptions.Timeout('timeout'), EVOLUTION_TIMEOUT),
        (requests.exceptions.ConnectionError('connection'), EVOLUTION_CONNECTION_ERROR),
        (requests.exceptions.RequestException('request'), EVOLUTION_REQUEST_ERROR),
        (ValueError('invalid json'), EVOLUTION_INVALID_RESPONSE),
        (RuntimeError('unknown'), EVOLUTION_UNKNOWN_ERROR),
    ],
)
def test_map_evolution_exception_to_error_code(exception: Exception, expected_error_code: str) -> None:
    assert map_evolution_exception_to_error_code(exception) == expected_error_code


def test_sanitized_error_code_does_not_keep_sensitive_or_dangerous_characters() -> None:
    sanitized = sanitize_message_send_error_code('api_key: sk-secret\nAuthorization header <payload>')

    assert '\n' not in sanitized
    assert ':' not in sanitized
    assert '<' not in sanitized
    assert len(sanitized) <= 64
