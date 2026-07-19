from __future__ import annotations

import logging
from unittest.mock import patch

import pytest

from crm.models import Contact
from omnichannel.evolution_event_processing import (
    build_provider_message_key,
    process_evolution_channel_event,
)
from omnichannel.factories import ContactFactory, ConversationFactory, WhatsAppChannelFactory
from omnichannel.models import Conversation, EvolutionWebhookEvent, Message, WhatsAppChannel
from workspaces.factories import WorkspaceAIProviderConfigFactory

pytestmark = pytest.mark.django_db


def _item(
    external_id: str = 'incoming-message-1',
    *,
    phone: str = '5511999999999',
    text: str = 'Mensagem inbound de teste',
    push_name: object = 'Contato Teste',
    from_me: object = False,
) -> dict:
    return {
        'key': {
            'id': external_id,
            'remoteJid': f'{phone}@s.whatsapp.net',
            'fromMe': from_me,
        },
        'pushName': push_name,
        'message': {'conversation': text},
        'messageType': 'conversation',
    }


def _payload(data: object, **extra) -> dict:
    payload = {
        'event': 'messages.upsert',
        'instance': 'untrusted-instance',
        'workspace_id': 'untrusted-workspace',
        'data': data,
    }
    payload.update(extra)
    return payload


def test_text_message_creates_tenant_scoped_contact_conversation_and_message() -> None:
    channel = WhatsAppChannelFactory()
    process_evolution_channel_event(channel=channel, payload=_payload(_item()))

    contact = Contact.objects.get(workspace=channel.workspace)
    conversation = Conversation.objects.get(workspace=channel.workspace)
    message = Message.objects.get(conversation=conversation)
    receipt = EvolutionWebhookEvent.objects.get(whatsapp_channel=channel)
    expected_key = build_provider_message_key(channel.id, 'incoming-message-1')

    assert contact.phone == '5511999999999'
    assert contact.channel_id == '5511999999999'
    assert contact.name == 'Contato Teste'
    assert conversation.contact == contact
    assert conversation.workspace == channel.workspace
    assert conversation.whatsapp_channel == channel
    assert conversation.channel == 'whatsapp'
    assert message.direction == Message.Direction.INBOUND
    assert message.status == Message.Status.DELIVERED
    assert message.external_id == 'incoming-message-1'
    assert message.provider_message_key == expected_key
    assert 'incoming-message-1' not in expected_key
    assert receipt.status == EvolutionWebhookEvent.Status.PROCESSED


def test_extended_text_message_is_supported() -> None:
    channel = WhatsAppChannelFactory()
    item = _item()
    item['message'] = {'extendedTextMessage': {'text': 'Texto estendido'}}
    process_evolution_channel_event(channel=channel, payload=_payload(item))
    assert Message.objects.get().body == 'Texto estendido'


def test_explicit_false_from_me_is_accepted() -> None:
    channel = WhatsAppChannelFactory()

    process_evolution_channel_event(
        channel=channel,
        payload=_payload(_item(from_me=False)),
    )

    assert Message.objects.filter(conversation__whatsapp_channel=channel).count() == 1


def test_lid_uses_confirmed_alternate_phone_jid() -> None:
    channel = WhatsAppChannelFactory()
    item = _item()
    item['key']['remoteJid'] = '123456789012345@lid'
    item['key']['remoteJidAlt'] = '5511777777777@s.whatsapp.net'
    process_evolution_channel_event(channel=channel, payload=_payload(item))
    assert Contact.objects.get(workspace=channel.workspace).phone == '5511777777777'


def test_c_us_individual_jid_is_supported() -> None:
    channel = WhatsAppChannelFactory()
    item = _item()
    item['key']['remoteJid'] = '5511777777777@c.us'

    process_evolution_channel_event(channel=channel, payload=_payload(item))

    assert Contact.objects.get(workspace=channel.workspace).channel_id == '5511777777777'


def test_same_contact_and_open_conversation_are_reused_in_same_channel() -> None:
    channel = WhatsAppChannelFactory()
    process_evolution_channel_event(channel=channel, payload=_payload(_item('message-1')))
    process_evolution_channel_event(channel=channel, payload=_payload(_item('message-2')))

    assert Contact.objects.filter(workspace=channel.workspace).count() == 1
    assert Conversation.objects.filter(whatsapp_channel=channel).count() == 1
    assert Message.objects.filter(conversation__whatsapp_channel=channel).count() == 2


