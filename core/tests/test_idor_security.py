from __future__ import annotations

import pytest

from automations.models import Flow
from omnichannel.factories import ContactFactory, ConversationFactory
from tests.security_helpers import (
    assert_not_found_or_forbidden,
    assert_response_does_not_contain,
    auth_client_for,
    make_user_with_membership,
)
from tickets.models import Ticket
from workspaces.factories import WorkspaceAIProviderConfigFactory, WorkspaceFactory
from workspaces.models import Member


@pytest.mark.django_db
def test_idor_ai_provider_pk_from_workspace_b_on_workspace_a_url_is_blocked() -> None:
    workspace_a = WorkspaceFactory()
    workspace_b = WorkspaceFactory()
    owner_a = make_user_with_membership(workspace_a, Member.Role.OWNER)
    provider_b = WorkspaceAIProviderConfigFactory(
        workspace=workspace_b,
        api_key='sk-provider-b-secret',
        model_name='provider-b-model',
    )

    response = auth_client_for(owner_a).get(
        f'/api/workspaces/{workspace_a.id}/ai-providers/{provider_b.id}/',
    )

    assert_not_found_or_forbidden(response)
    assert_response_does_not_contain(response, ['provider-b-model', 'sk-provider-b-secret'])


@pytest.mark.django_db
def test_idor_crm_contact_pk_from_workspace_b_is_blocked() -> None:
    workspace_a = WorkspaceFactory()
    workspace_b = WorkspaceFactory()
    owner_a = make_user_with_membership(workspace_a, Member.Role.OWNER)
    contact_b = ContactFactory(
        workspace=workspace_b,
        name='IDOR Contact B',
        phone='5522999999999',
        email='idor-b@example.com',
    )

    response = auth_client_for(owner_a).get(f'/api/crm/contacts/{contact_b.id}/')

    assert_not_found_or_forbidden(response)
    assert_response_does_not_contain(response, ['IDOR Contact B', '5522999999999', 'idor-b@example.com'])


@pytest.mark.django_db
def test_idor_conversation_pk_from_workspace_b_is_blocked() -> None:
    workspace_a = WorkspaceFactory()
    workspace_b = WorkspaceFactory()
    owner_a = make_user_with_membership(workspace_a, Member.Role.OWNER)
    conversation_b = ConversationFactory(
        workspace=workspace_b,
        contact__name='IDOR Conversation B',
        contact__phone='5522888888888',
    )

    response = auth_client_for(owner_a).get(f'/api/omnichannel/conversations/{conversation_b.id}/')

    assert_not_found_or_forbidden(response)
    assert_response_does_not_contain(response, ['IDOR Conversation B', '5522888888888'])


@pytest.mark.django_db
def test_idor_ticket_pk_from_workspace_b_is_blocked_without_side_effect() -> None:
    workspace_a = WorkspaceFactory()
    workspace_b = WorkspaceFactory()
    owner_a = make_user_with_membership(workspace_a, Member.Role.OWNER)
    ticket_b = Ticket.objects.create(
        workspace=workspace_b,
        contact=ContactFactory(workspace=workspace_b),
        title='IDOR Ticket B',
    )

    response = auth_client_for(owner_a).patch(
        f'/api/tickets/tickets/{ticket_b.id}/',
        {'title': 'Changed by A'},
        format='json',
    )

    assert_not_found_or_forbidden(response)
    ticket_b.refresh_from_db()
    assert ticket_b.title == 'IDOR Ticket B'
    assert_response_does_not_contain(response, ['IDOR Ticket B'])


@pytest.mark.django_db
def test_idor_flow_pk_from_workspace_b_is_blocked_without_side_effect() -> None:
    workspace_a = WorkspaceFactory()
    workspace_b = WorkspaceFactory()
    owner_a = make_user_with_membership(workspace_a, Member.Role.OWNER)
    flow_b = Flow.objects.create(workspace=workspace_b, name='IDOR Flow B')

    response = auth_client_for(owner_a).delete(f'/api/automations/flows/{flow_b.id}/')

    assert_not_found_or_forbidden(response)
    assert Flow.objects.filter(id=flow_b.id, name='IDOR Flow B').exists()
    assert_response_does_not_contain(response, ['IDOR Flow B'])
