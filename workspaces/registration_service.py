"""
Cadastro self-service: cria o tenant minimo (User + Workspace + Member OWNER).

A invariante "Workspace sempre nasce com OWNER" e garantida aqui, por
`transaction.atomic`, e nao por constraint global no model — o superuser continua
criando Workspace e Member em passos separados pelo Django Admin.
"""
from __future__ import annotations

from dataclasses import dataclass

from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction

from .models import Member, Workspace
from .slug_service import generate_unique_workspace_slug

User = get_user_model()

MAX_SLUG_ATTEMPTS = 5
MAX_NAME_PART_LENGTH = 150


class RegistrationError(Exception):
    """Falha de negocio no cadastro self-service."""


class EmailAlreadyRegisteredError(RegistrationError):
    """E-mail ja cadastrado (inclusive por corrida entre requisicoes concorrentes)."""


class WorkspaceSlugGenerationError(RegistrationError):
    """Nao foi possivel gerar um slug unico dentro do limite de tentativas."""


@dataclass(frozen=True)
class RegisteredAccount:
    """Entidades criadas pelo cadastro, ja commitadas."""

    user: User
    workspace: Workspace
    member: Member


def split_full_name(full_name: str) -> tuple[str, str]:
    """Divide o nome completo em first/last sem heuristica fragil."""
    parts = (full_name or '').split()
    if not parts:
        return '', ''
    first_name = parts[0][:MAX_NAME_PART_LENGTH]
    last_name = ' '.join(parts[1:])[:MAX_NAME_PART_LENGTH]
    return first_name, last_name


def register_owner_account(
    *,
    full_name: str,
    company_name: str,
    email: str,
    password: str,
) -> RegisteredAccount:
    """
    Cria User + Workspace + Member(OWNER) em uma unica transacao.

    Qualquer falha desfaz tudo: nao resta User, Workspace nem Member parcial.
    Nao provisiona instancia Evolution, nao cria WhatsAppChannel, nao envia
    e-mail e nao eleva `CustomUser.role` de plataforma (mantem o default).
    """
    normalized_email = User.objects.normalize_email((email or '').strip())
    normalized_company_name = (company_name or '').strip()
    first_name, last_name = split_full_name(full_name)

    with transaction.atomic():
        user = _create_user(
            email=normalized_email,
            password=password,
            first_name=first_name,
            last_name=last_name,
        )
        workspace = _create_workspace_with_unique_slug(normalized_company_name)
        member = Member.objects.create(
            workspace=workspace,
            user=user,
            role=Member.Role.OWNER,
        )

    return RegisteredAccount(user=user, workspace=workspace, member=member)


def _create_user(*, email: str, password: str, first_name: str, last_name: str) -> User:
    try:
        # Savepoint proprio: um e-mail duplicado vira erro de negocio tratavel
        # em vez de contaminar a transacao externa.
        with transaction.atomic():
            return User.objects.create_user(
                email=email,
                password=password,
                first_name=first_name,
                last_name=last_name,
                is_active=True,
            )
    except IntegrityError as exc:
        raise EmailAlreadyRegisteredError from exc


def _create_workspace_with_unique_slug(name: str) -> Workspace:
    for attempt in range(MAX_SLUG_ATTEMPTS):
        slug = generate_unique_workspace_slug(name, force_suffix=attempt > 0)
        try:
            with transaction.atomic():
                return Workspace.objects.create(name=name, slug=slug)
        except IntegrityError:
            # Corrida de slug: regenera com sufixo aleatorio novo.
            continue

    raise WorkspaceSlugGenerationError
