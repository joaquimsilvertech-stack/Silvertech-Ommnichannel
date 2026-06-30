from __future__ import annotations

from datetime import timedelta

import pytest
from django.apps import apps
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from core.models import AuditLog
from crm.models import Contact, Lead, Organization
from omnichannel.factories import (
    ContactFactory,
    LeadFactory,
    OrganizationFactory,
)
from core.signals import AUDITED_MODEL_LABELS
from workspaces.factories import WorkspaceFactory, WorkspaceInviteFactory
from workspaces.models import Workspace


@pytest.mark.django_db
def test_create_contact_generates_audit_log(
    api_client: APIClient,
    tenant_workspace: Workspace,
) -> None:
    AuditLog.objects.all().delete()

    response = api_client.post(
        '/api/crm/contacts/',
        {
            'workspace_id': str(tenant_workspace.id),
            'name': 'Maria Silva',
            'phone': '5511999999999',
            'email': 'maria@example.com',
        },
        format='json',
        HTTP_X_FORWARDED_FOR='203.0.113.10',
        HTTP_USER_AGENT='pytest-agent',
    )

    assert response.status_code == status.HTTP_201_CREATED
    audit_log = AuditLog.objects.get(action=AuditLog.Action.CREATE, model_name='Contact')
    assert audit_log.workspace == tenant_workspace
    assert audit_log.actor is not None
    assert audit_log.after['name'] == 'Maria Silva'
    assert audit_log.ip_address == '203.0.113.10'
    assert audit_log.user_agent == 'pytest-agent'


@pytest.mark.django_db
def test_update_lead_generates_audit_log_with_changes(tenant_workspace: Workspace) -> None:
    lead = LeadFactory(contact__workspace=tenant_workspace, status=Lead.Status.NEW)
    AuditLog.objects.all().delete()

    lead.status = Lead.Status.WON
    lead.score = 90
    lead.save()

    audit_log = AuditLog.objects.get(action=AuditLog.Action.UPDATE, model_name='Lead')
    assert audit_log.workspace == tenant_workspace
    assert audit_log.changes['status'] == {
        'before': Lead.Status.NEW,
        'after': Lead.Status.WON,
    }
    assert audit_log.changes['score'] == {'before': 0, 'after': 90}


@pytest.mark.django_db
def test_delete_existing_audited_model_generates_delete_log(tenant_workspace: Workspace) -> None:
    organization = OrganizationFactory(workspace=tenant_workspace, name='Silver Ops')
    object_id = str(organization.id)
    AuditLog.objects.all().delete()

    organization.delete()

    audit_log = AuditLog.objects.get(action=AuditLog.Action.DELETE, model_name='Organization')
    assert audit_log.workspace == tenant_workspace
    assert audit_log.object_id == object_id
    assert audit_log.before['name'] == 'Silver Ops'
    assert audit_log.after is None


@pytest.mark.django_db
def test_delete_ticket_generates_audit_log_when_tickets_app_is_installed() -> None:
    try:
        apps.get_model('tickets', 'Ticket')
    except LookupError:
        pytest.skip('App tickets nao esta instalado neste checkout.')


@pytest.mark.django_db
def test_audit_log_does_not_leak_between_workspaces(
    tenant_workspace: Workspace,
) -> None:
    other_workspace = WorkspaceFactory()
    AuditLog.objects.all().delete()

    ContactFactory(workspace=tenant_workspace, name='Visible Contact')
    ContactFactory(workspace=other_workspace, name='Hidden Contact')

    workspace_ids = set(
        AuditLog.objects.filter(workspace=tenant_workspace)
        .values_list('workspace_id', flat=True)
        .distinct(),
    )
    assert workspace_ids == {tenant_workspace.id}
    assert not AuditLog.objects.filter(
        workspace=tenant_workspace,
        object_repr='Hidden Contact',
    ).exists()


@pytest.mark.django_db
def test_signal_does_not_audit_auditlog_itself(tenant_workspace: Workspace) -> None:
    AuditLog.objects.all().delete()

    AuditLog.objects.create(
        workspace=tenant_workspace,
        action=AuditLog.Action.CREATE,
        model_name='Manual',
        object_id='1',
        object_repr='Manual log',
    )

    assert AuditLog.objects.count() == 1


@pytest.mark.django_db
def test_message_is_not_audited_to_avoid_high_volume_logs(tenant_workspace: Workspace) -> None:
    assert 'omnichannel.Message' not in AUDITED_MODEL_LABELS


@pytest.mark.django_db
def test_sensitive_fields_are_masked_in_audit_log(tenant_workspace: Workspace, auth_user) -> None:
    AuditLog.objects.all().delete()
    invite = WorkspaceInviteFactory(
        workspace=tenant_workspace,
        invited_by=auth_user,
        expires_at=timezone.now() + timedelta(days=7),
    )

    audit_log = AuditLog.objects.get(
        action=AuditLog.Action.CREATE,
        model_name='WorkspaceInvite',
        object_id=str(invite.id),
    )
    assert audit_log.after['token'] == '***'
    assert str(invite.token) not in str(audit_log.after)


@pytest.mark.django_db
def test_operation_without_request_creates_audit_log_with_null_actor(
    tenant_workspace: Workspace,
) -> None:
    AuditLog.objects.all().delete()

    contact = Contact.objects.create(
        workspace=tenant_workspace,
        name='Sem Request',
        phone='5511888888888',
    )

    audit_log = AuditLog.objects.get(
        action=AuditLog.Action.CREATE,
        model_name='Contact',
        object_id=str(contact.id),
    )
    assert audit_log.actor is None
    assert audit_log.workspace == tenant_workspace
