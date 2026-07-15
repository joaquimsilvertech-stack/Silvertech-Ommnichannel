from __future__ import annotations

import pytest
from rest_framework import status

from crm.models import Contact, Lead, Organization
from omnichannel.factories import ContactFactory, LeadFactory, OrganizationFactory
from tests.security_helpers import (
    assert_not_found_or_forbidden,
    assert_response_does_not_contain,
    auth_client_for,
    make_user_with_membership,
)
from workspaces.factories import WorkspaceFactory
from workspaces.models import Member


def _results(payload):
    if isinstance(payload, dict) and 'results' in payload:
        return payload['results']
    return payload


@pytest.mark.django_db
def test_contact_list_filters_and_search_do_not_cross_workspace() -> None:
    workspace_a = WorkspaceFactory()
    workspace_b = WorkspaceFactory()
    owner_a = make_user_with_membership(workspace_a, Member.Role.OWNER)
    contact_a = ContactFactory(workspace=workspace_a, name='Cliente A', phone='5511111111111')
    contact_b = ContactFactory(
        workspace=workspace_b,
        name='Cliente B Secreto',
        phone='5522222222222',
        email='secret-b@example.com',
    )

    client = auth_client_for(owner_a)
    list_response = client.get('/api/crm/contacts/', {'workspace': str(workspace_b.id)})
    search_response = client.get('/api/crm/contacts/', {'search': 'Cliente B Secreto'})

    assert list_response.status_code == status.HTTP_200_OK
    assert search_response.status_code == status.HTTP_200_OK
    assert str(contact_a.id) not in list_response.content.decode('utf-8')
    assert str(contact_b.id) not in list_response.content.decode('utf-8')
    assert _results(search_response.json()) == []
    assert_response_does_not_contain(search_response, ['Cliente B Secreto', '5522222222222', 'secret-b@example.com'])


@pytest.mark.django_db
@pytest.mark.parametrize('method', ['get', 'patch', 'delete'])
def test_contact_detail_update_delete_other_workspace_is_blocked(method: str) -> None:
    workspace_a = WorkspaceFactory()
    workspace_b = WorkspaceFactory()
    owner_a = make_user_with_membership(workspace_a, Member.Role.OWNER)
    contact_b = ContactFactory(
        workspace=workspace_b,
        name='Contato B',
        phone='5522999999999',
        email='contato-b@example.com',
    )

    response = getattr(auth_client_for(owner_a), method)(
        f'/api/crm/contacts/{contact_b.id}/',
        {'name': 'Changed by A'},
        format='json',
    )

    assert_not_found_or_forbidden(response)
    contact_b.refresh_from_db()
    assert contact_b.name == 'Contato B'
    assert_response_does_not_contain(response, ['Contato B', '5522999999999', 'contato-b@example.com'])


@pytest.mark.django_db
def test_contact_create_cannot_force_other_workspace() -> None:
    workspace_a = WorkspaceFactory()
    workspace_b = WorkspaceFactory()
    owner_a = make_user_with_membership(workspace_a, Member.Role.OWNER)

    response = auth_client_for(owner_a).post(
        '/api/crm/contacts/',
        {
            'workspace_id': str(workspace_b.id),
            'name': 'Cross tenant contact',
            'phone': '+55 22 99999-9999',
            'email': 'cross@example.com',
            'contact_type': Contact.ContactType.LEAD,
        },
        format='json',
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert not Contact.objects.filter(workspace=workspace_b, email='cross@example.com').exists()


@pytest.mark.django_db
def test_lead_crud_and_search_do_not_cross_workspace() -> None:
    workspace_a = WorkspaceFactory()
    workspace_b = WorkspaceFactory()
    owner_a = make_user_with_membership(workspace_a, Member.Role.OWNER)
    contact_a = ContactFactory(workspace=workspace_a, name='Lead A')
    lead_b = LeadFactory(
        contact=ContactFactory(workspace=workspace_b, name='Lead B Secreto', email='lead-b@example.com'),
        notes='nota secreta B',
    )
    client = auth_client_for(owner_a)

    create_response = client.post(
        '/api/crm/leads/',
        {'contact_id': str(lead_b.contact_id), 'source': 'Cross tenant'},
        format='json',
    )
    search_response = client.get('/api/crm/leads/', {'search': 'Lead B Secreto'})
    retrieve_response = client.get(f'/api/crm/leads/{lead_b.id}/')
    update_response = client.patch(f'/api/crm/leads/{lead_b.id}/', {'notes': 'changed'}, format='json')
    own_create_response = client.post(
        '/api/crm/leads/',
        {'contact_id': str(contact_a.id), 'source': 'Own tenant'},
        format='json',
    )

    assert create_response.status_code == status.HTTP_400_BAD_REQUEST
    assert search_response.status_code == status.HTTP_200_OK
    assert _results(search_response.json()) == []
    assert_not_found_or_forbidden(retrieve_response)
    assert_not_found_or_forbidden(update_response)
    assert own_create_response.status_code == status.HTTP_201_CREATED
    lead_b.refresh_from_db()
    assert lead_b.notes == 'nota secreta B'
    assert_response_does_not_contain(search_response, ['Lead B Secreto', 'lead-b@example.com', 'nota secreta B'])


@pytest.mark.django_db
def test_organization_crud_filters_and_contact_payload_do_not_cross_workspace() -> None:
    workspace_a = WorkspaceFactory()
    workspace_b = WorkspaceFactory()
    owner_a = make_user_with_membership(workspace_a, Member.Role.OWNER)
    contact_b = ContactFactory(workspace=workspace_b, name='Contato org B')
    org_b = OrganizationFactory(workspace=workspace_b, name='Organizacao B Secreta')
    org_b.contacts.add(contact_b)
    client = auth_client_for(owner_a)

    create_response = client.post(
        '/api/crm/organizations/',
        {
            'workspace_id': str(workspace_a.id),
            'name': 'Org A invalid contact',
            'contact_ids': [str(contact_b.id)],
        },
        format='json',
    )
    filter_response = client.get('/api/crm/organizations/', {'workspace': str(workspace_b.id)})
    search_response = client.get('/api/crm/organizations/', {'search': 'Organizacao B Secreta'})
    retrieve_response = client.get(f'/api/crm/organizations/{org_b.id}/')
    delete_response = client.delete(f'/api/crm/organizations/{org_b.id}/')

    assert create_response.status_code == status.HTTP_400_BAD_REQUEST
    assert filter_response.status_code == status.HTTP_200_OK
    assert _results(filter_response.json()) == []
    assert _results(search_response.json()) == []
    assert_not_found_or_forbidden(retrieve_response)
    assert_not_found_or_forbidden(delete_response)
    org_b.refresh_from_db()
    assert org_b.name == 'Organizacao B Secreta'
    assert_response_does_not_contain(search_response, ['Organizacao B Secreta', 'Contato org B'])


@pytest.mark.django_db
def test_dashboard_metrics_cannot_be_requested_for_other_workspace() -> None:
    workspace_a = WorkspaceFactory()
    workspace_b = WorkspaceFactory(name='Workspace B Dashboard')
    owner_a = make_user_with_membership(workspace_a, Member.Role.OWNER)
    ContactFactory(workspace=workspace_b, name='Dashboard Contact B')

    response = auth_client_for(owner_a).get(f'/api/crm/dashboard/{workspace_b.id}/')

    assert_not_found_or_forbidden(response)
    assert_response_does_not_contain(response, ['Dashboard Contact B', 'Workspace B Dashboard'])
