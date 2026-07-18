from __future__ import annotations

from unittest.mock import Mock, patch
from uuid import uuid4

import pytest
from django.conf import settings as django_settings
from django.core.cache import cache
from django.test import override_settings
from rest_framework import status
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import AccessToken

from omnichannel.evolution import BaseEvolutionClient
from omnichannel.evolution_qr_cache import get_evolution_qr_code, store_evolution_qr_code
from omnichannel.factories import WhatsAppChannelFactory
from omnichannel.models import WhatsAppChannel
from omnichannel.whatsapp_channel_read_service import mask_whatsapp_phone_number
from omnichannel.whatsapp_channel_views import WorkspaceWhatsAppChannelCollectionView
from workspaces.factories import MemberFactory, UserFactory, WorkspaceFactory
from workspaces.models import Member

pytestmark = pytest.mark.django_db

PUBLIC_FIELDS = {
    'id',
    'name',
    'provider',
    'status',
    'phone_number_masked',
    'has_qr_code',
    'connected_at',
    'last_connection_update_at',
    'created_at',
    'updated_at',
}
RAW_QR = 'R' * 128


@pytest.fixture(autouse=True)
def clear_channel_cache():
    cache.clear()
    yield
    cache.clear()


def _client_for(user) -> APIClient:
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f'Bearer {AccessToken.for_user(user)}')
    return client


def _member_client(*, role: str = Member.Role.OWNER, workspace=None):
    user = UserFactory()
    workspace = workspace or WorkspaceFactory()
    MemberFactory(user=user, workspace=workspace, role=role)
    return _client_for(user), user, workspace


def _list_url(workspace) -> str:
    return f'/api/workspaces/{workspace.id}/whatsapp-channels/'


def _detail_url(workspace, channel) -> str:
    return f'{_list_url(workspace)}{channel.id}/'


def _sensitive_channel(*, workspace, **kwargs):
    defaults = {
        'workspace': workspace,
        'instance_name': f'private-instance-{uuid4().hex}',
        'instance_id': 'private-instance-id',
        'instance_token': 'private-instance-token',
        'webhook_secret': 'private-webhook-secret',
        'phone_number': '5511999991234',
        'last_error_code': 'PRIVATE_LAST_ERROR',
    }
    defaults.update(kwargs)
    return WhatsAppChannelFactory(**defaults)


def test_list_requires_authentication() -> None:
    workspace = WorkspaceFactory()
    response = APIClient().get(_list_url(workspace))
    assert response.status_code == status.HTTP_401_UNAUTHORIZED


@pytest.mark.parametrize('role', [Member.Role.OWNER, Member.Role.ADMIN])
def test_owner_and_admin_can_list_channels(role: str) -> None:
    client, _, workspace = _member_client(role=role)
    channel = WhatsAppChannelFactory(workspace=workspace)
    response = client.get(_list_url(workspace))
    assert response.status_code == status.HTTP_200_OK
    assert response.json()[0]['id'] == str(channel.id)


def test_superuser_can_list_without_membership() -> None:
    user = UserFactory(is_superuser=True, is_staff=True)
    workspace = WorkspaceFactory()
    WhatsAppChannelFactory(workspace=workspace)
    response = _client_for(user).get(_list_url(workspace))
    assert response.status_code == status.HTTP_200_OK
    assert len(response.json()) == 1


@pytest.mark.parametrize('access_kind', ['agent', 'non_member'])
def test_agent_and_non_member_cannot_list(access_kind: str) -> None:
    workspace = WorkspaceFactory()
    if access_kind == 'agent':
        client, _, _ = _member_client(role=Member.Role.AGENT, workspace=workspace)
    else:
        client = _client_for(UserFactory())
    response = client.get(_list_url(workspace))
    assert response.status_code == status.HTTP_403_FORBIDDEN


def test_list_is_workspace_scoped_and_stably_ordered() -> None:
    client, _, workspace = _member_client()
    second = WhatsAppChannelFactory(workspace=workspace, name='Beta')
    first = WhatsAppChannelFactory(workspace=workspace, name='Alpha')
    other = WhatsAppChannelFactory(name='Alpha')

    response = client.get(
        f'{_list_url(workspace)}?workspace_id={other.workspace_id}&channel_id={other.id}'
        f'&instance_name={other.instance_name}',
    )

    assert response.status_code == status.HTTP_200_OK
    assert [item['id'] for item in response.json()] == [str(first.id), str(second.id)]
    assert str(other.id) not in response.content.decode()


