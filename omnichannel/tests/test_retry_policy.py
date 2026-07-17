from __future__ import annotations

import pytest

from omnichannel.ai.exceptions import (
    AIProviderAuthenticationError,
    AIProviderInvalidRequestError,
    AIProviderRateLimitError,
    AIProviderTimeoutError,
    AIProviderUnavailableError,
)
from omnichannel.evolution import (
    EvolutionAPIError,
    EvolutionAuthenticationError,
    EvolutionConfigurationError,
    EvolutionConflictError,
    EvolutionConnectionError,
    EvolutionInvalidRequestError,
    EvolutionInvalidResponseError,
    EvolutionNotFoundError,
    EvolutionRateLimitError,
    EvolutionTimeoutError,
    EvolutionUnavailableError,
)
from omnichannel.services import (
    EVOLUTION_AUTHENTICATION_ERROR,
    EVOLUTION_CONFIGURATION_ERROR,
    EVOLUTION_CONFLICT,
    EVOLUTION_CONNECTION_ERROR,
    EVOLUTION_INVALID_REQUEST,
    EVOLUTION_INVALID_RESPONSE,
    EVOLUTION_NOT_FOUND,
    EVOLUTION_RATE_LIMIT,
    EVOLUTION_REQUEST_ERROR,
    EVOLUTION_TIMEOUT,
    EVOLUTION_UNAVAILABLE,
    EVOLUTION_UNKNOWN_ERROR,
    calculate_exponential_backoff,
    is_retryable_ai_provider_error,
    is_retryable_evolution_error,
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
        (EvolutionConfigurationError(), EVOLUTION_CONFIGURATION_ERROR),
        (EvolutionAuthenticationError(), EVOLUTION_AUTHENTICATION_ERROR),
        (EvolutionRateLimitError(), EVOLUTION_RATE_LIMIT),
        (EvolutionTimeoutError(), EVOLUTION_TIMEOUT),
        (EvolutionConnectionError(), EVOLUTION_CONNECTION_ERROR),
        (EvolutionUnavailableError(), EVOLUTION_UNAVAILABLE),
        (EvolutionInvalidRequestError(), EVOLUTION_INVALID_REQUEST),
        (EvolutionNotFoundError(), EVOLUTION_NOT_FOUND),
        (EvolutionConflictError(), EVOLUTION_CONFLICT),
        (EvolutionInvalidResponseError(), EVOLUTION_INVALID_RESPONSE),
        (EvolutionAPIError(), EVOLUTION_REQUEST_ERROR),
        (RuntimeError('unknown'), EVOLUTION_UNKNOWN_ERROR),
    ],
)
def test_map_evolution_exception_to_error_code(exception: Exception, expected_error_code: str) -> None:
    assert map_evolution_exception_to_error_code(exception) == expected_error_code


@pytest.mark.parametrize(
    'exception',
    [
        EvolutionTimeoutError(),
        EvolutionConnectionError(),
        EvolutionRateLimitError(),
        EvolutionUnavailableError(),
        EvolutionAPIError(retryable=True),
    ],
)
def test_retryable_evolution_errors(exception: Exception) -> None:
    assert is_retryable_evolution_error(exception) is True


@pytest.mark.parametrize(
    'exception',
    [
        EvolutionConfigurationError(),
        EvolutionAuthenticationError(),
        EvolutionInvalidRequestError(),
        EvolutionNotFoundError(),
        EvolutionConflictError(),
        EvolutionInvalidResponseError(),
        EvolutionAPIError(),
        RuntimeError('unknown'),
    ],
)
def test_permanent_evolution_errors(exception: Exception) -> None:
    assert is_retryable_evolution_error(exception) is False


def test_sanitized_error_code_does_not_keep_sensitive_or_dangerous_characters() -> None:
    sanitized = sanitize_message_send_error_code('api_key: sk-secret\nAuthorization header <payload>')

    assert '\n' not in sanitized
    assert ':' not in sanitized
    assert '<' not in sanitized
    assert len(sanitized) <= 64
