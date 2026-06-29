from __future__ import annotations

import pytest
from rest_framework import status
from rest_framework.test import APIClient

from crm.models import Contact, Lead
from omnichannel.factories import ContactFactory, LeadFactory
from workspaces.models import Workspace


def _results(response_data):
    if isinstance(response_data, dict) and 'results' in response_data:
        return response_data['results']
    return response_data


@pytest.mark.django_db
def test_create_contact_success(api_client: APIClient, tenant_workspace: Workspace) -> None:
    payload = {
        'workspace_id': str(tenant_workspace.id),
        'name': 'Cliente Teste',
        'phone': '+55 11 99999-0000',
        'email': 'cliente@example.com',
        'contact_type': Contact.ContactType.LEAD,
    }

    response = api_client.post('/api/crm/contacts/', payload, format='json')

    assert response.status_code == status.HTTP_201_CREATED
    assert Contact.objects.filter(
        workspace=tenant_workspace,
        phone=payload['phone'],
    ).exists()


@pytest.mark.django_db
def test_create_contact_invalid_phone(api_client: APIClient, tenant_workspace: Workspace) -> None:
    payload = {
        'workspace_id': str(tenant_workspace.id),
        'name': 'Telefone Invalido',
        'phone': 'abcde',
        'email': 'telefone-invalido@example.com',
        'contact_type': Contact.ContactType.LEAD,
    }

    response = api_client.post('/api/crm/contacts/', payload, format='json')

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert 'phone' in response.json()


@pytest.mark.django_db
def test_user_cannot_see_other_tenant_contacts(api_client: APIClient, auth_user) -> None:
    ContactFactory()

    response = api_client.get('/api/crm/contacts/')

    assert response.status_code == status.HTTP_200_OK
    assert _results(response.json()) == []


@pytest.mark.django_db
def test_create_lead_success(api_client: APIClient, tenant_workspace: Workspace) -> None:
    contact = ContactFactory(workspace=tenant_workspace)
    payload = {
        'contact_id': str(contact.id),
        'status': Lead.Status.NEW,
        'source': 'Teste automatizado',
        'notes': 'Lead criado pela suite de regressao.',
    }

    response = api_client.post('/api/crm/leads/', payload, format='json')

    assert response.status_code == status.HTTP_201_CREATED
    assert Lead.objects.filter(contact=contact, source=payload['source']).exists()


@pytest.mark.django_db
def test_user_cannot_see_other_tenant_leads(api_client: APIClient, auth_user) -> None:
    LeadFactory()

    response = api_client.get('/api/crm/leads/')

    assert response.status_code == status.HTTP_200_OK
    assert _results(response.json()) == []
