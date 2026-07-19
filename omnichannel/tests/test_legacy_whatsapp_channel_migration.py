from __future__ import annotations

import inspect
from io import StringIO
from uuid import UUID, uuid4
from unittest.mock import patch

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import override_settings

import omnichannel.legacy_channel_migration as migration_service
from crm.models import Contact
from omnichannel.factories import (
    ConversationFactory,
    MessageFactory,
    WhatsAppChannelFactory,
)
from omnichannel.legacy_channel_migration import LegacyChannelMigrationError
from omnichannel.models import Conversation, Message, WhatsAppChannel
from omnichannel.services import send_whatsapp_message
from workspaces.factories import WorkspaceFactory

pytestmark = pytest.mark.django_db


def _run_command(workspace_id: UUID | str, **options: object) -> str:
    output = StringIO()
    call_command(
        'migrate_legacy_whatsapp_channel',
        workspace_id=str(workspace_id),
        stdout=output,
        **options,
    )
    return output.getvalue()


@pytest.mark.parametrize('workspace_id', ['invalid-uuid', ''])
def test_invalid_workspace_id_raises_safe_command_error(workspace_id: str) -> None:
    with pytest.raises(CommandError, match='UUID valido'):
        _run_command(workspace_id, instance_name='legacy-invalid-workspace')


def test_missing_workspace_raises_command_error() -> None:
    with pytest.raises(CommandError, match='Workspace informado nao existe'):
        _run_command(uuid4(), instance_name='legacy-missing-workspace')


@override_settings(EVOLUTION_INSTANCE_NAME='')
def test_missing_instance_name_and_setting_raises_safe_error() -> None:
    with pytest.raises(CommandError, match='EVOLUTION_INSTANCE_NAME') as exc_info:
        _run_command(WorkspaceFactory().id)

    assert 'EVOLUTION_API_KEY' not in str(exc_info.value)


@override_settings(EVOLUTION_INSTANCE_NAME=' legacy-from-settings ')
def test_first_run_uses_setting_and_creates_safe_disconnected_channel() -> None:
    workspace = WorkspaceFactory()

    output = _run_command(workspace.id)

    channel = WhatsAppChannel.objects.get(workspace=workspace)
    assert channel.provider == WhatsAppChannel.Provider.EVOLUTION
    assert channel.status == WhatsAppChannel.Status.DISCONNECTED
    assert channel.name == 'WhatsApp legado'
    assert channel.instance_name == 'legacy-from-settings'
    assert channel.instance_id == ''
    assert channel.instance_token == ''
    assert channel.webhook_secret == ''
    assert channel.phone_number == ''
    assert channel.connected_at is None
    assert channel.last_connection_update_at is None
    assert channel.last_error_code == ''
    assert channel.webhook_public_id is not None
    assert 'Canal: criado' in output


@override_settings(EVOLUTION_INSTANCE_NAME='global-instance-unchanged')
def test_explicit_instance_and_channel_name_are_trimmed_without_changing_settings(
    settings,
) -> None:
    workspace = WorkspaceFactory()

    _run_command(
        workspace.id,
        instance_name=' explicit-instance ',
        channel_name=' Canal legado controlado ',
    )

    channel = WhatsAppChannel.objects.get(workspace=workspace)
    assert channel.instance_name == 'explicit-instance'
    assert channel.name == 'Canal legado controlado'
    assert settings.EVOLUTION_INSTANCE_NAME == 'global-instance-unchanged'


@pytest.mark.parametrize(
    ('options', 'error_fragment'),
    [
        ({'instance_name': 'x' * 129}, 'instance_name excede'),
        ({'instance_name': 'valid-instance', 'channel_name': ' '}, 'name nao pode'),
        (
            {'instance_name': 'valid-instance', 'channel_name': 'x' * 129},
            'name excede',
        ),
    ],
)
def test_instance_and_channel_names_are_validated(
    options: dict[str, object],
    error_fragment: str,
) -> None:
    with pytest.raises(CommandError, match=error_fragment):
        _run_command(WorkspaceFactory().id, **options)


