from __future__ import annotations

from unittest.mock import patch

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, connection, transaction
from encrypted_model_fields.fields import EncryptedCharField

from omnichannel.factories import ConversationFactory, WhatsAppChannelFactory
from omnichannel.models import Conversation, WhatsAppChannel
from workspaces.factories import WorkspaceFactory


@pytest.mark.django_db
def test_whatsapp_channel_defaults_to_evolution_provider() -> None:
    channel = WhatsAppChannel.objects.create(
        workspace=WorkspaceFactory(),
        name='WhatsApp principal',
        instance_name='default-provider-instance',
    )

    assert channel.provider == WhatsAppChannel.Provider.EVOLUTION


@pytest.mark.django_db
def test_whatsapp_channel_defaults_to_disconnected_status() -> None:
    channel = WhatsAppChannel.objects.create(
        workspace=WorkspaceFactory(),
        name='WhatsApp principal',
        instance_name='default-status-instance',
    )

    assert channel.status == WhatsAppChannel.Status.DISCONNECTED


@pytest.mark.django_db
def test_workspace_exposes_whatsapp_channels_related_name() -> None:
    channel = WhatsAppChannelFactory()

    assert list(channel.workspace.whatsapp_channels.all()) == [channel]


@pytest.mark.django_db
def test_workspace_can_have_multiple_whatsapp_channels() -> None:
    workspace = WorkspaceFactory()
    first = WhatsAppChannelFactory(workspace=workspace)
    second = WhatsAppChannelFactory(workspace=workspace)

    assert set(workspace.whatsapp_channels.all()) == {first, second}


@pytest.mark.django_db
def test_instance_name_is_globally_unique() -> None:
    WhatsAppChannelFactory(instance_name='globally-unique-instance')

    with pytest.raises(IntegrityError):
        with transaction.atomic():
            WhatsAppChannelFactory(instance_name='globally-unique-instance')


@pytest.mark.django_db
def test_webhook_public_id_is_generated_and_unique() -> None:
    first = WhatsAppChannelFactory()
    second = WhatsAppChannelFactory()

    assert first.webhook_public_id is not None
    assert second.webhook_public_id is not None
    assert first.webhook_public_id != second.webhook_public_id


@pytest.mark.django_db
def test_webhook_public_id_rejects_duplicate_value() -> None:
    first = WhatsAppChannelFactory()

    with pytest.raises(IntegrityError):
        with transaction.atomic():
            WhatsAppChannelFactory(webhook_public_id=first.webhook_public_id)


@pytest.mark.django_db
def test_sensitive_values_and_full_phone_are_not_exposed_in_str() -> None:
    channel = WhatsAppChannelFactory(
        instance_token='fake-instance-token',
        webhook_secret='fake-webhook-secret',
        phone_number='5511999999999',
    )

    rendered = str(channel)

    assert 'fake-instance-token' not in rendered
    assert 'fake-webhook-secret' not in rendered
    assert '5511999999999' not in rendered
    assert channel.name in rendered
    assert str(channel.workspace_id) in rendered


def test_sensitive_channel_fields_use_encrypted_storage() -> None:
    for field_name in ('instance_token', 'webhook_secret', 'phone_number'):
        field = WhatsAppChannel._meta.get_field(field_name)
        assert isinstance(field, EncryptedCharField)


@pytest.mark.django_db
def test_sensitive_channel_values_are_encrypted_at_rest() -> None:
    channel = WhatsAppChannelFactory(
        instance_token='fake-instance-token',
        webhook_secret='fake-webhook-secret',
        phone_number='5511999999999',
    )

    with connection.cursor() as cursor:
        cursor.execute(
            'SELECT instance_token, webhook_secret, phone_number '
            'FROM omnichannel_whatsappchannel WHERE id = %s',
            [str(channel.id)],
        )
        raw_values = cursor.fetchone()

    assert raw_values is not None
    serialized_raw_values = ' '.join(
        value.decode('utf-8', errors='ignore')
        if isinstance(value, bytes)
        else str(value)
        for value in raw_values
        if value is not None
    )

    assert 'fake-instance-token' not in serialized_raw_values
    assert 'fake-webhook-secret' not in serialized_raw_values
    assert '5511999999999' not in serialized_raw_values


