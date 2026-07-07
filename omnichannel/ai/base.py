from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from .types import AIProviderResult


class BaseAIProviderAdapter(ABC):
    """Contrato comum para adapters de providers de IA."""

    provider: str

    @abstractmethod
    def generate_response(
        self,
        *,
        model_name: str,
        messages: list[dict[str, str]],
        settings: dict[str, Any],
    ) -> AIProviderResult:
        raise NotImplementedError
