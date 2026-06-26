from __future__ import annotations

import factory

from crm.models import Contact, Lead
from workspaces.factories import WorkspaceFactory


class ContactFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Contact

    workspace = factory.SubFactory(WorkspaceFactory)
    name = factory.Faker('name')
    phone = factory.Faker('phone_number')
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
    notes = factory.Faker('sentence')