def test_duplicate_message_does_not_duplicate_domain_or_ai_schedule(
    django_capture_on_commit_callbacks,
) -> None:
    channel = WhatsAppChannelFactory()
    WorkspaceAIProviderConfigFactory(workspace=channel.workspace, is_active=True)
    payload = _payload(_item())

    with (
        patch('omnichannel.tasks.process_ai_response.delay') as ai_task,
        django_capture_on_commit_callbacks(execute=True),
    ):
        process_evolution_channel_event(channel=channel, payload=payload)
        process_evolution_channel_event(channel=channel, payload=payload)

    assert Contact.objects.filter(workspace=channel.workspace).count() == 1
    assert Conversation.objects.filter(whatsapp_channel=channel).count() == 1
    assert Message.objects.filter(conversation__whatsapp_channel=channel).count() == 1
    assert EvolutionWebhookEvent.objects.filter(whatsapp_channel=channel).count() == 1
    ai_task.assert_called_once()


def test_list_processes_new_items_and_skips_duplicate_independently() -> None:
    channel = WhatsAppChannelFactory()
    first = _item('list-message-1')
    process_evolution_channel_event(channel=channel, payload=_payload(first))

    process_evolution_channel_event(
        channel=channel,
        payload=_payload([first, _item('list-message-2'), {'invalid': True}]),
    )

    assert Message.objects.filter(conversation__whatsapp_channel=channel).count() == 2
    assert EvolutionWebhookEvent.objects.filter(whatsapp_channel=channel).count() == 3
    assert EvolutionWebhookEvent.objects.filter(
        whatsapp_channel=channel,
        status=EvolutionWebhookEvent.Status.IGNORED,
    ).count() == 1


@pytest.mark.parametrize(
    ('mutator', 'expected_error'),
    [
        (lambda item: item.pop('key'), 'INVALID_MESSAGE_KEY'),
        (lambda item: item['key'].pop('id'), 'INVALID_EXTERNAL_ID'),
        (lambda item: item['key'].pop('remoteJid'), 'INVALID_REMOTE_JID'),
        (lambda item: item['key'].pop('fromMe'), 'INVALID_FROM_ME'),
        (lambda item: item['key'].__setitem__('fromMe', None), 'INVALID_FROM_ME'),
        (lambda item: item['key'].__setitem__('fromMe', 'false'), 'INVALID_FROM_ME'),
        (lambda item: item['key'].__setitem__('fromMe', 0), 'INVALID_FROM_ME'),
        (lambda item: item['key'].__setitem__('fromMe', True), 'MESSAGE_FROM_ME'),
        (
            lambda item: item['key'].__setitem__('remoteJid', '5511999999999'),
            'INVALID_REMOTE_JID',
        ),
        (
            lambda item: item['key'].__setitem__(
                'remoteJid',
                ' 5511999999999@s.whatsapp.net ',
            ),
            'INVALID_REMOTE_JID',
        ),
        (
            lambda item: item['key'].__setitem__(
                'remoteJid',
                '5511999999999\n@s.whatsapp.net',
            ),
            'INVALID_REMOTE_JID',
        ),
        (
            lambda item: item['key'].__setitem__('remoteJid', f"{'1' * 7}@s.whatsapp.net"),
            'INVALID_REMOTE_JID',
        ),
        (
            lambda item: item['key'].__setitem__('remoteJid', f"{'1' * 21}@s.whatsapp.net"),
            'INVALID_REMOTE_JID',
        ),
        (
            lambda item: item['key'].__setitem__('remoteJid', '123456789@g.us'),
            'UNSUPPORTED_GROUP_MESSAGE',
        ),
        (
            lambda item: item['key'].__setitem__('remoteJid', '5511999999999@broadcast'),
            'UNSUPPORTED_REMOTE_JID',
        ),
        (
            lambda item: item['key'].__setitem__('remoteJid', 'status@broadcast'),
            'UNSUPPORTED_REMOTE_JID',
        ),
        (
            lambda item: item['key'].__setitem__('remoteJid', '5511999999999@newsletter'),
            'UNSUPPORTED_REMOTE_JID',
        ),
        (
            lambda item: item['key'].__setitem__('remoteJid', '5511999999999@unknown'),
            'UNSUPPORTED_REMOTE_JID',
        ),
        (
            lambda item: item['key'].__setitem__('remoteJid', '123456789012345@lid'),
            'INVALID_REMOTE_JID',
        ),
        (
            lambda item: (
                item['key'].__setitem__('remoteJid', '123456789012345@lid'),
                item['key'].__setitem__('remoteJidAlt', '123456789012345@lid'),
            ),
            'INVALID_REMOTE_JID',
        ),
        (
            lambda item: (
                item['key'].__setitem__('remoteJid', '123456789012345@lid'),
                item['key'].__setitem__('remoteJidAlt', '5511999999999@g.us'),
            ),
            'INVALID_REMOTE_JID',
        ),
        (lambda item: item.__setitem__('message', {'conversation': ''}), 'UNSUPPORTED_MESSAGE_CONTENT'),
        (lambda item: item.__setitem__('message', {'imageMessage': {}}), 'UNSUPPORTED_MESSAGE_CONTENT'),
    ],
)
def test_invalid_inbound_items_are_receipted_without_domain_objects(mutator, expected_error) -> None:
    channel = WhatsAppChannelFactory()
    item = _item()
    mutator(item)

    process_evolution_channel_event(channel=channel, payload=_payload(item))

    event = EvolutionWebhookEvent.objects.get(whatsapp_channel=channel)
    assert event.status == EvolutionWebhookEvent.Status.IGNORED
    assert event.error_code == expected_error
    assert not Contact.objects.filter(workspace=channel.workspace).exists()
    assert not Conversation.objects.filter(workspace=channel.workspace).exists()
    assert not Message.objects.filter(conversation__workspace=channel.workspace).exists()


