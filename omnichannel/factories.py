from __future__ import annotations

import factory

from crm.models import Contact, Lead, Organization
from omnichannel.models import Conversation, Message
from workspaces.factories import UserFactory, WorkspaceFactory


class ContactFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Contact

    workspace = factory.SubFactory(WorkspaceFactory)
    name = factory.Faker('name')
    phone = factory.Sequence(lambda n: f'551199999{n:04d}')
    email = factory.Sequence(lambda n: f'contact{n}@example.com')
    contact_type = Contact.ContactType.LEAD
    custom_attributes = factory.LazyFunction(dict)


class LeadFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Lead

    contact = factory.SubFactory(ContactFactory)
    status = Lead.Status.NEW
    score = 0
    source = 'Manual'
    assigned_to = factory.SubFactory(UserFactory)
    notes = ''


class OrganizationFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Organization

    workspace = factory.SubFactory(WorkspaceFactory)
    name = factory.Sequence(lambda n: f'Organization {n}')


class ConversationFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Conversation

    workspace = factory.SubFactory(WorkspaceFactory)
    contact = factory.SubFactory(ContactFactory, workspace=factory.SelfAttribute('..workspace'))
    channel = 'whatsapp'
    status = Conversation.Status.OPEN


class MessageFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Message

    conversation = factory.SubFactory(ConversationFactory)
    body = factory.Faker('sentence')
    direction = Message.Direction.INBOUND
    status = Message.Status.DELIVERED
