from __future__ import annotations

import factory
from django.contrib.auth import get_user_model

from .models import Member, Workspace, WorkspaceInvite

User = get_user_model()


class UserFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = User
        django_get_or_create = ('email',)
        skip_postgeneration_save = True

    email = factory.Sequence(lambda n: f'user{n}@example.com')
    first_name = factory.Faker('first_name')
    last_name = factory.Faker('last_name')
    role = User.Role.AGENT

    @factory.post_generation
    def password(self, create, extracted, **kwargs):
        self.set_password(extracted or 'test-pass-123')
        if create:
            self.save()


class WorkspaceFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Workspace

    name = factory.Sequence(lambda n: f'Workspace {n}')
    slug = factory.Sequence(lambda n: f'workspace-{n}')


class MemberFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Member

    workspace = factory.SubFactory(WorkspaceFactory)
    user = factory.SubFactory(UserFactory)
    role = Member.Role.OWNER


class WorkspaceInviteFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = WorkspaceInvite

    email = factory.Sequence(lambda n: f'invite{n}@example.com')
    workspace = factory.SubFactory(WorkspaceFactory)
    invited_by = factory.SubFactory(UserFactory)
    role = WorkspaceInvite.Role.AGENT
    expires_at = factory.Faker('future_datetime', tzinfo=None)
