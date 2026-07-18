from __future__ import annotations

from unittest.mock import Mock, patch
from uuid import uuid4

import pytest
from django.conf import settings
from django.core.cache import cache
from rest_framework import status
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import AccessToken

from omnichannel.evolution import (
    BaseEvolutionClient,
    EvolutionAuthenticationError,
    EvolutionConflictError,
    EvolutionInvalidRequestError,
    EvolutionTimeoutError,
    EvolutionUnavailableError,
)
from omnichannel.factories import WhatsAppChannelFactory
from omnichannel.models import WhatsAppChannel
from omnichannel.whatsapp_channel_provisioning import (
    SAFE_PROVISIONING_ERROR_MESSAGE,
    WhatsAppChannelProvisioningError,
)
from omnichannel.whatsapp_channel_views import WorkspaceWhatsAppChannelProvisioningView
from workspaces.factories import MemberFactory, UserFactory, WorkspaceFactory
from workspaces.models import Member

pytestmark = pytest.mark.django_db


def _url(workspace) -> str:
    return f'/api/workspaces/{workspace.id}/whatsapp-channels/'


def _client_for(user) -> APIClient:
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f'Bearer {AccessToken.for_user(user)}')
    return client


def _member_client(*, role: str = Member.Role.OWNER, workspace=None):
    user = UserFactory()
    workspace = workspace or WorkspaceFactory()
    MemberFactory(user=user, workspace=workspace, role=role)
    return _client_for(user), user, workspace


def _evolution_client(*, response: dict | None = None) -> Mock:
    client = Mock(spec=BaseEvolutionClient)
    client.create_instance.return_value = response if response is not None else {
        'instance': {'instanceId': 'safe-remote-id'},
        'hash': {'apikey': 'private-instance-token'},
        'qrcode': {'base64': 'private-qr', 'pairingCode': 'private-pairing'},
    }
    client.delete_instance.return_value = {}
    return client


def test_endpoint_requires_authentication() -> None:
    workspace = WorkspaceFactory()

    response = APIClient().post(_url(workspace), {'name': 'WhatsApp principal'}, format='json')

    assert response.status_code == status.HTTP_401_UNAUTHORIZED
    assert not WhatsAppChannel.objects.filter(workspace=workspace).exists()


@pytest.mark.parametrize('role', [Member.Role.OWNER, Member.Role.ADMIN])
def test_owner_and_admin_can_provision_channel(role: str) -> None:
    client, _, workspace = _member_client(role=role)
    evolution = _evolution_client()

    with patch(
        'omnichannel.whatsapp_channel_provisioning.get_evolution_client',
        return_value=evolution,
    ):
        response = client.post(_url(workspace), {'name': 'WhatsApp principal'}, format='json')

    assert response.status_code == status.HTTP_201_CREATED
    channel = WhatsAppChannel.objects.get(workspace=workspace)
    assert response.json()['id'] == str(channel.id)
    assert channel.status == WhatsAppChannel.Status.WAITING_QR
    evolution.create_instance.assert_called_once()


def test_superuser_can_provision_without_membership() -> None:
    user = UserFactory(is_superuser=True, is_staff=True)
    client = _client_for(user)
    workspace = WorkspaceFactory()
    evolution = _evolution_client()

    with patch(
        'omnichannel.whatsapp_channel_provisioning.get_evolution_client',
        return_value=evolution,
    ):
        response = client.post(_url(workspace), {'name': 'Canal superuser'}, format='json')

    assert response.status_code == status.HTTP_201_CREATED
    assert WhatsAppChannel.objects.filter(workspace=workspace).count() == 1


def test_agent_member_cannot_provision() -> None:
    client, _, workspace = _member_client(role=Member.Role.AGENT)

    with patch('omnichannel.whatsapp_channel_views.provision_whatsapp_channel') as provision:
        response = client.post(_url(workspace), {'name': 'Canal bloqueado'}, format='json')

    assert response.status_code == status.HTTP_403_FORBIDDEN
    provision.assert_not_called()


