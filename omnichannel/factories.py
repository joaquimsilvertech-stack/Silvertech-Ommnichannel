from __future__ import annotations

import factory

from crm.models import Contact, Lead, Organization
from omnichannel.models import (
    Conversation,
    EvolutionWebhookEvent,
    Message,
    WhatsAppChannel,
)
from workspaces.factories import UserFactory, WorkspaceFactory


class ContactFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Contact

    workspace = factory.SubFactory(WorkspaceFactory)
    name = factory.Faker('name')
    phone = factory.Sequence(lambda n: f'5511{900000000 + n:09d}')
    email = factory.Faker('email')
    channel_id = factory.Sequence(lambda n: f'whatsapp-{n}')
    contact_type = Contact.ContactType.LEAD
    custom_attributes = factory.Dict({})


class LeadFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Lead

    contact = factory.SubFactory(ContactFactory)
    status = Lead.Status.NEW
    score = 0
    source = 'Teste automatizado'
    assigned_to = factory.SubFactory(UserFactory)
    notes = factory.Faker('sentence')


class OrganizationFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Organization

    workspace = factory.SubFactory(WorkspaceFactory)
    name = factory.Sequence(lambda n: f'Organization {n}')


class WhatsAppChannelFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = WhatsAppChannel

    workspace = factory.SubFactory(WorkspaceFactory)
    provider = WhatsAppChannel.Provider.EVOLUTION
    name = factory.Sequence(lambda n: f'WhatsApp teste {n}')
    instance_name = factory.Sequence(lambda n: f'silvertech-test-{n}')
    instance_id = ''
    instance_token = ''
    webhook_secret = ''
    status = WhatsAppChannel.Status.DISCONNECTED
    phone_number = ''


class ConversationFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Conversation

    workspace = factory.SubFactory(WorkspaceFactory)
    contact = factory.SubFactory(ContactFactory, workspace=factory.SelfAttribute('..workspace'))
    whatsapp_channel = None
    channel = 'whatsapp'
    status = Conversation.Status.OPEN

    class Params:
        with_whatsapp_channel = factory.Trait(
            whatsapp_channel=factory.SubFactory(
                WhatsAppChannelFactory,
                workspace=factory.SelfAttribute('..workspace'),
            ),
        )


class MessageFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Message

    conversation = factory.SubFactory(ConversationFactory)
    body = factory.Faker('sentence')
    direction = Message.Direction.INBOUND
    status = Message.Status.DELIVERED


class EvolutionWebhookEventFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = EvolutionWebhookEvent

    whatsapp_channel = factory.SubFactory(WhatsAppChannelFactory)
    event_type = 'MESSAGES_UPSERT'
    deduplication_key = factory.Sequence(lambda n: f'{n:064x}')
    external_id = ''
    status = EvolutionWebhookEvent.Status.PROCESSING
