from __future__ import annotations

from .base import BaseEvolutionClient
from .client import EvolutionAPIClient, get_evolution_client
from .exceptions import (
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
    EvolutionUnexpectedResponseError,
)

__all__ = [
    'BaseEvolutionClient',
    'EvolutionAPIClient',
    'EvolutionAPIError',
    'EvolutionAuthenticationError',
    'EvolutionConfigurationError',
    'EvolutionConflictError',
    'EvolutionConnectionError',
    'EvolutionInvalidRequestError',
    'EvolutionInvalidResponseError',
    'EvolutionNotFoundError',
    'EvolutionRateLimitError',
    'EvolutionTimeoutError',
    'EvolutionUnavailableError',
    'EvolutionUnexpectedResponseError',
    'get_evolution_client',
]
