from __future__ import annotations

import inspect
from unittest.mock import patch

import pytest
from django.db import IntegrityError

from workspaces.factories import WorkspaceAIProviderConfigFactory, WorkspaceFactory
from workspaces.models import AIProvider, WorkspaceAIProviderConfig
from workspaces.services import (
    AIProviderActivationError,
    activate_ai_provider_config,
    deactivate_ai_provider_config,
)


@pytest.mark.django_db
def test_activate_ai_provider_config_activates_target() -> None:
    config = WorkspaceAIProviderConfigFactory(is_active=False)

    activated = activate_ai_provider_config(
        workspace=config.workspace,
        provider_config=config,
    )

    activated.refresh_from_db()
    assert activated.is_active is True


@pytest.mark.django_db
def test_activate_ai_provider_config_deactivates_other_provider_in_same_workspace() -> None:
    workspace = WorkspaceFactory()
    active_config = WorkspaceAIProviderConfigFactory(
        workspace=workspace,
        provider=AIProvider.ANTHROPIC,
        is_active=True,
    )
    target = WorkspaceAIProviderConfigFactory(
        workspace=workspace,
        provider=AIProvider.OPENAI,
        is_active=False,
    )

    activate_ai_provider_config(workspace=workspace, provider_config=target)

    active_config.refresh_from_db()
    target.refresh_from_db()
    assert active_config.is_active is False
    assert target.is_active is True
    assert WorkspaceAIProviderConfig.objects.filter(workspace=workspace, is_active=True).count() == 1


@pytest.mark.django_db
def test_activate_ai_provider_config_does_not_affect_other_workspace() -> None:
    other_active = WorkspaceAIProviderConfigFactory(is_active=True)
    target = WorkspaceAIProviderConfigFactory(is_active=False)

    activate_ai_provider_config(workspace=target.workspace, provider_config=target)

    other_active.refresh_from_db()
    assert other_active.is_active is True


@pytest.mark.django_db
def test_activate_ai_provider_config_is_idempotent_for_active_provider() -> None:
    config = WorkspaceAIProviderConfigFactory(is_active=True)

    activated = activate_ai_provider_config(
        workspace=config.workspace,
        provider_config=config,
    )

    activated.refresh_from_db()
    assert activated.is_active is True


def test_activate_ai_provider_config_uses_atomic_and_select_for_update() -> None:
    source = inspect.getsource(activate_ai_provider_config)

    assert 'transaction.atomic' in source
    assert 'select_for_update' in source


@pytest.mark.django_db
def test_activate_ai_provider_config_handles_integrity_error_safely() -> None:
    config = WorkspaceAIProviderConfigFactory(is_active=False)

    with patch.object(WorkspaceAIProviderConfig, 'save', side_effect=IntegrityError('raw sql leak')):
        with pytest.raises(AIProviderActivationError) as exc_info:
            activate_ai_provider_config(workspace=config.workspace, provider_config=config)

    assert 'raw sql leak' not in str(exc_info.value)


@pytest.mark.django_db
def test_deactivate_ai_provider_config_deactivates_active_provider() -> None:
    config = WorkspaceAIProviderConfigFactory(is_active=True)

    deactivated = deactivate_ai_provider_config(
        workspace=config.workspace,
        provider_config=config,
    )

    deactivated.refresh_from_db()
    assert deactivated.is_active is False


@pytest.mark.django_db
def test_deactivate_ai_provider_config_is_idempotent_for_inactive_provider() -> None:
    config = WorkspaceAIProviderConfigFactory(is_active=False)

    deactivated = deactivate_ai_provider_config(
        workspace=config.workspace,
        provider_config=config,
    )

    deactivated.refresh_from_db()
    assert deactivated.is_active is False


@pytest.mark.django_db
def test_deactivate_ai_provider_config_does_not_delete_api_key_or_settings() -> None:
    config = WorkspaceAIProviderConfigFactory(
        api_key='sk-service-secret-key',
        settings={'temperature': 0.2},
        is_active=True,
    )

    deactivate_ai_provider_config(workspace=config.workspace, provider_config=config)

    config.refresh_from_db()
    assert config.api_key == 'sk-service-secret-key'
    assert config.settings == {'temperature': 0.2}


@pytest.mark.django_db
def test_deactivate_ai_provider_config_does_not_affect_other_workspace() -> None:
    other_active = WorkspaceAIProviderConfigFactory(is_active=True)
    config = WorkspaceAIProviderConfigFactory(is_active=True)

    deactivate_ai_provider_config(workspace=config.workspace, provider_config=config)

    other_active.refresh_from_db()
    assert other_active.is_active is True


def test_deactivate_ai_provider_config_uses_atomic_and_select_for_update() -> None:
    source = inspect.getsource(deactivate_ai_provider_config)

    assert 'transaction.atomic' in source
    assert 'select_for_update' in source