def test_migration_associates_all_whatsapp_statuses_and_isolates_scope() -> None:
    workspace = WorkspaceFactory()
    other_workspace = WorkspaceFactory()
    open_conversation = ConversationFactory(
        workspace=workspace,
        status=Conversation.Status.OPEN,
    )
    closed_conversation = ConversationFactory(
        workspace=workspace,
        status=Conversation.Status.CLOSED,
    )
    pending_conversation = ConversationFactory(
        workspace=workspace,
        status=Conversation.Status.PENDING,
    )
    other_workspace_conversation = ConversationFactory(workspace=other_workspace)
    non_whatsapp_conversation = ConversationFactory(workspace=workspace, channel='email')
    existing_channel = WhatsAppChannelFactory(
        workspace=workspace,
        name='Canal ja associado',
    )
    already_associated = ConversationFactory(
        workspace=workspace,
        whatsapp_channel=existing_channel,
    )

    _run_command(workspace.id, instance_name='legacy-scope-instance')

    migrated_channel = WhatsAppChannel.objects.get(
        instance_name='legacy-scope-instance',
    )
    for conversation in (open_conversation, closed_conversation, pending_conversation):
        conversation.refresh_from_db()
        assert conversation.whatsapp_channel == migrated_channel

    other_workspace_conversation.refresh_from_db()
    non_whatsapp_conversation.refresh_from_db()
    already_associated.refresh_from_db()
    assert other_workspace_conversation.whatsapp_channel is None
    assert non_whatsapp_conversation.whatsapp_channel is None
    assert already_associated.whatsapp_channel == existing_channel


def test_migration_preserves_contact_conversation_and_message_data() -> None:
    workspace = WorkspaceFactory()
    conversation = ConversationFactory(
        workspace=workspace,
        status=Conversation.Status.CLOSED,
    )
    contact = conversation.contact
    message = MessageFactory(
        conversation=conversation,
        body='Mensagem historica que deve permanecer intacta',
        direction=Message.Direction.OUTBOUND,
        status=Message.Status.SENT,
        external_id='evolution-message-123',
    )
    conversation_updated_at = conversation.updated_at

    _run_command(workspace.id, instance_name='legacy-preservation-instance')

    contact.refresh_from_db()
    conversation.refresh_from_db()
    message.refresh_from_db()
    assert Contact.objects.filter(pk=contact.pk).exists()
    assert Conversation.objects.filter(pk=conversation.pk).exists()
    assert Message.objects.filter(pk=message.pk).exists()
    assert conversation.status == Conversation.Status.CLOSED
    assert conversation.updated_at == conversation_updated_at
    assert message.body == 'Mensagem historica que deve permanecer intacta'
    assert message.direction == Message.Direction.OUTBOUND
    assert message.status == Message.Status.SENT
    assert message.external_id == 'evolution-message-123'


def test_repeated_migration_is_idempotent_and_picks_up_new_conversation() -> None:
    workspace = WorkspaceFactory()
    first_conversation = ConversationFactory(workspace=workspace)

    _run_command(workspace.id, instance_name='legacy-idempotent-instance')
    second_output = _run_command(
        workspace.id,
        instance_name='legacy-idempotent-instance',
    )

    assert WhatsAppChannel.objects.filter(workspace=workspace).count() == 1
    assert 'Canal: reutilizado' in second_output
    assert 'Conversas elegiveis: 0' in second_output
    assert 'Conversas associadas: 0' in second_output

    new_conversation = ConversationFactory(workspace=workspace)
    third_output = _run_command(
        workspace.id,
        instance_name='legacy-idempotent-instance',
    )

    channel = WhatsAppChannel.objects.get(workspace=workspace)
    first_conversation.refresh_from_db()
    new_conversation.refresh_from_db()
    assert first_conversation.whatsapp_channel == channel
    assert new_conversation.whatsapp_channel == channel
    assert 'Conversas associadas: 1' in third_output


def test_existing_channel_is_reused_without_overwriting_configuration() -> None:
    workspace = WorkspaceFactory()
    channel = WhatsAppChannelFactory(
        workspace=workspace,
        name='Nome original',
        instance_name='legacy-reused-instance',
        status=WhatsAppChannel.Status.CONNECTED,
        instance_id='remote-instance-id',
        instance_token='existing-instance-token',
        webhook_secret='existing-webhook-secret',
        phone_number='5511888888888',
        last_error_code='PREVIOUS_ERROR',
    )
    conversation = ConversationFactory(workspace=workspace)

    output = _run_command(
        workspace.id,
        instance_name='legacy-reused-instance',
        channel_name='Nome que nao deve sobrescrever',
    )

    channel.refresh_from_db()
    conversation.refresh_from_db()
    assert channel.name == 'Nome original'
    assert channel.status == WhatsAppChannel.Status.CONNECTED
    assert channel.instance_id == 'remote-instance-id'
    assert channel.instance_token == 'existing-instance-token'
    assert channel.webhook_secret == 'existing-webhook-secret'
    assert channel.phone_number == '5511888888888'
    assert channel.last_error_code == 'PREVIOUS_ERROR'
    assert conversation.whatsapp_channel == channel
    assert 'Canal: reutilizado' in output


