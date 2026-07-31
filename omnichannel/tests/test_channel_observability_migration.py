from __future__ import annotations

import pytest
from django.conf import settings
from django.db import connection
from django.db.migrations.executor import MigrationExecutor


@pytest.mark.django_db(transaction=True)
def test_channel_snapshot_backfill_only_links_same_workspace() -> None:
    migration_modules = getattr(settings, 'MIGRATION_MODULES', {})
    if (
        'omnichannel' in migration_modules
        and migration_modules['omnichannel'] is None
    ):
        pytest.skip('Requer pytest --migrations; validado na suite dedicada de migration.')

    executor = MigrationExecutor(connection)
    executor.migrate([('omnichannel', '0010_aiobservabilityevent_whatsapp_channel_and_more')])
    old_apps = executor.loader.project_state(
        [('omnichannel', '0010_aiobservabilityevent_whatsapp_channel_and_more')],
    ).apps
    Workspace = old_apps.get_model('workspaces', 'Workspace')
    WhatsAppChannel = old_apps.get_model('omnichannel', 'WhatsAppChannel')
    Event = old_apps.get_model('omnichannel', 'AIObservabilityEvent')

    workspace_a = Workspace.objects.create(name='Workspace A', slug='migration-workspace-a')
    workspace_b = Workspace.objects.create(name='Workspace B', slug='migration-workspace-b')
    channel_a = WhatsAppChannel.objects.create(
        workspace=workspace_a,
        name='Canal A',
        instance_name='migration-channel-a',
    )
    channel_b = WhatsAppChannel.objects.create(
        workspace=workspace_b,
        name='Canal B',
        instance_name='migration-channel-b',
    )
    same_tenant = Event.objects.create(
        workspace=workspace_a,
        whatsapp_channel=channel_a,
        event_type='CHANNEL_CONNECTED',
        status='success',
    )
    cross_tenant = Event.objects.create(
        workspace=workspace_a,
        whatsapp_channel=channel_b,
        event_type='CHANNEL_CONNECTED',
        status='success',
    )

    executor = MigrationExecutor(connection)
    executor.migrate([('omnichannel', '0011_aiobservabilityevent_channel_id_snapshot')])
    new_apps = executor.loader.project_state(
        [('omnichannel', '0011_aiobservabilityevent_channel_id_snapshot')],
    ).apps
    MigratedEvent = new_apps.get_model('omnichannel', 'AIObservabilityEvent')

    assert MigratedEvent.objects.get(id=same_tenant.id).whatsapp_channel_id_snapshot == channel_a.id
    assert MigratedEvent.objects.get(id=cross_tenant.id).whatsapp_channel_id_snapshot is None