@pytest.mark.parametrize('push_name', ['', ' bad ', 'bad\nname', 'X' * 256, {'name': 'bad'}])
def test_invalid_push_name_is_not_stored(push_name) -> None:
    channel = WhatsAppChannelFactory()
    process_evolution_channel_event(
        channel=channel,
        payload=_payload(_item(push_name=push_name)),
    )
    contact = Contact.objects.get(workspace=channel.workspace)
    assert contact.name == contact.phone


def test_valid_push_name_updates_existing_placeholder_contact() -> None:
    channel = WhatsAppChannelFactory()
    Contact.objects.create(
        workspace=channel.workspace,
        name='5511999999999',
        phone='5511999999999',
    )
    process_evolution_channel_event(channel=channel, payload=_payload(_item()))
    assert Contact.objects.get(workspace=channel.workspace).name == 'Contato Teste'


def test_valid_push_name_does_not_replace_curated_contact_name() -> None:
    channel = WhatsAppChannelFactory()
    contact = Contact.objects.create(
        workspace=channel.workspace,
        name='Cliente Premium',
        phone='5511999999999',
        channel_id='5511999999999',
    )

    process_evolution_channel_event(channel=channel, payload=_payload(_item()))

    contact.refresh_from_db()
    assert contact.name == 'Cliente Premium'


def test_same_phone_is_isolated_between_workspaces() -> None:
    first = WhatsAppChannelFactory()
    second = WhatsAppChannelFactory()
    process_evolution_channel_event(channel=first, payload=_payload(_item('first')))
    process_evolution_channel_event(channel=second, payload=_payload(_item('second')))

    assert Contact.objects.filter(phone='5511999999999').count() == 2
    assert Contact.objects.filter(workspace=first.workspace).count() == 1
    assert Contact.objects.filter(workspace=second.workspace).count() == 1


def test_same_contact_on_two_channels_gets_separate_conversations() -> None:
    first = WhatsAppChannelFactory()
    second = WhatsAppChannelFactory(workspace=first.workspace)
    process_evolution_channel_event(channel=first, payload=_payload(_item('first')))
    process_evolution_channel_event(channel=second, payload=_payload(_item('second')))

    assert Contact.objects.filter(workspace=first.workspace).count() == 1
    assert Conversation.objects.filter(workspace=first.workspace).count() == 2
    assert Conversation.objects.filter(whatsapp_channel=first).count() == 1
    assert Conversation.objects.filter(whatsapp_channel=second).count() == 1


def test_same_external_id_on_two_channels_creates_one_message_per_channel() -> None:
    first = WhatsAppChannelFactory()
    second = WhatsAppChannelFactory(workspace=first.workspace)
    payload = _payload(_item('shared-external-id'))

    process_evolution_channel_event(channel=first, payload=payload)
    process_evolution_channel_event(channel=second, payload=payload)

    first_message = Message.objects.get(conversation__whatsapp_channel=first)
    second_message = Message.objects.get(conversation__whatsapp_channel=second)
    assert first_message.id != second_message.id
    assert first_message.provider_message_key != second_message.provider_message_key
    assert Contact.objects.filter(workspace=first.workspace).count() == 1


