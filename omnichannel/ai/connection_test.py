from __future__ import annotations

import logging
from dataclasses import dataclass

from workspaces.models import WorkspaceAIProviderConfig

from .exceptions import (
    AIProviderAuthenticationError,
    AIProviderError,
    AIProviderInvalidRequestError,
    AIProviderRateLimitError,
    AIProviderTimeoutError,
    AIProviderUnavailableError,
    UnsupportedAIProviderError,
)
from .registry import get_provider_adapter

logger = logging.getLogger(__name__)

CONNECTIVITY_TEST_MESSAGES = [
    {
        'role': 'system',
        'content': 'You are a connectivity check. Reply with OK.',
    },
    {
        'role': 'user',
        'content': 'Reply with OK.',
    },
]
CONNECTIVITY_TEST_SETTINGS = {
    'temperature': 0,
    'max_tokens': 3,
    'timeout': 5,
}


@dataclass(frozen=True, slots=True)
class AIProviderConnectionTestResult:
    success: bool
    provider: str
    model_name: str
    message: str
    error_code: str | None = None


def test_ai_provider_connection(
    *,
    provider_config: WorkspaceAIProviderConfig,
    api_key_override: str | None = None,
) -> AIProviderConnectionTestResult:
    api_key = api_key_override or provider_config.api_key

    try:
        adapter = get_provider_adapter(
            provider=provider_config.provider,
            api_key=api_key,
        )
        adapter.generate_response(
            model_name=provider_config.model_name,
            messages=CONNECTIVITY_TEST_MESSAGES,
            settings=CONNECTIVITY_TEST_SETTINGS,
        )
    except UnsupportedAIProviderError as exc:
        return _connection_error_result(
            provider_config=provider_config,
            error_code='UNSUPPORTED_PROVIDER',
            message='Este provedor ainda nao possui adapter ativo.',
            status=400,
            exc=exc,
        )
    except AIProviderAuthenticationError as exc:
        return _connection_error_result(
            provider_config=provider_config,
            error_code='INVALID_CREDENTIALS',
            message='A credencial informada nao foi aceita pelo provedor.',
            status=400,
            exc=exc,
        )
    except AIProviderRateLimitError as exc:
        return _connection_error_result(
            provider_config=provider_config,
            error_code='RATE_LIMITED',
            message='O provedor recusou a requisicao por limite de uso.',
            status=429,
            exc=exc,
        )
    except AIProviderTimeoutError as exc:
        return _connection_error_result(
            provider_config=provider_config,
            error_code='PROVIDER_TIMEOUT',
            message='O provedor nao respondeu dentro do tempo limite.',
            status=504,
            exc=exc,
        )
    except AIProviderUnavailableError as exc:
        return _connection_error_result(
            provider_config=provider_config,
            error_code='PROVIDER_UNAVAILABLE',
            message='O provedor esta temporariamente indisponivel.',
            status=503,
            exc=exc,
        )
    except AIProviderInvalidRequestError as exc:
        return _connection_error_result(
            provider_config=provider_config,
            error_code='INVALID_REQUEST',
            message='A configuracao enviada ao provedor e invalida.',
            status=400,
            exc=exc,
        )
    except AIProviderError as exc:
        return _connection_error_result(
            provider_config=provider_config,
            error_code='PROVIDER_ERROR',
            message='Nao foi possivel validar a conexao com o provedor.',
            status=502,
            exc=exc,
        )
    except Exception as exc:
        return _connection_error_result(
            provider_config=provider_config,
            error_code='PROVIDER_ERROR',
            message='Nao foi possivel validar a conexao com o provedor.',
            status=502,
            exc=exc,
        )

    return AIProviderConnectionTestResult(
        success=True,
        provider=provider_config.provider,
        model_name=provider_config.model_name,
        message='Credencial validada com sucesso.',
    )


def get_connection_test_http_status(result: AIProviderConnectionTestResult) -> int:
    if result.success:
        return 200

    return {
        'INVALID_CREDENTIALS': 400,
        'RATE_LIMITED': 429,
        'PROVIDER_TIMEOUT': 504,
        'PROVIDER_UNAVAILABLE': 503,
        'INVALID_REQUEST': 400,
        'UNSUPPORTED_PROVIDER': 400,
        'PROVIDER_ERROR': 502,
    }.get(result.error_code, 502)


def _connection_error_result(
    *,
    provider_config: WorkspaceAIProviderConfig,
    error_code: str,
    message: str,
    status: int,
    exc: Exception,
) -> AIProviderConnectionTestResult:
    logger.warning(
        'Falha ao testar conexao com provider de IA',
        extra={
            'workspace_id': str(provider_config.workspace_id),
            'provider_config_id': str(provider_config.id),
            'provider': provider_config.provider,
            'model_name': provider_config.model_name,
            'error_code': error_code,
            'status': status,
            'exception_type': type(exc).__name__,
        },
    )
    return AIProviderConnectionTestResult(
        success=False,
        provider=provider_config.provider,
        model_name=provider_config.model_name,
        message=message,
        error_code=error_code,
    )