def test_cross_tenant_instance_conflict_aborts_without_partial_changes() -> None:
    workspace = WorkspaceFactory()
    other_channel = WhatsAppChannelFactory(instance_name='shared-legacy-instance')
    conversation = ConversationFactory(workspace=workspace)
    channel_count = WhatsAppChannel.objects.count()

    with pytest.raises(CommandError, match='outro workspace'):
        _run_command(workspace.id, instance_name='shared-legacy-instance')

    conversation.refresh_from_db()
    other_channel.refresh_from_db()
    assert conversation.whatsapp_channel is None
    assert WhatsAppChannel.objects.count() == channel_count
    assert other_channel.workspace_id != workspace.id


def test_channel_name_conflict_is_detected_in_dry_run_without_partial_changes() -> None:
    workspace = WorkspaceFactory()
    existing = WhatsAppChannelFactory(
        workspace=workspace,
        name='WhatsApp legado',
        instance_name='different-instance',
    )
    conversation = ConversationFactory(workspace=workspace)

    with pytest.raises(CommandError, match='outra instancia'):
        _run_command(
            workspace.id,
            instance_name='new-instance',
            dry_run=True,
        )

    conversation.refresh_from_db()
    assert conversation.whatsapp_channel is None
    assert list(WhatsAppChannel.objects.filter(workspace=workspace)) == [existing]


def test_dry_run_reports_plan_without_creating_channel_or_associations() -> None:
    workspace = WorkspaceFactory()
    conversations = [
        ConversationFactory(workspace=workspace),
        ConversationFactory(workspace=workspace),
    ]

    output = _run_command(
        workspace.id,
        instance_name='legacy-dry-run-instance',
        dry_run=True,
    )

    assert not WhatsAppChannel.objects.filter(
        instance_name='legacy-dry-run-instance',
    ).exists()
    assert all(
        Conversation.objects.get(pk=conversation.pk).whatsapp_channel is None
        for conversation in conversations
    )
    assert 'Canal: seria criado' in output
    assert 'Conversas elegiveis: 2' in output
    assert 'Conversas associadas: 0' in output
    assert 'Dry-run: sim' in output


def test_dry_run_reuses_existing_channel_without_mutating_it_or_conversation() -> None:
    workspace = WorkspaceFactory()
    channel = WhatsAppChannelFactory(
        workspace=workspace,
        instance_name='legacy-existing-dry-run',
        status=WhatsAppChannel.Status.CONNECTED,
    )
    conversation = ConversationFactory(workspace=workspace)

    output = _run_command(
        workspace.id,
        instance_name='legacy-existing-dry-run',
        dry_run=True,
    )

    channel.refresh_from_db()
    conversation.refresh_from_db()
    assert channel.status == WhatsAppChannel.Status.CONNECTED
    assert conversation.whatsapp_channel is None
    assert 'Canal: reutilizado' in output
    assert 'Conversas elegiveis: 1' in output


def test_rollback_unlinks_conversation_and_preserves_all_domain_data() -> None:
    workspace = WorkspaceFactory()
    conversation = ConversationFactory(workspace=workspace)
    contact = conversation.contact
    message = MessageFactory(
        conversation=conversation,
        body='Mensagem preservada no rollback',
        external_id='rollback-external-id',
    )
    conversation_updated_at = conversation.updated_at
    _run_command(workspace.id, instance_name='legacy-rollback-instance')
    channel = WhatsAppChannel.objects.get(instance_name='legacy-rollback-instance')

    output = _run_command(
        workspace.id,
        instance_name='legacy-rollback-instance',
        rollback=True,
    )

    conversation.refresh_from_db()
    message.refresh_from_db()
    assert conversation.whatsapp_channel is None
    assert conversation.updated_at == conversation_updated_at
    assert WhatsAppChannel.objects.filter(pk=channel.pk).exists()
    assert Contact.objects.filter(pk=contact.pk).exists()
    assert Conversation.objects.filter(pk=conversation.pk).exists()
    assert Message.objects.filter(pk=message.pk).exists()
    assert message.body == 'Mensagem preservada no rollback'
    assert message.external_id == 'rollback-external-id'
    assert 'Conversas desvinculadas: 1' in output
    assert 'Canal preservado: sim' in output


def test_rollback_is_scoped_to_workspace_whatsapp_and_matching_channel() -> None:
    workspace = WorkspaceFactory()
    other_workspace = WorkspaceFactory()
    target_channel = WhatsAppChannelFactory(
        workspace=workspace,
        name='Canal alvo',
        instance_name='legacy-scoped-rollback',
    )
    other_channel = WhatsAppChannelFactory(
        workspace=workspace,
        name='Outro canal',
    )
    target = ConversationFactory(
        workspace=workspace,
        whatsapp_channel=target_channel,
    )
    linked_to_other_channel = ConversationFactory(
        workspace=workspace,
        whatsapp_channel=other_channel,
    )
    non_whatsapp = ConversationFactory(
        workspace=workspace,
        channel='email',
        whatsapp_channel=target_channel,
    )
    other_workspace_conversation = ConversationFactory(
        workspace=other_workspace,
        with_whatsapp_channel=True,
    )

    _run_command(
        workspace.id,
        instance_name='legacy-scoped-rollback',
        rollback=True,
    )

    for conversation in (
        target,
        linked_to_other_channel,
        non_whatsapp,
        other_workspace_conversation,
    ):
        conversation.refresh_from_db()
    assert target.whatsapp_channel is None
    assert linked_to_other_channel.whatsapp_channel == other_channel
    assert non_whatsapp.whatsapp_channel == target_channel
    assert other_workspace_conversation.whatsapp_channel is not None


