from __future__ import annotations

import importlib
import uuid
from collections.abc import Callable, Generator

import pytest
from django.apps.registry import Apps
from django.db import connection
from django.db.migrations.executor import MigrationExecutor

MIGRATION_BEFORE = ('workspaces', '0005_workspaceaiconfig')
MIGRATION_AFTER = ('workspaces', '0006_workspaceaiproviderconfig')


def _record_current_schema_as_applied(executor: MigrationExecutor) -> None:
    """Alinha o recorder ao schema atual criado pelo pytest --no-migrations."""
    executor.recorder.ensure_schema()
    applied = executor.recorder.applied_migrations()
    for app_label, migration_name in executor.loader.graph.nodes:
        if (app_label, migration_name) not in applied:
            executor.recorder.record_applied(app_label, migration_name)


def _delete_migration_test_data() -> None:
    with connection.cursor() as cursor:
        workspace_filter = """
            SELECT id FROM workspaces_workspace
            WHERE slug LIKE 'migration-test-%'
               OR slug LIKE 'tenant-migration%'
               OR slug LIKE 'tenant-idempotent%'
               OR slug LIKE 'tenant-rollback%'
        """
        cursor.execute(
            f"""
            DELETE FROM workspaces_workspaceaiproviderconfig
            WHERE workspace_id IN ({workspace_filter})
            """,
        )
        cursor.execute(
            f"""
            DELETE FROM workspaces_workspaceaiconfig
            WHERE workspace_id IN ({workspace_filter})
            """,
        )
        cursor.execute(
            """
            DELETE FROM workspaces_workspace
            WHERE slug LIKE 'migration-test-%'
               OR slug LIKE 'tenant-migration%'
               OR slug LIKE 'tenant-idempotent%'
               OR slug LIKE 'tenant-rollback%'
            """,
        )


@pytest.fixture
def migrate_to(settings) -> Generator[Callable[[tuple[str, str]], Apps], None, None]:
    """Executa migrations reais e sempre restaura o banco ao estado atual."""
    settings.MIGRATION_MODULES = {}
    executor = MigrationExecutor(connection)
    _record_current_schema_as_applied(executor)
    final_targets = executor.loader.graph.leaf_nodes()

    def _migrate(target: tuple[str, str]) -> Apps:
        executor = MigrationExecutor(connection)
        executor.migrate([target])
        executor = MigrationExecutor(connection)
        return executor.loader.project_state([target]).apps

    try:
        yield _migrate
    finally:
        executor = MigrationExecutor(connection)
        executor.migrate(final_targets)
        _delete_migration_test_data()


def _create_workspace(Workspace, slug: str = 'tenant-migration'):
    unique_slug = f'{slug}-{uuid.uuid4().hex[:12]}'
    return Workspace.objects.create(
        name='Tenant Migration',
        slug=unique_slug,
    )


@pytest.mark.django_db(transaction=True)
def test_migration_0005_to_0006_copies_legacy_openai_config(migrate_to) -> None:
    old_apps = migrate_to(MIGRATION_BEFORE)
    Workspace = old_apps.get_model('workspaces', 'Workspace')
    WorkspaceAIConfig = old_apps.get_model('workspaces', 'WorkspaceAIConfig')

    workspace = _create_workspace(Workspace)
    WorkspaceAIConfig.objects.create(
        workspace=workspace,
        openai_api_key='sk-legacy-openai-key',
        model_name='gpt-4o-mini',
        system_prompt='Prompt legado',
        is_active=True,
    )

    new_apps = migrate_to(MIGRATION_AFTER)
    WorkspaceAIProviderConfig = new_apps.get_model('workspaces', 'WorkspaceAIProviderConfig')

    configs = list(WorkspaceAIProviderConfig.objects.filter(workspace_id=workspace.id))

    assert len(configs) == 1
    config = configs[0]
    assert config.workspace_id == workspace.id
    assert config.provider == 'openai'
    assert config.api_key == 'sk-legacy-openai-key'
    assert config.model_name == 'gpt-4o-mini'
    assert config.system_prompt == 'Prompt legado'
    assert config.is_active is True
    assert config.settings == {}


