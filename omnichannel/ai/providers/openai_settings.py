from __future__ import annotations

from typing import Any

from ..exceptions import AIProviderInvalidRequestError

MAX_TIMEOUT_SECONDS = 120

ALLOWED_OPENAI_SETTINGS = {
    'temperature',
    'top_p',
    'max_tokens',
    'max_completion_tokens',
    'frequency_penalty',
    'presence_penalty',
    'timeout',
}

SENSITIVE_SETTING_KEYS = {
    'api_key',
    'openai_api_key',
    'authorization',
    'auth',
    'token',
    'access_token',
    'refresh_token',
    'secret',
    'password',
    'headers',
    'client',
    'transport',
    'proxies',
    'proxy',
    'base_url',
    'organization',
    'project',
}


def validate_openai_settings(settings: dict[str, Any] | None) -> dict[str, Any]:
    if not settings:
        return {}

    _validate_settings_mapping(settings)

    unknown_settings = set(settings) - ALLOWED_OPENAI_SETTINGS
    if unknown_settings:
        raise AIProviderInvalidRequestError('Settings OpenAI contem chaves nao suportadas.')

    if settings.get('max_tokens') is not None and settings.get('max_completion_tokens') is not None:
        raise AIProviderInvalidRequestError('Use apenas max_tokens ou max_completion_tokens.')

    validated: dict[str, Any] = {}
    for key, value in settings.items():
        if value is None:
            continue

        if key in {'max_tokens', 'max_completion_tokens'}:
            validated[key] = _validate_positive_int(key, value)
            continue

        if key == 'timeout':
            validated[key] = _validate_number_range(key, value, minimum=0, maximum=MAX_TIMEOUT_SECONDS)
            continue

        if key == 'temperature':
            validated[key] = _validate_number_range(key, value, minimum=0, maximum=2)
            continue

        if key == 'top_p':
            validated[key] = _validate_number_range(key, value, minimum=0, maximum=1)
            continue

        if key in {'frequency_penalty', 'presence_penalty'}:
            validated[key] = _validate_number_range(key, value, minimum=-2, maximum=2)

    return validated


def validate_no_sensitive_settings(settings: Any) -> None:
    _validate_settings_mapping(settings)


def _validate_settings_mapping(value: Any) -> None:
    if not isinstance(value, dict):
        raise AIProviderInvalidRequestError('Settings deve ser um objeto JSON.')

    for key, item in value.items():
        if isinstance(key, str) and key.lower() in SENSITIVE_SETTING_KEYS:
            raise AIProviderInvalidRequestError('Campo sensivel nao permitido em settings.')
        if isinstance(item, dict):
            _validate_settings_mapping(item)
        elif isinstance(item, list):
            for nested_item in item:
                if isinstance(nested_item, dict):
                    _validate_settings_mapping(nested_item)


def _validate_positive_int(key: str, value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise AIProviderInvalidRequestError(f'Setting OpenAI invalido: {key}.')
    return value


def _validate_number_range(key: str, value: Any, *, minimum: float, maximum: float) -> float | int:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise AIProviderInvalidRequestError(f'Setting OpenAI invalido: {key}.')

    if key == 'timeout' and value <= minimum:
        raise AIProviderInvalidRequestError(f'Setting OpenAI invalido: {key}.')

    if key != 'timeout' and value < minimum:
        raise AIProviderInvalidRequestError(f'Setting OpenAI invalido: {key}.')

    if value > maximum:
        raise AIProviderInvalidRequestError(f'Setting OpenAI invalido: {key}.')

    return value
