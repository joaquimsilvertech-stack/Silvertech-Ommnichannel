"""Geracao de slug unico de Workspace, reutilizavel e segura contra colisao."""
from __future__ import annotations

import secrets

from django.utils.text import slugify

from .models import Workspace

MAX_SLUG_LENGTH = 128
FALLBACK_SLUG_BASE = 'workspace'
SLUG_SUFFIX_BYTES = 4
# Reserva espaco para '-' + sufixo hex, garantindo que o slug com sufixo caiba no campo.
MAX_SLUG_BASE_LENGTH = MAX_SLUG_LENGTH - (1 + SLUG_SUFFIX_BYTES * 2)


def build_workspace_slug_base(name: str) -> str:
    """Deriva a base do slug a partir do nome da empresa, com fallback deterministico."""
    base = slugify(name or '')[:MAX_SLUG_BASE_LENGTH].strip('-')
    return base or FALLBACK_SLUG_BASE


def generate_unique_workspace_slug(name: str, *, force_suffix: bool = False) -> str:
    """
    Retorna um slug derivado de `name`, unico no momento da chamada.

    `force_suffix=True` pula a tentativa de slug limpo e ja devolve um slug com
    sufixo aleatorio; usado pelo servico de registro para re-tentar apos uma
    corrida de `IntegrityError`. A unicidade definitiva e garantida pela
    constraint do banco, nao por este helper.
    """
    base = build_workspace_slug_base(name)
    if not force_suffix and not Workspace.objects.filter(slug=base).exists():
        return base
    return f'{base}-{secrets.token_hex(SLUG_SUFFIX_BYTES)}'
