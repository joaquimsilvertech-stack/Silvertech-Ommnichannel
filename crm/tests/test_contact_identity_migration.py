from __future__ import annotations

import uuid
from collections.abc import Callable, Generator
from datetime import timedelta

import pytest
from django.apps.registry import Apps
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.utils import timezone

from omnichannel.factories import WhatsAppChannelFactory
from omnichannel.models import Conversation, Message
from workspaces.factories import WorkspaceFactory

MIGRATION_BEFORE = (
    'crm',
    '0003_contact_channel_id_contact_starred_lead_assigned_to_and_more',
)
MIGRATION_AFTER = ('crm', '0004_contact_identity_constraint')


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
            WHERE slug LIKE 'contact-identity-migration-%'
        """
        cursor.execute(
            f"""
            DELETE FROM core_auditlog
            WHERE workspace_id IN ({workspace_filter})
            """,
        )
        cursor.execute(
            f"""
            DELETE FROM omnichannel_message
            WHERE conversation_id IN (
                SELECT id FROM omnichannel_conversation
                WHERE workspace_id IN ({workspace_filter})
            )
            """,
        )
        cursor.execute(
            f"""
            DELETE FROM omnichannel_conversation
            WHERE workspace_id IN ({workspace_filter})
            """,
        )
        cursor.execute(
            f"""
            DELETE FROM omnichannel_evolutionwebhookevent
            WHERE whatsapp_channel_id IN (
                SELECT id FROM omnichannel_whatsappchannel
                WHERE workspace_id IN ({workspace_filter})
            )
            """,
        )
        cursor.execute(
            f"""
            DELETE FROM omnichannel_whatsappchannel
            WHERE workspace_id IN ({workspace_filter})
            """,
        )
        cursor.execute(
            f"""
            DELETE FROM crm_contact
            WHERE workspace_id IN ({workspace_filter})
            """,
        )
        cursor.execute(
            """
            DELETE FROM workspaces_workspace
            WHERE slug LIKE 'contact-identity-migration-%'
            """,
        )


@pytest.fixture
def migrate_to(settings) -> Generator[Callable[[tuple[str, str]], Apps], None, None]:
    settings.MIGRATION_MODULES = {}
    executor = MigrationExecutor(connection)
    _record_current_schema_as_applied(executor)
    final_targets = executor.loader.graph.leaf_nodes()

    def _migrate(target: tuple[str, str]) -> Apps:
        current_executor = MigrationExecutor(connection)
        current_executor.migrate([target])
        current_executor = MigrationExecutor(connection)
        return current_executor.loader.project_state([target]).apps

    try:
        yield _migrate
    finally:
        executor = MigrationExecutor(connection)
        executor.migrate(final_targets)
        _delete_migration_test_data()


@pytest.mark.django_db(transaction=True)
def test_migration_clears_only_duplicate_identity_and_preserves_domain_relations(
    migrate_to,
) -> None:
    old_apps = migrate_to(MIGRATION_BEFORE)
    HistoricalContact = old_apps.get_model('crm', 'Contact')
    workspace = WorkspaceFactory(
        slug=f'contact-identity-migration-{uuid.uuid4().hex[:12]}',
    )
    identity = '5511777777777'
    canonical_id = uuid.UUID('00000000-0000-0000-0000-000000000101')
    tied_duplicate_id = uuid.UUID('00000000-0000-0000-0000-000000000102')
    newer_duplicate_id = uuid.UUID('00000000-0000-0000-0000-000000000103')

    for contact_id, name in (
        (tied_duplicate_id, 'Contato preservado B'),
        (canonical_id, 'Contato preservado A'),
        (newer_duplicate_id, 'Contato preservado C'),
    ):
        HistoricalContact.objects.create(
            id=contact_id,
            workspace_id=workspace.id,
            name=name,
            phone=identity,
            email=f'{contact_id.int}@example.invalid',
            channel_id=identity,
            custom_attributes={'preserved': name[-1]},
        )

    oldest_time = timezone.now() - timedelta(days=2)
    HistoricalContact.objects.filter(
        id__in=[canonical_id, tied_duplicate_id],
    ).update(created_at=oldest_time)
    HistoricalContact.objects.filter(id=newer_duplicate_id).update(
        created_at=oldest_time + timedelta(days=1),
    )
    null_contacts = [
        HistoricalContact.objects.create(
            workspace_id=workspace.id,
            name=f'Contato null {index}',
            phone='',
            channel_id=None,
        )
        for index in range(2)
    ]
    empty_contacts = [
        HistoricalContact.objects.create(
            workspace_id=workspace.id,
            name=f'Contato vazio {index}',
            phone='',
            channel_id='',
        )
        for index in range(2)
    ]

    channel = WhatsAppChannelFactory(workspace=workspace)
    conversation = Conversation.objects.create(
        workspace=workspace,
        contact_id=tied_duplicate_id,
        whatsapp_channel=channel,
        channel='whatsapp',
        status=Conversation.Status.OPEN,
    )
    message = Message.objects.create(
        conversation=conversation,
        body='Conteudo preservado apenas no banco de teste',
        direction=Message.Direction.INBOUND,
        status=Message.Status.DELIVERED,
    )
    contact_count = HistoricalContact.objects.filter(workspace_id=workspace.id).count()

    new_apps = migrate_to(MIGRATION_AFTER)
    MigratedContact = new_apps.get_model('crm', 'Contact')

    assert MigratedContact.objects.filter(workspace_id=workspace.id).count() == contact_count
    assert MigratedContact.objects.get(id=canonical_id).channel_id == identity
    assert MigratedContact.objects.get(id=tied_duplicate_id).channel_id is None
    assert MigratedContact.objects.get(id=newer_duplicate_id).channel_id is None
    assert [
        MigratedContact.objects.get(id=contact.id).channel_id for contact in null_contacts
    ] == [None, None]
    assert [
        MigratedContact.objects.get(id=contact.id).channel_id for contact in empty_contacts
    ] == ['', '']
    assert MigratedContact.objects.get(id=tied_duplicate_id).name == 'Contato preservado B'
    assert MigratedContact.objects.get(id=tied_duplicate_id).phone == identity
    conversation.refresh_from_db()
    message.refresh_from_db()
    assert conversation.contact_id == tied_duplicate_id
    assert message.conversation_id == conversation.id

    rollback_apps = migrate_to(MIGRATION_BEFORE)
    RestoredContact = rollback_apps.get_model('crm', 'Contact')
    assert RestoredContact.objects.get(id=tied_duplicate_id).channel_id is None
    assert RestoredContact.objects.get(id=newer_duplicate_id).channel_id is None
