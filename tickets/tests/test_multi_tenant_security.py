from __future__ import annotations

import pytest
from rest_framework import status

from omnichannel.factories import ContactFactory, ConversationFactory
from tests.security_helpers import (
    assert_not_found_or_forbidden,
    assert_response_does_not_contain,
    auth_client_for,
    make_user_with_membership,
)
from tickets.models import Ticket
from workspaces.factories import UserFactory, WorkspaceFactory
from workspaces.models import Member


@pytest.mark.django_db
def test_ticket_list_and_filters_do_not_cross_workspace() -> None:
    workspace_a = WorkspaceFactory()
    workspace_b = WorkspaceFactory()
    owner_a = make_user_with_membership(workspace_a, Member.Role.OWNER)
    ticket_a = Ticket.objects.create(
        workspace=workspace_a,
        contact=ContactFactory(workspace=workspace_a),
        title='Ticket A',
        status=Ticket.Status.OPEN,
    )
    ticket_b = Ticket.objects.create(
        workspace=workspace_b,
        contact=ContactFactory(workspace=workspace_b),
        title='Ticket B Secreto',
        status=Ticket.Status.OPEN,
    )

    response = auth_client_for(owner_a).get('/api/tickets/tickets/', {'status': Ticket.Status.OPEN})

    assert response.status_code == status.HTTP_200_OK
    body = response.content.decode('utf-8')
    assert str(ticket_a.id) in body
    assert str(ticket_b.id) not in body
    assert 'Ticket B Secreto' not in body


@pytest.mark.django_db
@pytest.mark.parametrize('method', ['get', 'patch', 'delete'])
def test_ticket_detail_update_delete_other_workspace_is_blocked(method: str) -> None:
    workspace_a = WorkspaceFactory()
    workspace_b = WorkspaceFactory()
    owner_a = make_user_with_membership(workspace_a, Member.Role.OWNER)
    ticket_b = Ticket.objects.create(
        workspace=workspace_b,
        contact=ContactFactory(workspace=workspace_b),
        title='Ticket B Secreto',
    )

    response = getattr(auth_client_for(owner_a), method)(
        f'/api/tickets/tickets/{ticket_b.id}/',
        {'title': 'Changed'},
        format='json',
    )

    assert_not_found_or_forbidden(response)
    ticket_b.refresh_from_db()
    assert ticket_b.title == 'Ticket B Secreto'
    assert_response_does_not_contain(response, ['Ticket B Secreto', str(workspace_b.id)])


@pytest.mark.django_db
def test_ticket_create_cannot_force_other_workspace_or_foreign_relations() -> None:
    workspace_a = WorkspaceFactory()
    workspace_b = WorkspaceFactory()
    owner_a = make_user_with_membership(workspace_a, Member.Role.OWNER)
    contact_b = ContactFactory(workspace=workspace_b)
    conversation_b = ConversationFactory(workspace=workspace_b, contact=contact_b)
    assigned_b = UserFactory()
    Member.objects.create(user=assigned_b, workspace=workspace_b, role=Member.Role.AGENT)

    response = auth_client_for(owner_a).post(
        '/api/tickets/tickets/',
        {
            'workspace_id': str(workspace_b.id),
            'contact_id': str(contact_b.id),
            'conversation_id': str(conversation_b.id),
            'assigned_to_id': str(assigned_b.id),
            'title': 'Cross tenant ticket',
        },
        format='json',
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert not Ticket.objects.filter(workspace=workspace_b, title='Cross tenant ticket').exists()
    assert_response_does_not_contain(response, ['Cross tenant ticket'])


@pytest.mark.django_db
def test_ticket_create_keeps_relations_inside_current_workspace() -> None:
    workspace_a = WorkspaceFactory()
    workspace_b = WorkspaceFactory()
    owner_a = make_user_with_membership(workspace_a, Member.Role.OWNER)
    contact_a = ContactFactory(workspace=workspace_a)
    conversation_a = ConversationFactory(workspace=workspace_a, contact=contact_a)
    contact_b = ContactFactory(workspace=workspace_b)

    invalid_response = auth_client_for(owner_a).post(
        '/api/tickets/tickets/',
        {
            'workspace_id': str(workspace_a.id),
            'contact_id': str(contact_b.id),
            'conversation_id': str(conversation_a.id),
            'title': 'Mixed tenant ticket',
        },
        format='json',
    )
    valid_response = auth_client_for(owner_a).post(
        '/api/tickets/tickets/',
        {
            'workspace_id': str(workspace_a.id),
            'contact_id': str(contact_a.id),
            'conversation_id': str(conversation_a.id),
            'title': 'Own tenant ticket',
        },
        format='json',
    )

    assert invalid_response.status_code == status.HTTP_400_BAD_REQUEST
    assert valid_response.status_code == status.HTTP_201_CREATED
    assert Ticket.objects.filter(workspace=workspace_a, title='Own tenant ticket').exists()
    assert not Ticket.objects.filter(workspace=workspace_b, title='Mixed tenant ticket').exists()
