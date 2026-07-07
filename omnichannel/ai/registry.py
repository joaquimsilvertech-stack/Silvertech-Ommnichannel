from __future__ import annotations

from workspaces.models import AIProvider

from .base import BaseAIProviderAdapter
from .exceptions import UnsupportedAIProviderError
from .providers.openai import OpenAIAdapter

PROVIDER_ADAPTERS: dict[str, type[BaseAIProviderAdapter]] = {
    AIProvider.OPENAI: OpenAIAdapter,
}


def get_provider_adapter(*, provider: str, api_key: str) -> BaseAIProviderAdapter:
    adapter_class = PROVIDER_ADAPTERS.get(provider)
    if adapter_class is None:
        raise UnsupportedAIProviderError(f'Provider de IA nao suportado: {provider}')

    return adapter_class(api_key=api_key)
