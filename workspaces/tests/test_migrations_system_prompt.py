from __future__ import annotations

import uuid
from collections.abc import Callable, Generator

import pytest
from django.apps.registry import Apps
from django.db import connection
from django.db.migrations.executor import MigrationExecutor

MIGRATION_BEFORE = ('workspaces', '0006_workspaceaiproviderconfig')
MIGRATION_AFTER = ('workspaces', '0007_consolidate_system_prompt')


def _record_current_schema_as_applied(executor: MigrationExecutor) -> None:
    executor.recorder.ensure_schema()
    applied = executor.recorder.applied_migrations()
    for app_label, migration_name in executor.loader.graph.nodes:
        if (app_label, migration_name) not in applied:
            executor.recorder.record_applied(app_label, migration_name)


def _delete_migration_test_data() -> None:
    with connection.cursor() as cursor:
        workspace_filter = """
            SELECT id FROM workspaces_workspace
            WHERE slug LIKE 'system-prompt-migration-%'
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
            WHERE slug LIKE 'system-prompt-migration-%'
            """,
        )


@pytest.fixture
def migrate_to(settings) -> Generator[Callable[[tuple[str, str]], Apps], None, None]:
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


def _create_workspace(Workspace, *, prompt: str | None, slug_prefix: str = 'default'):
    return Workspace.objects.create(
        name=f'System Prompt Migration {slug_prefix}',
        slug=f'system-prompt-migration-{slug_prefix}-{uuid.uuid4().hex[:12]}',
        ai_system_prompt=prompt,
    )


def _create_provider_config(
    WorkspaceAIProviderConfig,
    *,
    workspace,
    provider: str = 'openai',
    prompt: str = '',
    is_active: bool = True,
):
    return WorkspaceAIProviderConfig.objects.create(
        workspace=workspace,
        provider=provider,
        api_key=f'sk-{provider}-{uuid.uuid4().hex[:8]}',
        model_name=f'{provider}-test-model',
        system_prompt=prompt,
        is_active=is_active,
        settings={},
    )


@pytest.mark.django_db(transaction=True)
def test_copies_workspace_prompt_when_provider_prompt_is_empty(migrate_to) -> None:
    old_apps = migrate_to(MIGRATION_BEFORE)
    Workspace = old_apps.get_model('workspaces', 'Workspace')
    WorkspaceAIProviderConfig = old_apps.get_model('workspaces', 'WorkspaceAIProviderConfig')

    workspace = _create_workspace(Workspace, prompt='Prompt legado do workspace', slug_prefix='copy')
    _create_provider_config(WorkspaceAIProviderConfig, workspace=workspace, prompt='')

    new_apps = migrate_to(MIGRATION_AFTER)
    MigratedProviderConfig = new_apps.get_model('workspaces', 'WorkspaceAIProviderConfig')

    config = MigratedProviderConfig.objects.get(workspace_id=workspace.id, provider='openai')
    assert config.system_prompt == 'Prompt legado do workspace'


@pytest.mark.django_db(transaction=True)
def test_preserves_existing_provider_prompt(migrate_to) -> None:
    old_apps = migrate_to(MIGRATION_BEFORE)
    Workspace = old_apps.get_model('workspaces', 'Workspace')
    WorkspaceAIProviderConfig = old_apps.get_model('workspaces', 'WorkspaceAIProviderConfig')

    workspace = _create_workspace(Workspace, prompt='Prompt legado que nao deve sobrescrever', slug_prefix='preserve')
    _create_provider_config(
        WorkspaceAIProviderConfig,
        workspace=workspace,
        prompt='Prompt oficial do provider',
    )

    new_apps = migrate_to(MIGRATION_AFTER)
    MigratedProviderConfig = new_apps.get_model('workspaces', 'WorkspaceAIProviderConfig')

    config = MigratedProviderConfig.objects.get(workspace_id=workspace.id, provider='openai')
    assert config.system_prompt == 'Prompt oficial do provider'


@pytest.mark.django_db(transaction=True)
def test_empty_workspace_prompt_does_not_change_provider_prompt(migrate_to) -> None:
    old_apps = migrate_to(MIGRATION_BEFORE)
    Workspace = old_apps.get_model('workspaces', 'Workspace')
    WorkspaceAIProviderConfig = old_apps.get_model('workspaces', 'WorkspaceAIProviderConfig')

    workspace = _create_workspace(Workspace, prompt='', slug_prefix='empty-workspace')
    _create_provider_config(WorkspaceAIProviderConfig, workspace=workspace, prompt='')

    new_apps = migrate_to(MIGRATION_AFTER)
    MigratedProviderConfig = new_apps.get_model('workspaces', 'WorkspaceAIProviderConfig')

    config = MigratedProviderConfig.objects.get(workspace_id=workspace.id, provider='openai')
    assert config.system_prompt == ''


@pytest.mark.django_db(transaction=True)
def test_workspace_without_provider_config_is_not_created(migrate_to) -> None:
    old_apps = migrate_to(MIGRATION_BEFORE)
    Workspace = old_apps.get_model('workspaces', 'Workspace')

    workspace = _create_workspace(Workspace, prompt='Prompt sem provider', slug_prefix='no-provider')

    new_apps = migrate_to(MIGRATION_AFTER)
    MigratedWorkspace = new_apps.get_model('workspaces', 'Workspace')
    MigratedProviderConfig = new_apps.get_model('workspaces', 'WorkspaceAIProviderConfig')

    migrated_workspace = MigratedWorkspace.objects.get(id=workspace.id)
    assert migrated_workspace.ai_system_prompt == 'Prompt sem provider'
    assert not MigratedProviderConfig.objects.filter(workspace_id=workspace.id).exists()