def test_channel_never_reuses_open_conversation_from_another_channel() -> None:
    target = WhatsAppChannelFactory()
    other = WhatsAppChannelFactory(workspace=target.workspace)
    contact = ContactFactory(
        workspace=target.workspace,
        phone='5511999999999',
        channel_id='5511999999999',
    )
    other_conversation = ConversationFactory(
        workspace=target.workspace,
        contact=contact,
        whatsapp_channel=other,
        status=Conversation.Status.OPEN,
    )

    process_evolution_channel_event(channel=target, payload=_payload(_item()))

    target_conversation = Conversation.objects.get(whatsapp_channel=target)
    assert target_conversation.id != other_conversation.id
    assert target_conversation.contact == contact


def test_channel_never_reuses_legacy_open_conversation_without_channel() -> None:
    channel = WhatsAppChannelFactory()
    contact = ContactFactory(
        workspace=channel.workspace,
        phone='5511999999999',
        channel_id='5511999999999',
    )
    legacy = ConversationFactory(
        workspace=channel.workspace,
        contact=contact,
        whatsapp_channel=None,
        status=Conversation.Status.OPEN,
    )

    process_evolution_channel_event(channel=channel, payload=_payload(_item()))

    current = Conversation.objects.get(whatsapp_channel=channel)
    assert current.id != legacy.id
    assert current.contact == contact


def test_payload_workspace_and_instance_do_not_change_tenant_routing() -> None:
    channel = WhatsAppChannelFactory()
    other = WhatsAppChannelFactory()
    payload = _payload(_item())
    payload['workspace_id'] = str(other.workspace_id)
    payload['instance'] = other.instance_name

    process_evolution_channel_event(channel=channel, payload=payload)

    assert Contact.objects.filter(workspace=channel.workspace).count() == 1
    assert Contact.objects.filter(workspace=other.workspace).count() == 0
    assert Conversation.objects.filter(workspace=channel.workspace, whatsapp_channel=channel).count() == 1
    assert not Conversation.objects.filter(workspace=other.workspace).exists()
    assert Message.objects.filter(conversation__workspace=channel.workspace).count() == 1
    assert not Message.objects.filter(conversation__workspace=other.workspace).exists()


def test_untrusted_tenant_fields_cannot_cross_two_processed_workspaces() -> None:
    first = WhatsAppChannelFactory()
    second = WhatsAppChannelFactory()
    first_payload = _payload(_item('tenant-first'))
    first_payload['workspace_id'] = str(second.workspace_id)
    first_payload['instance'] = second.instance_name
    second_payload = _payload(_item('tenant-second'))
    second_payload['workspace_id'] = str(first.workspace_id)
    second_payload['instance'] = first.instance_name

    process_evolution_channel_event(channel=first, payload=first_payload)
    process_evolution_channel_event(channel=second, payload=second_payload)

    first_contact = Contact.objects.get(workspace=first.workspace)
    second_contact = Contact.objects.get(workspace=second.workspace)
    assert first_contact.id != second_contact.id
    assert Conversation.objects.get(whatsapp_channel=first).contact == first_contact
    assert Conversation.objects.get(whatsapp_channel=second).contact == second_contact
    assert Message.objects.filter(conversation__workspace=first.workspace).count() == 1
    assert Message.objects.filter(conversation__workspace=second.workspace).count() == 1


def test_deleting_channel_does_not_create_inbound_domain_objects() -> None:
    channel = WhatsAppChannelFactory(status=WhatsAppChannel.Status.DELETING)
    process_evolution_channel_event(channel=channel, payload=_payload(_item()))

    event = EvolutionWebhookEvent.objects.get(whatsapp_channel=channel)
    assert event.status == EvolutionWebhookEvent.Status.IGNORED
    assert event.error_code == 'CHANNEL_DELETING'
    assert not Message.objects.filter(conversation__workspace=channel.workspace).exists()


def test_ai_is_scheduled_only_after_commit_for_active_provider(
    django_capture_on_commit_callbacks,
) -> None:
    channel = WhatsAppChannelFactory()
    WorkspaceAIProviderConfigFactory(workspace=channel.workspace, is_active=True)

    with patch('omnichannel.tasks.process_ai_response.delay') as ai_task:
        with django_capture_on_commit_callbacks(execute=False) as callbacks:
            process_evolution_channel_event(channel=channel, payload=_payload(_item()))
            ai_task.assert_not_called()
        for callback in callbacks:
            callback()

    ai_task.assert_called_once()
    assert ai_task.call_args.kwargs['conversation_id'] == str(Conversation.objects.get().id)
    assert ai_task.call_args.kwargs['source_message_id'] == str(Message.objects.get().id)


