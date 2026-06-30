from __future__ import annotations

from contextvars import ContextVar, Token
from typing import Any

from django.http import HttpRequest, HttpResponse

_current_request: ContextVar[HttpRequest | None] = ContextVar(
    'audit_current_request',
    default=None,
)


def get_current_request() -> HttpRequest | None:
    """Retorna o request atual quando a alteracao veio de uma request HTTP."""
    return _current_request.get()


class AuditRequestMiddleware:
    """Armazena o request atual para que signals consigam registrar contexto."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        request.audit_workspace_id = self._resolve_workspace_id(request)
        token: Token[HttpRequest | None] = _current_request.set(request)
        try:
            return self.get_response(request)
        finally:
            _current_request.reset(token)

    def _resolve_workspace_id(self, request: HttpRequest) -> str:
        resolver_match = getattr(request, 'resolver_match', None)
        candidate = resolver_match.kwargs.get('workspace_id') if resolver_match else None
        if not candidate:
            candidate = request.GET.get('workspace') or request.GET.get('workspace_id')
        if not candidate and request.method in {'POST', 'PUT', 'PATCH'}:
            candidate = self._payload_value(request, 'workspace_id') or self._payload_value(
                request,
                'workspace',
            )
        return str(candidate or '')

    def _payload_value(self, request: HttpRequest, key: str) -> Any:
        data = getattr(request, 'data', None)
        if isinstance(data, dict):
            return data.get(key)
        return request.POST.get(key)