@pytest.mark.django_db(transaction=True)
def test_active_non_openai_provider_has_priority_over_inactive_openai(migrate_to) -> None:
    old_apps = migrate_to(MIGRATION_BEFORE)
    Workspace = old_apps.get_model('workspaces', 'Workspace')
    WorkspaceAIProviderConfig = old_apps.get_model('workspaces', 'WorkspaceAIProviderConfig')

    workspace = _create_workspace(Workspace, prompt='Prompt para provider ativo', slug_prefix='active-provider')
    _create_provider_config(
        WorkspaceAIProviderConfig,
        workspace=workspace,
        provider='openai',
        prompt='',
        is_active=False,
    )
    _create_provider_config(
        WorkspaceAIProviderConfig,
        workspace=workspace,
        provider='anthropic',
        prompt='',
        is_active=True,
    )

    new_apps = migrate_to(MIGRATION_AFTER)
    MigratedProviderConfig = new_apps.get_model('workspaces', 'WorkspaceAIProviderConfig')

    openai_config = MigratedProviderConfig.objects.get(workspace_id=workspace.id, provider='openai')
    active_config = MigratedProviderConfig.objects.get(workspace_id=workspace.id, provider='anthropic')
    assert openai_config.system_prompt == ''
    assert active_config.system_prompt == 'Prompt para provider ativo'


@pytest.mark.django_db(transaction=True)
def test_openai_provider_is_used_when_no_provider_is_active(migrate_to) -> None:
    old_apps = migrate_to(MIGRATION_BEFORE)
    Workspace = old_apps.get_model('workspaces', 'Workspace')
    WorkspaceAIProviderConfig = old_apps.get_model('workspaces', 'WorkspaceAIProviderConfig')

    workspace = _create_workspace(Workspace, prompt='Prompt para OpenAI inativo', slug_prefix='openai-fallback')
    _create_provider_config(
        WorkspaceAIProviderConfig,
        workspace=workspace,
        provider='openai',
        prompt='',
        is_active=False,
    )

    new_apps = migrate_to(MIGRATION_AFTER)
    MigratedProviderConfig = new_apps.get_model('workspaces', 'WorkspaceAIProviderConfig')

    config = MigratedProviderConfig.objects.get(workspace_id=workspace.id, provider='openai')
    assert config.system_prompt == 'Prompt para OpenAI inativo'


@pytest.mark.django_db(transaction=True)
def test_workspace_prompts_do_not_cross_tenants(migrate_to) -> None:
    old_apps = migrate_to(MIGRATION_BEFORE)
    Workspace = old_apps.get_model('workspaces', 'Workspace')
    WorkspaceAIProviderConfig = old_apps.get_model('workspaces', 'WorkspaceAIProviderConfig')

    first_workspace = _create_workspace(Workspace, prompt='Prompt A', slug_prefix='tenant-a')
    second_workspace = _create_workspace(Workspace, prompt='Prompt B', slug_prefix='tenant-b')
    _create_provider_config(WorkspaceAIProviderConfig, workspace=first_workspace, prompt='')
    _create_provider_config(WorkspaceAIProviderConfig, workspace=second_workspace, prompt='')

    new_apps = migrate_to(MIGRATION_AFTER)
    MigratedProviderConfig = new_apps.get_model('workspaces', 'WorkspaceAIProviderConfig')

    first_config = MigratedProviderConfig.objects.get(workspace_id=first_workspace.id)
    second_config = MigratedProviderConfig.objects.get(workspace_id=second_workspace.id)
    assert first_config.system_prompt == 'Prompt A'
    assert second_config.system_prompt == 'Prompt B'


@pytest.mark.django_db(transaction=True)
def test_reverse_migration_preserves_existing_workspace_prompt(migrate_to) -> None:
    old_apps = migrate_to(MIGRATION_BEFORE)
    Workspace = old_apps.get_model('workspaces', 'Workspace')
    WorkspaceAIProviderConfig = old_apps.get_model('workspaces', 'WorkspaceAIProviderConfig')

    workspace = _create_workspace(Workspace, prompt='Prompt legado preservado', slug_prefix='reverse-preserve')
    _create_provider_config(
        WorkspaceAIProviderConfig,
        workspace=workspace,
        prompt='Prompt provider nao deve sobrescrever',
    )

    migrate_to(MIGRATION_AFTER)
    rollback_apps = migrate_to(MIGRATION_BEFORE)
    RestoredWorkspace = rollback_apps.get_model('workspaces', 'Workspace')

    restored_workspace = RestoredWorkspace.objects.get(id=workspace.id)
    assert restored_workspace.ai_system_prompt == 'Prompt legado preservado'


@pytest.mark.django_db(transaction=True)
def test_reverse_migration_copies_provider_prompt_only_when_workspace_prompt_is_empty(migrate_to) -> None:
    new_apps = migrate_to(MIGRATION_AFTER)
    Workspace = new_apps.get_model('workspaces', 'Workspace')
    WorkspaceAIProviderConfig = new_apps.get_model('workspaces', 'WorkspaceAIProviderConfig')

    workspace = _create_workspace(Workspace, prompt='', slug_prefix='reverse-copy')
    _create_provider_config(
        WorkspaceAIProviderConfig,
        workspace=workspace,
        prompt='Prompt provider para rollback',
    )

    rollback_apps = migrate_to(MIGRATION_BEFORE)
    RestoredWorkspace = rollback_apps.get_model('workspaces', 'Workspace')

    restored_workspace = RestoredWorkspace.objects.get(id=workspace.id)
    assert restored_workspace.ai_system_prompt == 'Prompt provider para rollback'
