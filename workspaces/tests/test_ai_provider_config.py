from __future__ import annotations

import importlib

import pytest
from django.apps import apps
from django.db import IntegrityError, connection, transaction

from workspaces.factories import (
    WorkspaceAIConfigFactory,
    WorkspaceAIProviderConfigFactory,
    WorkspaceFactory,
)
from workspaces.models import AIProvider, WorkspaceAIProviderConfig


@pytest.mark.django_db
def test_workspace_can_have_openai_provider_config() -> None:
    workspace = WorkspaceFactory()

    config = WorkspaceAIProviderConfigFactory(workspace=workspace)

    assert config.workspace == workspace
    assert config.provider == AIProvider.OPENAI
    assert list(workspace.ai_provider_configs.all()) == [config]


@pytest.mark.django_db
def test_workspace_can_have_openai_and_anthropic_when_only_one_is_active() -> None:
    workspace = WorkspaceFactory()
    openai_config = WorkspaceAIProviderConfigFactory(
        workspace=workspace,
        provider=AIProvider.OPENAI,
        is_active=True,
    )
    anthropic_config = WorkspaceAIProviderConfigFactory(
        workspace=workspace,
        provider=AIProvider.ANTHROPIC,
        api_key='sk-anthropic-provider-key',
        is_active=False,
    )

    assert set(
        workspace.ai_provider_configs.values_list('provider', flat=True),
    ) == {AIProvider.OPENAI, AIProvider.ANTHROPIC}
    assert openai_config.is_active is True
    assert anthropic_config.is_active is False


@pytest.mark.django_db
def test_same_workspace_cannot_have_duplicate_provider() -> None:
    workspace = WorkspaceFactory()
    WorkspaceAIProviderConfigFactory(workspace=workspace, provider=AIProvider.OPENAI)

    with pytest.raises(IntegrityError):
        with transaction.atomic():
            WorkspaceAIProviderConfigFactory(
                workspace=workspace,
                provider=AIProvider.OPENAI,
                is_active=False,
            )


@pytest.mark.django_db
def test_different_workspaces_can_have_same_provider() -> None:
    first = WorkspaceAIProviderConfigFactory(provider=AIProvider.OPENAI)
    second = WorkspaceAIProviderConfigFactory(provider=AIProvider.OPENAI)

    assert first.workspace_id != second.workspace_id
    assert first.provider == second.provider == AIProvider.OPENAI


@pytest.mark.django_db
def test_only_one_provider_can_be_active_per_workspace() -> None:
    workspace = WorkspaceFactory()
    WorkspaceAIProviderConfigFactory(
        workspace=workspace,
        provider=AIProvider.OPENAI,
        is_active=True,
    )

    with pytest.raises(IntegrityError):
        with transaction.atomic():
            WorkspaceAIProviderConfigFactory(
                workspace=workspace,
                provider=AIProvider.ANTHROPIC,
                api_key='sk-anthropic-provider-key',
                is_active=True,
            )


@pytest.mark.django_db
def test_provider_api_key_is_encrypted_at_rest_and_readable_by_orm() -> None:
    config = WorkspaceAIProviderConfigFactory(api_key='sk-provider-secret')

    config.refresh_from_db()
    assert config.api_key == 'sk-provider-secret'

    with connection.cursor() as cursor:
        cursor.execute(
            'SELECT api_key FROM workspaces_workspaceaiproviderconfig WHERE id = %s',
            [str(config.id)],
        )
        raw_value = cursor.fetchone()[0]

    assert raw_value != 'sk-provider-secret'
    assert 'sk-provider-secret' not in raw_value


@pytest.mark.django_db
def test_workspace_provider_config_is_scoped_by_workspace() -> None:
    other_config = WorkspaceAIProviderConfigFactory(api_key='sk-other-workspace-key')
    current_workspace = WorkspaceFactory()

    config = WorkspaceAIProviderConfig.objects.filter(
        workspace=current_workspace,
        provider=AIProvider.OPENAI,
        is_active=True,
    ).first()

    assert config is None
    assert other_config.workspace != current_workspace


@pytest.mark.django_db
def test_legacy_openai_config_migration_preserves_data() -> None:
    legacy_config = WorkspaceAIConfigFactory(
        openai_api_key='sk-legacy-openai-key',
        model_name='gpt-4o-mini',
        system_prompt='Prompt legado',
        is_active=True,
    )
    WorkspaceAIProviderConfig.objects.all().delete()
    migration = importlib.import_module('workspaces.migrations.0006_workspaceaiproviderconfig')

    migration.copy_legacy_openai_configs(apps, None)

    config = WorkspaceAIProviderConfig.objects.get(
        workspace=legacy_config.workspace,
        provider=AIProvider.OPENAI,
    )
    assert config.api_key == 'sk-legacy-openai-key'
    assert config.model_name == 'gpt-4o-mini'
    assert config.system_prompt == 'Prompt legado'
    assert config.is_active is True
    assert config.settings == {}


@pytest.mark.django_db
def test_legacy_openai_config_migration_tolerates_no_legacy_records() -> None:
    WorkspaceAIProviderConfig.objects.all().delete()
    migration = importlib.import_module('workspaces.migrations.0006_workspaceaiproviderconfig')

    migration.copy_legacy_openai_configs(apps, None)

    assert WorkspaceAIProviderConfig.objects.count() == 0