def test_list_uses_only_public_fields_and_masks_phone() -> None:
    client, _, workspace = _member_client()
    channel = _sensitive_channel(workspace=workspace, status=WhatsAppChannel.Status.CONNECTED)

    response = client.get(_list_url(workspace))

    payload = response.json()[0]
    serialized = response.content.decode()
    assert set(payload) == PUBLIC_FIELDS
    assert payload['phone_number_masked'] == '********1234'
    for secret in (
        channel.phone_number,
        channel.instance_name,
        channel.instance_id,
        channel.instance_token,
        channel.webhook_secret,
        channel.last_error_code,
        str(channel.webhook_public_id),
    ):
        assert secret not in serialized


@pytest.mark.parametrize(
    ('phone', 'expected'),
    [
        ('5511999991234', '********1234'),
        ('12345678', '********5678'),
        ('', None),
        (None, None),
        ('123', None),
        ('55119999@s.whatsapp.net', None),
        ('+5511999991234', None),
        ({'phone': '5511999991234'}, None),
    ],
)
def test_phone_mask_is_fixed_and_defensive(phone, expected) -> None:
    assert mask_whatsapp_phone_number(phone) == expected


def test_empty_phone_is_returned_as_null() -> None:
    client, _, workspace = _member_client()
    WhatsAppChannelFactory(workspace=workspace, phone_number='')
    assert client.get(_list_url(workspace)).json()[0]['phone_number_masked'] is None


@pytest.mark.parametrize(
    ('channel_status', 'cache_qr', 'expected'),
    [
        (WhatsAppChannel.Status.WAITING_QR, True, True),
        (WhatsAppChannel.Status.WAITING_QR, False, False),
        (WhatsAppChannel.Status.CONNECTED, True, False),
        (WhatsAppChannel.Status.CONNECTING, True, False),
        (WhatsAppChannel.Status.ERROR, True, False),
    ],
)
def test_list_has_qr_only_for_waiting_channel_with_valid_cache(
    channel_status: str,
    cache_qr: bool,
    expected: bool,
) -> None:
    client, _, workspace = _member_client()
    channel = WhatsAppChannelFactory(workspace=workspace, status=channel_status)
    if cache_qr:
        store_evolution_qr_code(channel.id, RAW_QR)

    response = client.get(_list_url(workspace))

    assert response.json()[0]['has_qr_code'] is expected
    assert RAW_QR not in response.content.decode()
    if channel_status == WhatsAppChannel.Status.CONNECTED and cache_qr:
        assert get_evolution_qr_code(channel.id) is None


def test_cache_failure_does_not_break_list_or_leak_data() -> None:
    client, _, workspace = _member_client()
    channel = _sensitive_channel(workspace=workspace, status=WhatsAppChannel.Status.WAITING_QR)
    with patch('omnichannel.whatsapp_channel_read_service.cache.get_many', side_effect=RuntimeError):
        response = client.get(_list_url(workspace))

    assert response.status_code == status.HTTP_200_OK
    assert response.json()[0]['has_qr_code'] is False
    assert channel.phone_number not in response.content.decode()


def test_list_never_calls_evolution_celery_or_http_and_does_not_change_database() -> None:
    client, _, workspace = _member_client()
    channel = WhatsAppChannelFactory(workspace=workspace)
    before = (channel.status, channel.updated_at)
    with (
        patch('omnichannel.evolution.client.EvolutionAPIClient.get_qr_code') as get_qr,
        patch('omnichannel.evolution.client.EvolutionAPIClient.get_connection_state') as get_state,
        patch('omnichannel.tasks.process_evolution_channel_webhook_task.delay') as task,
        patch('requests.sessions.Session.request') as request,
    ):
        response = client.get(_list_url(workspace))

    channel.refresh_from_db()
    assert response.status_code == status.HTTP_200_OK
    assert (channel.status, channel.updated_at) == before
    get_qr.assert_not_called()
    get_state.assert_not_called()
    task.assert_not_called()
    request.assert_not_called()


def test_detail_returns_scoped_public_channel_without_qr() -> None:
    client, _, workspace = _member_client()
    channel = _sensitive_channel(workspace=workspace, status=WhatsAppChannel.Status.WAITING_QR)
    store_evolution_qr_code(channel.id, RAW_QR)

    response = client.get(_detail_url(workspace, channel))

    assert response.status_code == status.HTTP_200_OK
    assert set(response.json()) == PUBLIC_FIELDS
    assert response.json()['id'] == str(channel.id)
    assert response.json()['has_qr_code'] is True
    assert 'qr_code' not in response.json()
    assert RAW_QR not in response.content.decode()


