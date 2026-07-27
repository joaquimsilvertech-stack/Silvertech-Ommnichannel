from __future__ import annotations

import pytest

from omnichannel.factories import ConversationFactory, WhatsAppChannelFactory
from omnichannel.models import WhatsAppChannel
from omnichannel.whatsapp_recipient_validation import (
    RECIPIENT_IS_CHANNEL_PHONE,
    RECIPIENT_UNRESOLVED,
    VALID_RECIPIENT,
    normalize_trusted_phone,
    validate_conversation_whatsapp_recipient,
    validate_whatsapp_recipient,
)
from workspaces.factories import WorkspaceFactory


@pytest.mark.parametrize(
    ('value', 'expected'),
    [
        ('5511999999999', '5511999999999'),
        ('+55 (11) 99999-9999', '5511999999999'),
        (' 55 11 99999-9999 ', '5511999999999'),
    ],
)
def test_normalize_trusted_phone_accepts_only_canonicalizable_phone_values(
    value: str,
    expected: str,
) -> None:
    assert normalize_trusted_phone(value) == expected


@pytest.mark.parametrize(
    'value',
    [
        None,
        '',
        '   ',
        '5511999999999@lid',
        '5511999999999@s.whatsapp.net',
        '120363000000000000@g.us',
        'cms3:opaque-recipient',
        'phone-extension-x12',
        '5511\n99999999',
        '1234567',
        '1' * 21,
    ],
)
def test_normalize_trusted_phone_rejects_opaque_or_untrusted_identities(
    value: object,
) -> None:
    assert normalize_trusted_phone(value) is None


def test_validate_recipient_returns_canonical_phone() -> None:
    validation = validate_whatsapp_recipient(
        recipient='+55 (11) 99999-9999',
        channel_phone_number='5511888888888',
    )

    assert validation.status == VALID_RECIPIENT
    assert validation.canonical_phone == '5511999999999'
    assert validation.is_valid is True


def test_validate_recipient_detects_own_channel_phone_after_normalization() -> None:
    validation = validate_whatsapp_recipient(
        recipient='+55 (11) 99999-9999',
        channel_phone_number='55 11 99999-9999',
    )

    assert validation.status == RECIPIENT_IS_CHANNEL_PHONE
    assert validation.canonical_phone == ''
    assert validation.is_valid is False


def test_validate_recipient_marks_opaque_identity_unresolved() -> None:
    validation = validate_whatsapp_recipient(
        recipient='123456789012345@lid',
    )

    assert validation.status == RECIPIENT_UNRESOLVED
    assert validation.canonical_phone == ''
    assert validation.is_valid is False


@pytest.mark.django_db
def test_conversation_validation_fails_closed_for_cross_workspace_contact() -> None:
    workspace = WorkspaceFactory()
    conversation = ConversationFactory(
        workspace=workspace,
        contact__phone='5511999999999',
    )
    conversation.contact.workspace = WorkspaceFactory()
    conversation.contact.save(update_fields=['workspace', 'updated_at'])

    validation = validate_conversation_whatsapp_recipient(conversation)

    assert validation.status == RECIPIENT_UNRESOLVED


@pytest.mark.django_db
def test_conversation_validation_uses_persisted_channel_phone() -> None:
    channel = WhatsAppChannelFactory(
        status=WhatsAppChannel.Status.CONNECTED,
        phone_number='5511999999999',
    )
    conversation = ConversationFactory(
        workspace=channel.workspace,
        whatsapp_channel=channel,
        contact__phone='+55 (11) 99999-9999',
    )

    validation = validate_conversation_whatsapp_recipient(conversation)

    assert validation.status == RECIPIENT_IS_CHANNEL_PHONE
