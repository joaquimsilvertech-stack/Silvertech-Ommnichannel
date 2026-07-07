from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class AIProviderResult:
    text: str
    provider: str
    model_name: str
    external_id: str | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None

    def __post_init__(self) -> None:
        if not self.text or not self.text.strip():
            raise ValueError('AIProviderResult.text nao pode ser vazio.')