def test_non_member_cannot_provision() -> None:
    client = _client_for(UserFactory())
    workspace = WorkspaceFactory()

    with patch('omnichannel.whatsapp_channel_views.provision_whatsapp_channel') as provision:
        response = client.post(_url(workspace), {'name': 'Canal externo'}, format='json')

    assert response.status_code == status.HTTP_403_FORBIDDEN
    provision.assert_not_called()


def test_owner_of_workspace_a_cannot_provision_workspace_b() -> None:
    client, _, _ = _member_client(role=Member.Role.OWNER)
    workspace_b = WorkspaceFactory()

    with patch('omnichannel.whatsapp_channel_views.provision_whatsapp_channel') as provision:
        response = client.post(_url(workspace_b), {'name': 'Canal cruzado'}, format='json')

    assert response.status_code == status.HTTP_403_FORBIDDEN
    provision.assert_not_called()
    assert not WhatsAppChannel.objects.filter(workspace=workspace_b).exists()


def test_missing_workspace_does_not_provision() -> None:
    client = _client_for(UserFactory(is_superuser=True, is_staff=True))

    with patch('omnichannel.whatsapp_channel_views.provision_whatsapp_channel') as provision:
        response = client.post(
            f'/api/workspaces/{uuid4()}/whatsapp-channels/',
            {'name': 'Canal inexistente'},
            format='json',
        )

    assert response.status_code == status.HTTP_404_NOT_FOUND
    provision.assert_not_called()


@pytest.mark.parametrize(
    'payload',
    [
        {},
        {'name': ''},
        {'name': '   '},
        {'name': 'Canal\nmalicioso'},
        {'name': 'x' * 129},
        {'name': 123},
    ],
)
def test_invalid_channel_name_returns_400_without_provisioning(payload: dict) -> None:
    client, _, workspace = _member_client()

    with patch('omnichannel.whatsapp_channel_views.provision_whatsapp_channel') as provision:
        response = client.post(_url(workspace), payload, format='json')

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    provision.assert_not_called()


@pytest.mark.parametrize(
    ('field', 'value'),
    [
        ('workspace', str(uuid4())),
        ('workspace_id', str(uuid4())),
        ('provider', 'evolution'),
        ('instance_name', 'user-controlled-instance'),
        ('instance_id', 'user-controlled-id'),
        ('instance_token', 'user-controlled-token'),
        ('status', WhatsAppChannel.Status.CONNECTED),
        ('webhook_public_id', str(uuid4())),
        ('webhook_secret', 'user-controlled-secret'),
        ('phone_number', '5511999999999'),
        ('connected_at', '2026-01-01T00:00:00Z'),
        ('last_connection_update_at', '2026-01-01T00:00:00Z'),
        ('last_error_code', 'USER_CONTROLLED'),
    ],
)
def test_body_rejects_every_field_except_name(field: str, value: str) -> None:
    client, _, workspace = _member_client()
    payload = {'name': 'WhatsApp principal', field: value}

    with patch('omnichannel.whatsapp_channel_views.provision_whatsapp_channel') as provision:
        response = client.post(_url(workspace), payload, format='json')

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert field in response.json()
    provision.assert_not_called()
    assert not WhatsAppChannel.objects.filter(workspace=workspace).exists()


def test_channel_name_is_normalized_and_workspace_comes_only_from_url() -> None:
    client, _, workspace = _member_client()
    evolution = _evolution_client()

    with patch(
        'omnichannel.whatsapp_channel_provisioning.get_evolution_client',
        return_value=evolution,
    ):
        response = client.post(
            _url(workspace),
            {'name': '  WhatsApp   principal  '},
            format='json',
        )

    channel = WhatsAppChannel.objects.get()
    assert response.status_code == status.HTTP_201_CREATED
    assert channel.workspace_id == workspace.id
    assert channel.name == 'WhatsApp principal'


