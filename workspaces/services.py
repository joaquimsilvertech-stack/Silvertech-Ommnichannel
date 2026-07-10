from __future__ import annotations

from django.db import IntegrityError, transaction

from .models import Workspace, WorkspaceAIProviderConfig


class AIProviderActivationError(Exception):
    """Erro sanitizado ao trocar o provider ativo de IA do workspace."""


def activate_ai_provider_config(
    *,
    workspace: Workspace,
    provider_config: WorkspaceAIProviderConfig,
) -> WorkspaceAIProviderConfig:
    try:
        with transaction.atomic():
            Workspace.objects.select_for_update().get(id=workspace.id)
            configs = WorkspaceAIProviderConfig.objects.select_for_update().filter(
                workspace_id=workspace.id,
            )
            target = configs.get(id=provider_config.id)
            if target.workspace_id != workspace.id:
                raise AIProviderActivationError('Configuracao invalida para este workspace.')

            configs.exclude(id=target.id).filter(is_active=True).update(is_active=False)

            if not target.is_active:
                target.is_active = True
                target.save(update_fields=['is_active', 'updated_at'])

            return target
    except WorkspaceAIProviderConfig.DoesNotExist as exc:
        raise AIProviderActivationError('Configuracao invalida para este workspace.') from exc
    except IntegrityError as exc:
        raise AIProviderActivationError('Nao foi possivel ativar o provider de IA.') from exc


def deactivate_ai_provider_config(
    *,
    workspace: Workspace,
    provider_config: WorkspaceAIProviderConfig,
) -> WorkspaceAIProviderConfig:
    try:
        with transaction.atomic():
            Workspace.objects.select_for_update().get(id=workspace.id)
            target = WorkspaceAIProviderConfig.objects.select_for_update().get(
                id=provider_config.id,
                workspace_id=workspace.id,
            )

            if target.is_active:
                target.is_active = False
                target.save(update_fields=['is_active', 'updated_at'])

            return target
    except WorkspaceAIProviderConfig.DoesNotExist as exc:
        raise AIProviderActivationError('Configuracao invalida para este workspace.') from exc
    except IntegrityError as exc:
        raise AIProviderActivationError('Nao foi possivel desativar o provider de IA.') from exc
