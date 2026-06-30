from __future__ import annotations

import ipaddress
from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from django.db import models
from django.http import HttpRequest

SENSITIVE_FIELD_PARTS = (
    'password',
    'token',
    'secret',
    'api_key',
    'apikey',
    'authorization',
    'credential',
    'private_key',
)
MASKED_VALUE = '***'


def get_client_ip(request: HttpRequest | None) -> str | None:
    """Resolve o IP do cliente sem assumir confianca ampla em proxies."""
    if request is None:
        return None

    forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR', '')
    candidates = [part.strip() for part in forwarded_for.split(',') if part.strip()]
    remote_addr = request.META.get('REMOTE_ADDR')
    if remote_addr:
        candidates.append(remote_addr)

    for candidate in candidates:
        try:
            return str(ipaddress.ip_address(candidate))
        except ValueError:
            continue
    return None


def get_user_agent(request: HttpRequest | None) -> str:
    if request is None:
        return ''
    return request.META.get('HTTP_USER_AGENT', '')[:1000]


def get_request_id(request: HttpRequest | None) -> str:
    if request is None:
        return ''
    return (
        request.META.get('HTTP_X_REQUEST_ID')
        or request.META.get('HTTP_X_CORRELATION_ID')
        or ''
    )[:128]


def get_actor(request: HttpRequest | None):
    if request is None:
        return None
    user = getattr(request, 'user', None)
    if user is not None and getattr(user, 'is_authenticated', False):
        return user
    return None


def resolve_workspace(instance: models.Model):
    """Descobre o workspace do objeto auditado por caminhos explicitos."""
    model_name = instance.__class__.__name__

    if model_name == 'Workspace':
        return instance

    workspace = getattr(instance, 'workspace', None)
    if workspace is not None:
        return workspace

    contact = getattr(instance, 'contact', None)
    if contact is not None:
        return getattr(contact, 'workspace', None)

    conversation = getattr(instance, 'conversation', None)
    if conversation is not None:
        return getattr(conversation, 'workspace', None)

    return None


def serialize_instance(instance: models.Model) -> dict[str, Any]:
    """Serializa campos concretos do model com mascara para dados sensiveis."""
    data: dict[str, Any] = {}
    for field in instance._meta.concrete_fields:
        name = field.name
        value = getattr(instance, name)
        data[name] = sanitize_value(name, value)
    return data


def calculate_changes(
    before: dict[str, Any] | None,
    after: dict[str, Any] | None,
) -> dict[str, dict[str, Any]]:
    """Retorna apenas campos alterados entre dois snapshots."""
    if not before or not after:
        return {}

    changes: dict[str, dict[str, Any]] = {}
    ignored_fields = {'created_at', 'updated_at'}
    for field, old_value in before.items():
        if field in ignored_fields:
            continue
        new_value = after.get(field)
        if old_value != new_value:
            changes[field] = {
                'before': old_value,
                'after': new_value,
            }
    return changes


def sanitize_value(field_name: str, value: Any) -> Any:
    if _is_sensitive_field(field_name):
        return MASKED_VALUE

    if isinstance(value, dict):
        return {key: sanitize_value(str(key), item) for key, item in value.items()}
    if isinstance(value, list):
        return [sanitize_value(field_name, item) for item in value]
    if isinstance(value, tuple):
        return [sanitize_value(field_name, item) for item in value]
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, models.Model):
        return str(value.pk)
    return value


def short_repr(instance: models.Model) -> str:
    return str(instance)[:255]


def _is_sensitive_field(field_name: str) -> bool:
    normalized = field_name.lower()
    return any(part in normalized for part in SENSITIVE_FIELD_PARTS)