def test_rollback_dry_run_and_repeated_rollback_are_idempotent() -> None:
    workspace = WorkspaceFactory()
    conversation = ConversationFactory(workspace=workspace)
    _run_command(workspace.id, instance_name='legacy-idempotent-rollback')

    dry_run_output = _run_command(
        workspace.id,
        instance_name='legacy-idempotent-rollback',
        rollback=True,
        dry_run=True,
    )
    conversation.refresh_from_db()
    assert conversation.whatsapp_channel is not None
    assert 'Conversas associadas ao canal: 1' in dry_run_output
    assert 'Conversas desvinculadas: 0' in dry_run_output

    _run_command(
        workspace.id,
        instance_name='legacy-idempotent-rollback',
        rollback=True,
    )
    second_output = _run_command(
        workspace.id,
        instance_name='legacy-idempotent-rollback',
        rollback=True,
    )
    conversation.refresh_from_db()
    assert conversation.whatsapp_channel is None
    assert 'Conversas associadas ao canal: 0' in second_output
    assert 'Conversas desvinculadas: 0' in second_output


def test_rollback_rejects_channel_owned_by_another_workspace() -> None:
    workspace = WorkspaceFactory()
    other_channel = WhatsAppChannelFactory(instance_name='foreign-rollback-instance')
    other_conversation = ConversationFactory(
        workspace=other_channel.workspace,
        whatsapp_channel=other_channel,
    )

    with pytest.raises(CommandError, match='outro workspace'):
        _run_command(
            workspace.id,
            instance_name='foreign-rollback-instance',
            rollback=True,
        )

    other_conversation.refresh_from_db()
    assert other_conversation.whatsapp_channel == other_channel


@override_settings(EVOLUTION_API_KEY='global-api-key-must-not-leak')
def test_output_is_safe_and_command_makes_no_http_or_celery_calls() -> None:
    workspace = WorkspaceFactory()
    channel = WhatsAppChannelFactory(
        workspace=workspace,
        instance_name='legacy-safe-output',
        instance_token='private-instance-token',
        webhook_secret='private-webhook-secret',
        phone_number='5511777777777',
    )
    conversation = ConversationFactory(workspace=workspace)
    MessageFactory(
        conversation=conversation,
        body='private-message-body',
    )

    with (
        patch('requests.sessions.Session.request') as mock_http,
        patch('celery.app.task.Task.delay') as mock_delay,
    ):
        output = _run_command(
            workspace.id,
            instance_name='legacy-safe-output',
        )

    mock_http.assert_not_called()
    mock_delay.assert_not_called()
    for sensitive_value in (
        'global-api-key-must-not-leak',
        'private-instance-token',
        'private-webhook-secret',
        '5511777777777',
        'private-message-body',
        'instance_token',
        'webhook_secret',
    ):
        assert sensitive_value not in output
    channel.refresh_from_db()
    assert channel.instance_token == 'private-instance-token'


def test_simulated_failure_rolls_back_channel_creation_and_associations() -> None:
    workspace = WorkspaceFactory()
    conversation = ConversationFactory(workspace=workspace)

    with patch(
        'omnichannel.legacy_channel_migration._associate_eligible_conversations',
        side_effect=LegacyChannelMigrationError('Falha simulada segura.'),
    ):
        with pytest.raises(CommandError, match='Falha simulada segura'):
            _run_command(workspace.id, instance_name='legacy-atomic-instance')

    conversation.refresh_from_db()
    assert conversation.whatsapp_channel is None
    assert not WhatsAppChannel.objects.filter(
        instance_name='legacy-atomic-instance',
    ).exists()


def test_operational_migration_has_no_external_calls_or_outbound_global_fallback() -> None:
    migration_source = inspect.getsource(migration_service)
    legacy_send_source = inspect.getsource(send_whatsapp_message)

    assert 'EVOLUTION_API_KEY' not in migration_source
    assert 'requests.' not in migration_source
    assert '.delay(' not in migration_source
    assert 'EVOLUTION_INSTANCE_NAME' not in legacy_send_source
    assert 'channel.instance_name' in legacy_send_source