@pytest.mark.django_db(transaction=True)
def test_migration_0005_to_0006_tolerates_no_legacy_configs(migrate_to) -> None:
    old_apps = migrate_to(MIGRATION_BEFORE)
    Workspace = old_apps.get_model('workspaces', 'Workspace')

    workspace = _create_workspace(Workspace, slug='migration-test-no-legacy')

    new_apps = migrate_to(MIGRATION_AFTER)
    WorkspaceAIProviderConfig = new_apps.get_model('workspaces', 'WorkspaceAIProviderConfig')

    assert not WorkspaceAIProviderConfig.objects.filter(workspace_id=workspace.id).exists()


@pytest.mark.django_db(transaction=True)
def test_copy_legacy_openai_configs_is_logically_idempotent(migrate_to) -> None:
    old_apps = migrate_to(MIGRATION_BEFORE)
    Workspace = old_apps.get_model('workspaces', 'Workspace')
    WorkspaceAIConfig = old_apps.get_model('workspaces', 'WorkspaceAIConfig')

    workspace = _create_workspace(Workspace, slug='tenant-idempotent')
    WorkspaceAIConfig.objects.create(
        workspace=workspace,
        openai_api_key='sk-idempotent-key',
        model_name='gpt-4o-mini',
        system_prompt='Prompt idempotente',
        is_active=True,
    )

    new_apps = migrate_to(MIGRATION_AFTER)
    migration = importlib.import_module('workspaces.migrations.0006_workspaceaiproviderconfig')

    migration.copy_legacy_openai_configs(new_apps, None)
    migration.copy_legacy_openai_configs(new_apps, None)

    WorkspaceAIProviderConfig = new_apps.get_model('workspaces', 'WorkspaceAIProviderConfig')
    configs = WorkspaceAIProviderConfig.objects.filter(
        workspace_id=workspace.id,
        provider='openai',
    )

    assert configs.count() == 1
    assert configs.get().api_key == 'sk-idempotent-key'


@pytest.mark.django_db(transaction=True)
def test_reverse_migration_restores_legacy_openai_config(migrate_to) -> None:
    old_apps = migrate_to(MIGRATION_BEFORE)
    Workspace = old_apps.get_model('workspaces', 'Workspace')
    WorkspaceAIConfig = old_apps.get_model('workspaces', 'WorkspaceAIConfig')

    workspace = _create_workspace(Workspace, slug='tenant-rollback')
    WorkspaceAIConfig.objects.create(
        workspace=workspace,
        openai_api_key='sk-before-rollback',
        model_name='gpt-4o-mini',
        system_prompt='Prompt antes do rollback',
        is_active=True,
    )

    new_apps = migrate_to(MIGRATION_AFTER)
    WorkspaceAIProviderConfig = new_apps.get_model('workspaces', 'WorkspaceAIProviderConfig')
    provider_config = WorkspaceAIProviderConfig.objects.get(workspace_id=workspace.id)
    provider_config.api_key = 'sk-after-rollback'
    provider_config.model_name = 'gpt-4o-mini-updated'
    provider_config.system_prompt = 'Prompt restaurado no rollback'
    provider_config.is_active = False
    provider_config.save()

    rollback_apps = migrate_to(MIGRATION_BEFORE)
    RestoredWorkspaceAIConfig = rollback_apps.get_model('workspaces', 'WorkspaceAIConfig')
    restored = RestoredWorkspaceAIConfig.objects.get(workspace_id=workspace.id)

    assert restored.workspace_id == workspace.id
    assert restored.openai_api_key == 'sk-after-rollback'
    assert restored.model_name == 'gpt-4o-mini-updated'
    assert restored.system_prompt == 'Prompt restaurado no rollback'
    assert restored.is_active is False