@pytest.mark.django_db
def test_optional_connection_timestamps_default_to_none() -> None:
    channel = WhatsAppChannelFactory()

    assert channel.connected_at is None
    assert channel.last_connection_update_at is None


@pytest.mark.django_db
def test_last_error_code_preserves_sanitized_code_value() -> None:
    channel = WhatsAppChannelFactory(last_error_code='EVOLUTION_TIMEOUT')

    channel.refresh_from_db()
    assert channel.last_error_code == 'EVOLUTION_TIMEOUT'


@pytest.mark.django_db
def test_conversation_remains_valid_without_whatsapp_channel() -> None:
    conversation = ConversationFactory(whatsapp_channel=None)

    conversation.full_clean()
    assert conversation.whatsapp_channel is None


@pytest.mark.django_db
def test_conversation_accepts_channel_from_same_workspace() -> None:
    workspace = WorkspaceFactory()
    channel = WhatsAppChannelFactory(workspace=workspace)
    conversation = ConversationFactory(
        workspace=workspace,
        whatsapp_channel=channel,
    )

    conversation.full_clean()
    assert conversation.whatsapp_channel == channel
    assert channel.conversations.get() == conversation


@pytest.mark.django_db
def test_conversation_factory_trait_creates_channel_in_same_workspace() -> None:
    conversation = ConversationFactory(with_whatsapp_channel=True)

    assert conversation.whatsapp_channel is not None
    assert conversation.whatsapp_channel.workspace_id == conversation.workspace_id


@pytest.mark.django_db
def test_conversation_full_clean_rejects_channel_from_other_workspace() -> None:
    conversation = ConversationFactory()
    other_channel = WhatsAppChannelFactory()
    conversation.whatsapp_channel = other_channel

    with pytest.raises(ValidationError) as exc_info:
        conversation.full_clean()

    assert 'whatsapp_channel' in exc_info.value.message_dict


@pytest.mark.django_db
def test_deleting_channel_preserves_conversation_and_sets_reference_to_null() -> None:
    workspace = WorkspaceFactory()
    channel = WhatsAppChannelFactory(workspace=workspace)
    conversation = ConversationFactory(
        workspace=workspace,
        whatsapp_channel=channel,
    )

    channel.delete()

    conversation.refresh_from_db()
    assert conversation.whatsapp_channel is None
    assert Conversation.objects.filter(pk=conversation.pk).exists()


@pytest.mark.django_db
def test_deleting_workspace_cascades_to_its_whatsapp_channels() -> None:
    channel = WhatsAppChannelFactory()
    workspace = channel.workspace
    channel_id = channel.id

    # Workspace deletion auditing has its own lifecycle and is outside this
    # model test. Suppress only the audit write created by post_delete.
    with patch('core.signals._create_audit_log'):
        workspace.delete()

    assert not WhatsAppChannel.objects.filter(pk=channel_id).exists()


@pytest.mark.django_db
def test_channel_name_is_unique_inside_workspace() -> None:
    workspace = WorkspaceFactory()
    WhatsAppChannelFactory(workspace=workspace, name='WhatsApp principal')

    with pytest.raises(IntegrityError):
        with transaction.atomic():
            WhatsAppChannelFactory(workspace=workspace, name='WhatsApp principal')


@pytest.mark.django_db
def test_same_channel_name_is_allowed_in_different_workspaces() -> None:
    first = WhatsAppChannelFactory(name='WhatsApp principal')
    second = WhatsAppChannelFactory(name='WhatsApp principal')

    assert first.workspace_id != second.workspace_id
