from __future__ import annotations

import factory
from django.contrib.auth import get_user_model
from django.utils.text import slugify

from .models import Member, Workspace

User = get_user_model()


class UserFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = User
        django_get_or_create = ('email',)
        skip_postgeneration_save = True

    email = factory.Sequence(lambda n: f'user{n}@example.com')
    role = User.Role.AGENT
    is_active = True

    @factory.post_generation
    def password(self, create, extracted, **kwargs):
        raw_password = extracted or 'testpass123'
        self.set_password(raw_password)
        if create:
            self.save(update_fields=['password'])


class WorkspaceFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Workspace

    name = factory.Sequence(lambda n: f'Workspace {n}')
    slug = factory.LazyAttribute(lambda obj: slugify(obj.name))
    ai_system_prompt = 'Você é um assistente virtual prestativo da Silvertech.'


class MemberFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Member
        django_get_or_create = ('workspace', 'user')

    workspace = factory.SubFactory(WorkspaceFactory)
    user = factory.SubFactory(UserFactory)
    role = Member.Role.AGENT


MembershipFactory = MemberFactory
