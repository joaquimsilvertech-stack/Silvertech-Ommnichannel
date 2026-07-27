from __future__ import annotations

import logging
from datetime import timedelta
from unittest.mock import patch

import pytest
from django.db import IntegrityError, transaction
from django.utils import timezone

from crm.models import Contact
from omnichannel.factories import ContactFactory, ConversationFactory, WhatsAppChannelFactory
from omnichannel.inbound_routing import resolve_inbound_whatsapp_route
from omnichannel.models import Conversation

pytestmark = pytest.mark.django_db

PHONE = '5511888888888'


def _resolve(
    channel,
    *,
    phone: str = PHONE,
    provider_identity: str | None = None,
    resolved_phone: str | None = None,
    name: object = 'Contato Seguro',
):
    with transaction.atomic():
        return resolve_inbound_whatsapp_route(
            channel=channel,
            provider_identity=provider_identity or phone,
            resolved_phone=phone if resolved_phone is None else resolved_phone,
            contact_name=name,  # type: ignore[arg-type]
        )


def test_creates_contact_and_conversation_for_channel_workspace() -> None:
    channel = WhatsAppChannelFactory()

    route = _resolve(channel)

    assert route.contact.workspace_id == channel.workspace_id
    assert route.contact.phone == PHONE
    assert route.contact.channel_id == PHONE
    assert route.contact.name == 'Contato Seguro'
    assert route.conversation.workspace_id == channel.workspace_id
    assert route.conversation.contact == route.contact
    assert route.conversation.whatsapp_channel == channel
    assert route.conversation.channel == 'whatsapp'
    assert route.conversation.status == Conversation.Status.OPEN


def test_reuses_exact_workspace_and_channel_identity() -> None:
    channel = WhatsAppChannelFactory()
    contact = ContactFactory(
        workspace=channel.workspace,
        phone=PHONE,
        channel_id=PHONE,
        name='Nome curado',
    )

    route = _resolve(channel, name='Nome externo')

    assert route.contact == contact
    route.contact.refresh_from_db()
    assert route.contact.name == 'Nome curado'


def test_contact_from_another_workspace_is_never_reused() -> None:
    channel = WhatsAppChannelFactory()
    other = ContactFactory(phone=PHONE, channel_id=PHONE)

    route = _resolve(channel)

    assert route.contact.id != other.id
    assert route.contact.workspace_id == channel.workspace_id


@pytest.mark.parametrize('empty_identity', [None, ''])
def test_claims_unassigned_contact_with_same_phone(empty_identity) -> None:
    channel = WhatsAppChannelFactory()
    contact = ContactFactory(
        workspace=channel.workspace,
        phone=PHONE,
        channel_id=empty_identity,
        name='Nome curado',
    )

    route = _resolve(channel)

    assert route.contact == contact
    contact.refresh_from_db()
    assert contact.channel_id == PHONE
    assert contact.name == 'Nome curado'


def test_claims_oldest_unassigned_contact_deterministically() -> None:
    channel = WhatsAppChannelFactory()
    older = ContactFactory(workspace=channel.workspace, phone=PHONE, channel_id=None)
    newer = ContactFactory(workspace=channel.workspace, phone=PHONE, channel_id='')
    Contact.objects.filter(id=older.id).update(created_at=timezone.now() - timedelta(days=1))

    route = _resolve(channel)

    assert route.contact == older
    newer.refresh_from_db()
    assert newer.channel_id == ''


def test_same_phone_with_different_identity_is_not_overwritten() -> None:
    channel = WhatsAppChannelFactory()
    existing = ContactFactory(
        workspace=channel.workspace,
        phone=PHONE,
        channel_id='different-identity',
    )

    route = _resolve(channel)

    existing.refresh_from_db()
    assert route.contact.id != existing.id
    assert existing.channel_id == 'different-identity'
    assert route.contact.channel_id == PHONE


def test_creation_race_reuses_identity_winner() -> None:
    channel = WhatsAppChannelFactory()
    winner = ContactFactory(workspace=channel.workspace, phone=PHONE, channel_id=PHONE)

    with (
        patch(
            'omnichannel.inbound_routing._get_exact_contact',
            side_effect=[None, winner],
        ),
        patch('omnichannel.inbound_routing._get_unclaimed_contact', return_value=None),
        patch(
            'omnichannel.inbound_routing._create_contact_identity',
            side_effect=IntegrityError('identity race'),
        ),
    ):
        route = _resolve(channel)

    assert route.contact == winner
    assert Contact.objects.filter(workspace=channel.workspace, channel_id=PHONE).count() == 1


def test_claim_race_reuses_identity_winner_without_overwriting_candidate() -> None:
    channel = WhatsAppChannelFactory()
    candidate = ContactFactory(workspace=channel.workspace, phone=PHONE, channel_id=None)
    winner = ContactFactory(workspace=channel.workspace, phone=PHONE, channel_id=PHONE)

    with (
        patch(
            'omnichannel.inbound_routing._get_exact_contact',
            side_effect=[None, winner],
        ),
        patch(
            'omnichannel.inbound_routing._claim_contact_identity',
            side_effect=IntegrityError('identity race'),
        ),
    ):
        route = _resolve(channel)

    candidate.refresh_from_db()
    assert route.contact == winner
    assert candidate.channel_id is None


def test_unrelated_integrity_error_is_propagated() -> None:
    channel = WhatsAppChannelFactory()

    with (
        patch(
            'omnichannel.inbound_routing._create_contact_identity',
            side_effect=IntegrityError('unrelated constraint'),
        ),
        pytest.raises(IntegrityError, match='unrelated constraint'),
    ):
        _resolve(channel)


