from __future__ import annotations

from typing import Any

import openai

from workspaces.models import AIProvider

from ..base import BaseAIProviderAdapter
from ..exceptions import (
    AIProviderAuthenticationError,
    AIProviderError,
    AIProviderInvalidRequestError,
    AIProviderInvalidResponseError,
    AIProviderRateLimitError,
    AIProviderTimeoutError,
    AIProviderUnavailableError,
)
from ..types import AIProviderResult
from .openai_settings import validate_openai_settings


class OpenAIAdapter(BaseAIProviderAdapter):
    """Adapter OpenAI baseado em Chat Completions."""

    provider = AIProvider.OPENAI

    def __init__(self, *, api_key: str):
        if not api_key:
            raise AIProviderAuthenticationError('Credencial OpenAI nao configurada.')

        self._client = openai.OpenAI(api_key=api_key)

    def generate_response(
        self,
        *,
        model_name: str,
        messages: list[dict[str, str]],
        settings: dict[str, Any],
    ) -> AIProviderResult:
        request_settings = validate_openai_settings(settings)

        try:
            response = self._client.chat.completions.create(
                model=model_name,
                messages=messages,
                **request_settings,
            )
        except openai.AuthenticationError as exc:
            raise AIProviderAuthenticationError('Falha de autenticacao no provider OpenAI.') from exc
        except openai.RateLimitError as exc:
            raise AIProviderRateLimitError('Limite de taxa atingido no provider OpenAI.') from exc
        except openai.APITimeoutError as exc:
            raise AIProviderTimeoutError('Timeout ao chamar provider OpenAI.') from exc
        except openai.APIConnectionError as exc:
            raise AIProviderUnavailableError('Provider OpenAI indisponivel.') from exc
        except openai.InternalServerError as exc:
            raise AIProviderUnavailableError('Provider OpenAI retornou erro 5xx.') from exc
        except openai.BadRequestError as exc:
            raise AIProviderInvalidRequestError('Requisicao invalida para provider OpenAI.') from exc
        except openai.APIStatusError as exc:
            if getattr(exc, 'status_code', None) and exc.status_code >= 500:
                raise AIProviderUnavailableError('Provider OpenAI retornou erro 5xx.') from exc
            raise AIProviderInvalidRequestError('Provider OpenAI recusou a requisicao.') from exc
        except openai.APIResponseValidationError as exc:
            raise AIProviderInvalidResponseError('Resposta invalida do provider OpenAI.') from exc
        except openai.OpenAIError as exc:
            raise AIProviderError('Erro operacional no provider OpenAI.') from exc

        return _normalize_openai_response(response, requested_model_name=model_name)


def _normalize_openai_response(response: Any, *, requested_model_name: str) -> AIProviderResult:
    try:
        choice = response.choices[0]
        text = choice.message.content
    except (AttributeError, IndexError, TypeError) as exc:
        raise AIProviderInvalidResponseError('Resposta OpenAI sem conteudo esperado.') from exc

    if not text or not text.strip():
        raise AIProviderInvalidResponseError('Resposta OpenAI vazia.')

    usage = getattr(response, 'usage', None)
    model_name = getattr(response, 'model', None) or requested_model_name

    return AIProviderResult(
        text=text.strip(),
        provider=AIProvider.OPENAI,
        model_name=model_name,
        external_id=getattr(response, 'id', None),
        prompt_tokens=getattr(usage, 'prompt_tokens', None),
        completion_tokens=getattr(usage, 'completion_tokens', None),
        total_tokens=getattr(usage, 'total_tokens', None),
    )
