from __future__ import annotations

import pytest
from django.db import IntegrityError, transaction

from crm.models import Contact
from workspaces.factories import WorkspaceFactory

pytestmark = pytest.mark.django_db


def _contact(*, workspace, channel_id, phone: str = '5511000000000') -> Contact:
    return Contact.objects.create(
        workspace=workspace,
        name='Contato de teste',
        phone=phone,
        channel_id=channel_id,
    )


def test_same_workspace_and_channel_id_cannot_be_duplicated() -> None:
    workspace = WorkspaceFactory()
    _contact(workspace=workspace, channel_id='5511000000001')

    with pytest.raises(IntegrityError), transaction.atomic():
        _contact(workspace=workspace, channel_id='5511000000001')


def test_same_channel_id_is_allowed_in_different_workspaces() -> None:
    first = _contact(workspace=WorkspaceFactory(), channel_id='5511000000002')
    second = _contact(workspace=WorkspaceFactory(), channel_id='5511000000002')

    assert first.workspace_id != second.workspace_id


def test_multiple_null_channel_ids_are_allowed() -> None:
    workspace = WorkspaceFactory()

    _contact(workspace=workspace, channel_id=None)
    _contact(workspace=workspace, channel_id=None)

    assert Contact.objects.filter(workspace=workspace, channel_id__isnull=True).count() == 2


def test_multiple_empty_channel_ids_are_allowed() -> None:
    workspace = WorkspaceFactory()

    _contact(workspace=workspace, channel_id='')
    _contact(workspace=workspace, channel_id='')

    assert Contact.objects.filter(workspace=workspace, channel_id='').count() == 2


def test_duplicate_phone_remains_allowed_without_identity_conflict() -> None:
    workspace = WorkspaceFactory()

    _contact(workspace=workspace, channel_id='identity-a', phone='5511000000003')
    _contact(workspace=workspace, channel_id='identity-b', phone='5511000000003')

    assert Contact.objects.filter(workspace=workspace, phone='5511000000003').count() == 2


def test_contact_identity_constraint_has_stable_name_and_condition() -> None:
    constraint = next(
        item
        for item in Contact._meta.constraints
        if item.name == 'crm_contact_unique_ws_channel_id'
    )

    assert tuple(constraint.fields) == ('workspace', 'channel_id')
    assert constraint.condition is not None