def test_success_response_exposes_only_safe_fields_and_never_qr_or_phone() -> None:
    client, _, workspace = _member_client()
    evolution = _evolution_client()

    with patch(
        'omnichannel.whatsapp_channel_provisioning.get_evolution_client',
        return_value=evolution,
    ):
        response = client.post(_url(workspace), {'name': 'Canal seguro'}, format='json')

    assert response.status_code == status.HTTP_201_CREATED
    payload = response.json()
    assert set(payload) == {
        'id',
        'name',
        'provider',
        'status',
        'created_at',
        'updated_at',
    }
    assert payload['provider'] == WhatsAppChannel.Provider.EVOLUTION
    assert payload['status'] == WhatsAppChannel.Status.WAITING_QR
    serialized = response.content.decode('utf-8')
    for forbidden in (
        'instance_name',
        'instance_id',
        'instance_token',
        'webhook_public_id',
        'webhook_secret',
        'phone_number',
        'last_error_code',
        'private-instance-token',
        'private-qr',
        'private-pairing',
        'pairingCode',
        'base64',
    ):
        assert forbidden not in serialized


def test_second_equal_request_returns_200_and_does_not_call_evolution_again() -> None:
    client, _, workspace = _member_client()
    evolution = _evolution_client()

    with patch(
        'omnichannel.whatsapp_channel_provisioning.get_evolution_client',
        return_value=evolution,
    ):
        first = client.post(_url(workspace), {'name': 'Canal idempotente'}, format='json')
        second = client.post(_url(workspace), {'name': 'Canal idempotente'}, format='json')

    assert first.status_code == status.HTTP_201_CREATED
    assert second.status_code == status.HTTP_200_OK
    assert first.json()['id'] == second.json()['id']
    assert WhatsAppChannel.objects.filter(workspace=workspace).count() == 1
    evolution.create_instance.assert_called_once()


@pytest.mark.parametrize(
    ('error', 'expected_status'),
    [
        (EvolutionAuthenticationError(), status.HTTP_503_SERVICE_UNAVAILABLE),
        (EvolutionTimeoutError(), status.HTTP_504_GATEWAY_TIMEOUT),
        (EvolutionUnavailableError(), status.HTTP_503_SERVICE_UNAVAILABLE),
        (EvolutionConflictError(), status.HTTP_409_CONFLICT),
        (EvolutionInvalidRequestError(), status.HTTP_502_BAD_GATEWAY),
    ],
)
def test_evolution_failure_returns_safe_http_status_and_error_payload(
    error: Exception,
    expected_status: int,
) -> None:
    client, _, workspace = _member_client()
    evolution = _evolution_client()
    evolution.create_instance.side_effect = error

    with patch(
        'omnichannel.whatsapp_channel_provisioning.get_evolution_client',
        return_value=evolution,
    ):
        response = client.post(_url(workspace), {'name': 'Canal com falha'}, format='json')

    assert response.status_code == expected_status
    payload = response.json()
    assert payload['detail'] == SAFE_PROVISIONING_ERROR_MESSAGE
    assert payload['error_code'].startswith('EVOLUTION_')
    assert set(payload['channel']) == {
        'id',
        'name',
        'provider',
        'status',
        'created_at',
        'updated_at',
    }
    assert payload['channel']['status'] == WhatsAppChannel.Status.ERROR
    serialized = response.content.decode('utf-8')
    assert str(error) not in serialized
    assert 'instance_token' not in serialized
    assert 'qrcode' not in serialized.lower()
    assert 'private-qr' not in serialized


def test_operational_error_without_channel_returns_safe_minimal_payload() -> None:
    client, _, workspace = _member_client()

    with patch(
        'omnichannel.whatsapp_channel_views.provision_whatsapp_channel',
        side_effect=WhatsAppChannelProvisioningError(
            error_code='INSTANCE_NAME_GENERATION_FAILED',
            http_status=503,
        ),
    ):
        response = client.post(_url(workspace), {'name': 'Canal indisponivel'}, format='json')

    assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
    assert response.json() == {
        'detail': SAFE_PROVISIONING_ERROR_MESSAGE,
        'error_code': 'INSTANCE_NAME_GENERATION_FAILED',
    }