def test_detail_cross_tenant_channel_is_hidden() -> None:
    client, _, workspace = _member_client()
    other = _sensitive_channel(workspace=WorkspaceFactory())

    response = client.get(_detail_url(workspace, other))

    assert response.status_code == status.HTTP_404_NOT_FOUND
    assert other.instance_name not in response.content.decode()


@pytest.mark.parametrize('method', ['put', 'patch', 'delete'])
def test_collection_rejects_mutating_methods_except_existing_post(method: str) -> None:
    client, _, workspace = _member_client()
    response = getattr(client, method)(_list_url(workspace), {}, format='json')
    assert response.status_code == status.HTTP_405_METHOD_NOT_ALLOWED


@pytest.mark.parametrize('method', ['post', 'put', 'patch', 'delete'])
def test_detail_is_read_only(method: str) -> None:
    client, _, workspace = _member_client()
    channel = WhatsAppChannelFactory(workspace=workspace)
    response = getattr(client, method)(_detail_url(workspace, channel), {}, format='json')
    assert response.status_code == status.HTTP_405_METHOD_NOT_ALLOWED


def test_collection_and_detail_allow_head_and_options() -> None:
    client, _, workspace = _member_client()
    channel = WhatsAppChannelFactory(workspace=workspace)
    assert client.head(_list_url(workspace)).status_code == status.HTTP_200_OK
    assert client.options(_list_url(workspace)).status_code == status.HTTP_200_OK
    assert client.head(_detail_url(workspace, channel)).status_code == status.HTTP_200_OK
    assert client.options(_detail_url(workspace, channel)).status_code == status.HTTP_200_OK


def test_read_responses_disable_intermediary_cache() -> None:
    client, _, workspace = _member_client()
    channel = WhatsAppChannelFactory(workspace=workspace)
    for url in (_list_url(workspace), _detail_url(workspace, channel)):
        response = client.get(url)
        assert response['Cache-Control'] == 'private, no-store'
        assert 'Authorization' in response['Vary']


def test_collection_preserves_post_provisioning_contract() -> None:
    client, _, workspace = _member_client()
    evolution = Mock(spec=BaseEvolutionClient)
    evolution.create_instance.return_value = {}
    evolution.configure_webhook.return_value = {}
    with patch(
        'omnichannel.whatsapp_channel_provisioning.get_evolution_client',
        return_value=evolution,
    ):
        response = client.post(
            _list_url(workspace),
            {'name': 'WhatsApp principal'},
            format='json',
        )

    assert response.status_code == status.HTTP_201_CREATED
    assert set(response.json()) == {'id', 'name', 'provider', 'status', 'created_at', 'updated_at'}
    evolution.create_instance.assert_called_once()
    evolution.configure_webhook.assert_called_once()


def test_collection_uses_method_specific_throttle_scopes() -> None:
    assert WorkspaceWhatsAppChannelCollectionView.throttle_scope == 'whatsapp_channel_provisioning'
    assert WorkspaceWhatsAppChannelCollectionView.read_throttle_scope == 'whatsapp_channel_read'
    assert django_settings.REST_FRAMEWORK['DEFAULT_THROTTLE_RATES'][
        'whatsapp_channel_provisioning'
    ] == '3/minute'
    assert django_settings.REST_FRAMEWORK['DEFAULT_THROTTLE_RATES'][
        'whatsapp_channel_read'
    ] == '120/minute'


def test_read_throttle_returns_429_with_reduced_rate() -> None:
    client, _, workspace = _member_client()
    rates = {
        **django_settings.REST_FRAMEWORK['DEFAULT_THROTTLE_RATES'],
        'whatsapp_channel_read': '1/minute',
    }
    framework_settings = {**django_settings.REST_FRAMEWORK, 'DEFAULT_THROTTLE_RATES': rates}
    cache.clear()
    with override_settings(REST_FRAMEWORK=framework_settings):
        first = client.get(_list_url(workspace), REMOTE_ADDR='198.51.100.50')
        second = client.get(_list_url(workspace), REMOTE_ADDR='198.51.100.50')
    assert first.status_code == status.HTTP_200_OK
    assert second.status_code == status.HTTP_429_TOO_MANY_REQUESTS
