from __future__ import annotations


class AIProviderError(Exception):
    """Erro base da integracao com providers de IA."""


class AIProviderAuthenticationError(AIProviderError):
    pass


class AIProviderRateLimitError(AIProviderError):
    pass


class AIProviderTimeoutError(AIProviderError):
    pass


class AIProviderUnavailableError(AIProviderError):
    pass


class AIProviderInvalidRequestError(AIProviderError):
    pass


class AIProviderInvalidResponseError(AIProviderError):
    pass


class UnsupportedAIProviderError(AIProviderError):
    pass