def test_no_provider_and_handoff_preserve_ai_guards(django_capture_on_commit_callbacks) -> None:
    channel = WhatsAppChannelFactory()
    with (
        patch('omnichannel.tasks.process_ai_response.delay') as ai_task,
        django_capture_on_commit_callbacks(execute=True),
    ):
        process_evolution_channel_event(channel=channel, payload=_payload(_item('without-provider')))
    ai_task.assert_not_called()

    conversation = Conversation.objects.get(whatsapp_channel=channel)
    conversation.is_human_handoff = True
    conversation.save(update_fields=['is_human_handoff', 'updated_at'])
    WorkspaceAIProviderConfigFactory(workspace=channel.workspace, is_active=True)
    with (
        patch('omnichannel.tasks.process_ai_response.delay') as ai_task,
        django_capture_on_commit_callbacks(execute=True),
    ):
        process_evolution_channel_event(channel=channel, payload=_payload(_item('handoff')))
    ai_task.assert_not_called()


def test_ai_scheduling_failure_rolls_back_domain_and_marks_receipt_failed() -> None:
    channel = WhatsAppChannelFactory()
    with (
        patch(
            'omnichannel.services.handle_inbound_ai_scheduling',
            side_effect=RuntimeError('private-error'),
        ),
        pytest.raises(RuntimeError),
    ):
        process_evolution_channel_event(channel=channel, payload=_payload(_item()))

    assert not Message.objects.filter(conversation__workspace=channel.workspace).exists()
    assert not Conversation.objects.filter(workspace=channel.workspace).exists()
    assert not Contact.objects.filter(workspace=channel.workspace).exists()
    assert EvolutionWebhookEvent.objects.get(
        whatsapp_channel=channel,
    ).status == EvolutionWebhookEvent.Status.FAILED


def test_ai_scheduling_failure_rolls_back_claimed_contact_identity() -> None:
    channel = WhatsAppChannelFactory()
    contact = ContactFactory(
        workspace=channel.workspace,
        name='Nome curado',
        phone='5511999999999',
        channel_id=None,
    )

    with (
        patch(
            'omnichannel.services.handle_inbound_ai_scheduling',
            side_effect=RuntimeError('private-error'),
        ),
        pytest.raises(RuntimeError),
    ):
        process_evolution_channel_event(channel=channel, payload=_payload(_item()))

    contact.refresh_from_db()
    assert contact.channel_id is None
    assert contact.name == 'Nome curado'
    assert not Conversation.objects.filter(workspace=channel.workspace).exists()
    assert not Message.objects.filter(conversation__workspace=channel.workspace).exists()
    receipt = EvolutionWebhookEvent.objects.get(whatsapp_channel=channel)
    assert receipt.status == EvolutionWebhookEvent.Status.FAILED


def test_inbound_logs_do_not_include_payload_phone_body_or_external_id(caplog) -> None:
    channel = WhatsAppChannelFactory()
    phone = '5511666666666'
    body = 'private inbound body sentinel'
    external_id = 'private-external-sentinel'
    push_name = 'Private Push Name Sentinel'
    caplog.set_level(logging.INFO)

    process_evolution_channel_event(
        channel=channel,
        payload=_payload(
            _item(external_id, phone=phone, text=body, push_name=push_name),
        ),
    )

    rendered = ' '.join(record.getMessage() + repr(record.__dict__) for record in caplog.records)
    assert phone not in rendered
    assert body not in rendered
    assert external_id not in rendered
    assert push_name not in rendered


def test_lid_logs_do_not_include_remote_jids(caplog) -> None:
    channel = WhatsAppChannelFactory()
    remote_jid = '123456789012345@lid'
    remote_jid_alt = '5511444444444@c.us'
    item = _item('lid-log-sentinel')
    item['key']['remoteJid'] = remote_jid
    item['key']['remoteJidAlt'] = remote_jid_alt
    caplog.set_level(logging.INFO)

    process_evolution_channel_event(channel=channel, payload=_payload(item))

    rendered = ' '.join(record.getMessage() + repr(record.__dict__) for record in caplog.records)
    assert remote_jid not in rendered
    assert remote_jid_alt not in rendered


def test_inbound_processing_never_calls_external_http() -> None:
    channel = WhatsAppChannelFactory()
    with patch('requests.sessions.Session.request') as request:
        process_evolution_channel_event(channel=channel, payload=_payload(_item()))
    request.assert_not_called()
