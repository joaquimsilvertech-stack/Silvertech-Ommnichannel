from __future__ import annotations

import logging

from django.db import IntegrityError, transaction

from omnichannel.ai.connection_test import test_ai_provider_connection
from omnichannel.ai.registry import is_provider_supported

from .models import Workspace, WorkspaceAIProviderConfig

logger = logging.getLogger(__name__)


class AIProviderActivationError(Exception):
    """Erro sanitizado ao trocar o provider ativo de IA do workspace."""


class AIProviderCredentialError(Exception):
    """Erro sanitizado ao substituir ou revogar credenciais de IA."""

    def __init__(self, message: str, *, error_code: str = 'PROVIDER_ERROR') -> None:
        super().__init__(message)
        self.error_code = error_code


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


def replace_ai_provider_credentials(
    *,
    workspace: Workspace,
    provider_config: WorkspaceAIProviderConfig,
    api_key: str,
) -> WorkspaceAIProviderConfig:
    if provider_config.workspace_id != workspace.id:
        _log_credential_event(
            provider_config=provider_config,
            action='replace_credentials',
            success=False,
            error_code='PROVIDER_ERROR',
        )
        raise AIProviderCredentialError(
            'Configuracao invalida para este workspace.',
            error_code='PROVIDER_ERROR',
        )

    if not is_provider_supported(provider_config.provider):
        _log_credential_event(
            provider_config=provider_config,
            action='replace_credentials',
            success=False,
            error_code='UNSUPPORTED_PROVIDER',
        )
        raise AIProviderCredentialError(
            'Este provedor ainda nao possui adapter ativo.',
            error_code='UNSUPPORTED_PROVIDER',
        )

    result = test_ai_provider_connection(
        provider_config=provider_config,
        api_key_override=api_key,
    )
    if not result.success:
        _log_credential_event(
            provider_config=provider_config,
            action='replace_credentials',
            success=False,
            error_code=result.error_code or 'PROVIDER_ERROR',
        )
        raise AIProviderCredentialError(
            result.message,
            error_code=result.error_code or 'PROVIDER_ERROR',
        )

    try:
        with transaction.atomic():
            target = WorkspaceAIProviderConfig.objects.select_for_update().get(
                id=provider_config.id,
                workspace_id=workspace.id,
            )
            target.api_key = api_key
            target.save(update_fields=['api_key', 'updated_at'])
            _log_credential_event(
                provider_config=target,
                action='replace_credentials',
                success=True,
            )
            return target
    except WorkspaceAIProviderConfig.DoesNotExist as exc:
        _log_credential_event(
            provider_config=provider_config,
            action='replace_credentials',
            success=False,
            error_code='PROVIDER_ERROR',
            exception_type=type(exc).__name__,
        )
        raise AIProviderCredentialError(
            'Configuracao invalida para este workspace.',
            error_code='PROVIDER_ERROR',
        ) from exc
    except IntegrityError as exc:
        _log_credential_event(
            provider_config=provider_config,
            action='replace_credentials',
            success=False,
            error_code='PROVIDER_ERROR',
            exception_type=type(exc).__name__,
        )
        raise AIProviderCredentialError(
            'Nao foi possivel substituir a credencial do provider de IA.',
            error_code='PROVIDER_ERROR',
        ) from exc


def revoke_ai_provider_credentials(
    *,
    workspace: Workspace,
    provider_config: WorkspaceAIProviderConfig,
) -> WorkspaceAIProviderConfig:
    try:
        with transaction.atomic():
            target = WorkspaceAIProviderConfig.objects.select_for_update().get(
                id=provider_config.id,
                workspace_id=workspace.id,
            )
            changed_fields = []
            if target.api_key:
                target.api_key = ''
                changed_fields.append('api_key')
            if target.is_active:
                target.is_active = False
                changed_fields.append('is_active')

            if changed_fields:
                target.save(update_fields=[*changed_fields, 'updated_at'])
                _log_credential_event(
                    provider_config=target,
                    action='revoke_credentials',
                    success=True,
                    deactivated_by_revoke='is_active' in changed_fields,
                    idempotent=False,
                )
            else:
                _log_credential_event(
                    provider_config=target,
                    action='revoke_credentials',
                    success=True,
                    deactivated_by_revoke=False,
                    idempotent=True,
                )

            return target
    except WorkspaceAIProviderConfig.DoesNotExist as exc:
        _log_credential_event(
            provider_config=provider_config,
            action='revoke_credentials',
            success=False,
            error_code='PROVIDER_ERROR',
            exception_type=type(exc).__name__,
        )
        raise AIProviderCredentialError(
            'Configuracao invalida para este workspace.',
            error_code='PROVIDER_ERROR',
        ) from exc
    except IntegrityError as exc:
        _log_credential_event(
            provider_config=provider_config,
            action='revoke_credentials',
            success=False,
            error_code='PROVIDER_ERROR',
            exception_type=type(exc).__name__,
        )
        raise AIProviderCredentialError(
            'Nao foi possivel revogar a credencial do provider de IA.',
            error_code='PROVIDER_ERROR',
        ) from exc


def _log_credential_event(
    *,
    provider_config: WorkspaceAIProviderConfig,
    action: str,
    success: bool,
    error_code: str | None = None,
    exception_type: str | None = None,
    deactivated_by_revoke: bool | None = None,
    idempotent: bool | None = None,
) -> None:
    extra = {
        'workspace_id': str(provider_config.workspace_id),
        'provider_config_id': str(provider_config.id),
        'provider': provider_config.provider,
        'model_name': provider_config.model_name,
        'action': action,
        'success': success,
    }
    if error_code:
        extra['error_code'] = error_code
    if exception_type:
        extra['exception_type'] = exception_type
    if deactivated_by_revoke is not None:
        extra['deactivated_by_revoke'] = deactivated_by_revoke
    if idempotent is not None:
        extra['idempotent'] = idempotent

    if success:
        logger.info('Operacao de credencial de IA concluida', extra=extra)
    else:
        logger.warning('Operacao de credencial de IA falhou', extra=extra)
