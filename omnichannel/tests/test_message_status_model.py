from __future__ import annotations

import pytest

from omnichannel.factories import ConversationFactory, MessageFactory
from omnichannel.models import AIProcessingRun, Message


def test_message_status_pending_exists() -> None:
    assert Message.Status.PENDING == 'pending'
    assert ('pending', 'Pendente') in Message.Status.choices


@pytest.mark.django_db
def test_message_can_be_created_as_outbound_pending() -> None:
    conversation = ConversationFactory()

    message = Message.objects.create(
        conversation=conversation,
        body='Resposta em preparacao.',
        direction=Message.Direction.OUTBOUND,
        status=Message.Status.PENDING,
    )

    assert message.direction == Message.Direction.OUTBOUND
    assert message.status == Message.Status.PENDING


@pytest.mark.django_db
def test_message_send_error_code_defaults_to_empty_string() -> None:
    message = MessageFactory()

    assert message.send_error_code == ''


def test_message_has_send_error_code_field_without_sensitive_storage() -> None:
    field_names = {field.name for field in Message._meta.get_fields()}

    assert 'send_error_code' in field_names
    assert 'api_key' not in field_names
    assert 'payload' not in field_names
    assert 'raw_payload' not in field_names


def test_message_status_migration_does_not_add_sensitive_fields_to_ai_processing_run() -> None:
    field_names = {field.name for field in AIProcessingRun._meta.get_fields()}

    assert 'api_key' not in field_names
    assert 'payload' not in field_names
    assert 'raw_payload' not in field_names
    assert 'body' not in field_names