def test_push_name_updates_placeholder_name() -> None:
    channel = WhatsAppChannelFactory()
    contact = ContactFactory(
        workspace=channel.workspace,
        phone=PHONE,
        channel_id=PHONE,
        name=PHONE,
    )

    route = _resolve(channel, name='Maria Silva')

    route.contact.refresh_from_db()
    assert route.contact == contact
    assert route.contact.name == 'Maria Silva'


def test_push_name_does_not_replace_curated_name() -> None:
    channel = WhatsAppChannelFactory()
    contact = ContactFactory(
        workspace=channel.workspace,
        phone=PHONE,
        channel_id=PHONE,
        name='Cliente Premium',
    )

    route = _resolve(channel, name='Nome externo')

    route.contact.refresh_from_db()
    assert route.contact == contact
    assert route.contact.name == 'Cliente Premium'


@pytest.mark.parametrize('invalid_name', ['', ' nome ', 'nome\nmalformado', 'X' * 256, None])
def test_invalid_contact_name_uses_phone_only_on_creation(invalid_name) -> None:
    channel = WhatsAppChannelFactory()

    route = _resolve(channel, name=invalid_name)

    assert route.contact.name == PHONE


def test_same_phone_on_two_channels_reuses_contact_with_separate_conversations() -> None:
    first = WhatsAppChannelFactory()
    second = WhatsAppChannelFactory(workspace=first.workspace)

    first_route = _resolve(first)
    second_route = _resolve(second)

    assert first_route.contact == second_route.contact
    assert first_route.conversation.id != second_route.conversation.id
    assert first_route.conversation.whatsapp_channel == first
    assert second_route.conversation.whatsapp_channel == second
    assert Contact.objects.filter(workspace=first.workspace, channel_id=PHONE).count() == 1


def test_same_phone_in_two_workspaces_creates_isolated_contacts() -> None:
    first = WhatsAppChannelFactory()
    second = WhatsAppChannelFactory()

    first_route = _resolve(first)
    second_route = _resolve(second)

    assert first_route.contact.id != second_route.contact.id
    assert first_route.contact.workspace_id == first.workspace_id
    assert second_route.contact.workspace_id == second.workspace_id


def test_reuses_open_conversation_only_for_exact_channel() -> None:
    channel = WhatsAppChannelFactory()
    contact = ContactFactory(workspace=channel.workspace, phone=PHONE, channel_id=PHONE)
    conversation = ConversationFactory(
        workspace=channel.workspace,
        contact=contact,
        whatsapp_channel=channel,
        status=Conversation.Status.OPEN,
    )

    route = _resolve(channel)

    assert route.conversation == conversation


def test_open_conversation_from_other_channel_is_not_reused() -> None:
    target = WhatsAppChannelFactory()
    other = WhatsAppChannelFactory(workspace=target.workspace)
    contact = ContactFactory(workspace=target.workspace, phone=PHONE, channel_id=PHONE)
    other_conversation = ConversationFactory(
        workspace=target.workspace,
        contact=contact,
        whatsapp_channel=other,
        status=Conversation.Status.OPEN,
    )

    route = _resolve(target)

    assert route.conversation.id != other_conversation.id
    assert route.conversation.whatsapp_channel == target


def test_legacy_conversation_without_channel_is_not_reused() -> None:
    channel = WhatsAppChannelFactory()
    contact = ContactFactory(workspace=channel.workspace, phone=PHONE, channel_id=PHONE)
    legacy = ConversationFactory(
        workspace=channel.workspace,
        contact=contact,
        whatsapp_channel=None,
        status=Conversation.Status.OPEN,
    )

    route = _resolve(channel)

    assert route.conversation.id != legacy.id
    assert route.conversation.whatsapp_channel == channel


def test_closed_conversation_is_not_reused() -> None:
    channel = WhatsAppChannelFactory()
    contact = ContactFactory(workspace=channel.workspace, phone=PHONE, channel_id=PHONE)
    closed = ConversationFactory(
        workspace=channel.workspace,
        contact=contact,
        whatsapp_channel=channel,
        status=Conversation.Status.CLOSED,
    )

    route = _resolve(channel)

    assert route.conversation.id != closed.id
    assert route.conversation.status == Conversation.Status.OPEN


def test_historical_open_duplicates_reuse_oldest_and_log_only_technical_ids(caplog) -> None:
    channel = WhatsAppChannelFactory()
    contact = ContactFactory(
        workspace=channel.workspace,
        phone=PHONE,
        channel_id=PHONE,
        name='Private Contact Name',
    )
    older = ConversationFactory(
        workspace=channel.workspace,
        contact=contact,
        whatsapp_channel=channel,
    )
    ConversationFactory(
        workspace=channel.workspace,
        contact=contact,
        whatsapp_channel=channel,
    )
    Conversation.objects.filter(id=older.id).update(
        created_at=timezone.now() - timedelta(days=1),
    )
    caplog.set_level(logging.WARNING, logger='omnichannel.inbound_routing')

    route = _resolve(channel)

    assert route.conversation.id == older.id
    record = next(
        item for item in caplog.records if item.name == 'omnichannel.inbound_routing'
    )
    assert record.error_code == 'DUPLICATE_OPEN_CONVERSATIONS'
    assert record.duplicate_count == 2
    rendered = f'{record.getMessage()} {record.__dict__}'
    assert PHONE not in rendered
    assert 'Private Contact Name' not in rendered


def test_routing_service_never_performs_external_http() -> None:
    channel = WhatsAppChannelFactory()

    with patch('requests.sessions.Session.request') as request:
        _resolve(channel)

    request.assert_not_called()
