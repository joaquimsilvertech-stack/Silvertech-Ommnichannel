from __future__ import annotations

from collections.abc import Mapping
from typing import Any

SENSITIVE_FIELD_PARTS = (
    'api_key',
    'apikey',
    'authorization',
    'bearer',
    'cookie',
    'credential',
    'field_encryption_key',
    'openai_api_key',
    'password',
    'secret',
    'secret_key',
    'token',
)
MASKED_VALUE = '***'


def sanitize_sensitive_data(value: Any) -> Any:
    """Mascara valores associados a chaves sensiveis em estruturas aninhadas."""
    if isinstance(value, Mapping):
        sanitized = {}
        for key, item in value.items():
            key_text = str(key)
            sanitized[key] = (
                MASKED_VALUE
                if is_sensitive_key(key_text)
                else sanitize_sensitive_data(item)
            )
        return sanitized

    if isinstance(value, list):
        return [sanitize_sensitive_data(item) for item in value]

    if isinstance(value, tuple):
        return tuple(sanitize_sensitive_data(item) for item in value)

    return value


def is_sensitive_key(key: str) -> bool:
    normalized = key.lower().replace('-', '_')
    return any(part in normalized for part in SENSITIVE_FIELD_PARTS)


def sentry_before_send(event: dict[str, Any], hint: dict[str, Any]) -> dict[str, Any]:
    """Remove secrets de eventos enviados ao Sentry."""
    return sanitize_sensitive_data(event)