def test_same_name_in_two_authorized_workspaces_creates_isolated_channels() -> None:
    client, user, workspace_a = _member_client()
    workspace_b = WorkspaceFactory()
    MemberFactory(user=user, workspace=workspace_b, role=Member.Role.OWNER)
    evolution = _evolution_client(response={})

    with patch(
        'omnichannel.whatsapp_channel_provisioning.get_evolution_client',
        return_value=evolution,
    ):
        response_a = client.post(_url(workspace_a), {'name': 'Mesmo nome'}, format='json')
        response_b = client.post(_url(workspace_b), {'name': 'Mesmo nome'}, format='json')

    assert response_a.status_code == status.HTTP_201_CREATED
    assert response_b.status_code == status.HTTP_201_CREATED
    assert response_a.json()['id'] != response_b.json()['id']
    assert WhatsAppChannel.objects.filter(workspace=workspace_a).count() == 1
    assert WhatsAppChannel.objects.filter(workspace=workspace_b).count() == 1


def test_failure_in_one_workspace_does_not_change_other_workspace_channel() -> None:
    client, _, workspace_a = _member_client()
    workspace_b = WorkspaceFactory()
    untouched = WhatsAppChannelFactory(
        workspace=workspace_b,
        status=WhatsAppChannel.Status.CONNECTED,
        instance_token='other-workspace-token',
    )
    evolution = _evolution_client()
    evolution.create_instance.side_effect = EvolutionTimeoutError()

    with patch(
        'omnichannel.whatsapp_channel_provisioning.get_evolution_client',
        return_value=evolution,
    ):
        response = client.post(_url(workspace_a), {'name': 'Canal falho'}, format='json')

    untouched.refresh_from_db()
    assert response.status_code == status.HTTP_504_GATEWAY_TIMEOUT
    assert untouched.status == WhatsAppChannel.Status.CONNECTED
    assert untouched.instance_token == 'other-workspace-token'


def test_provisioning_endpoint_has_dedicated_throttle_configuration() -> None:
    assert (
        WorkspaceWhatsAppChannelProvisioningView.throttle_scope
        == 'whatsapp_channel_provisioning'
    )
    assert (
        settings.REST_FRAMEWORK['DEFAULT_THROTTLE_RATES']['whatsapp_channel_provisioning']
        == '3/minute'
    )


def test_provisioning_endpoint_returns_429_after_three_requests() -> None:
    cache.clear()
    client, _, workspace = _member_client()
    evolution = _evolution_client(response={})

    responses = []
    with patch(
        'omnichannel.whatsapp_channel_provisioning.get_evolution_client',
        return_value=evolution,
    ):
        for index in range(4):
            responses.append(
                client.post(
                    _url(workspace),
                    {'name': f'Canal throttle {index}'},
                    format='json',
                    REMOTE_ADDR='198.51.100.20',
                ),
            )

    assert [response.status_code for response in responses[:3]] == [201, 201, 201]
    assert responses[3].status_code == status.HTTP_429_TOO_MANY_REQUESTS
    assert evolution.create_instance.call_count == 3


@pytest.mark.parametrize('method', ['put', 'patch', 'delete'])
def test_endpoint_does_not_offer_update_or_delete(method: str) -> None:
    client, _, workspace = _member_client()

    response = getattr(client, method)(
        _url(workspace),
        {'name': 'Nao permitido'},
        format='json',
    )

    assert response.status_code == status.HTTP_405_METHOD_NOT_ALLOWED


def test_endpoint_does_not_offer_retrieve_route() -> None:
    client, _, workspace = _member_client()

    response = client.get(f'{_url(workspace)}{uuid4()}/')

    assert response.status_code == status.HTTP_404_NOT_FOUND


def test_head_and_options_are_allowed_without_provisioning() -> None:
    client, _, workspace = _member_client()

    with patch('omnichannel.whatsapp_channel_views.provision_whatsapp_channel') as provision:
        head_response = client.head(_url(workspace))
        options_response = client.options(_url(workspace))

    assert head_response.status_code == status.HTTP_200_OK
    assert options_response.status_code == status.HTTP_200_OK
    provision.assert_not_called()
