from __future__ import annotations

import logging
from unittest.mock import Mock, patch
from uuid import uuid4

import pytest
from django.conf import settings as django_settings
from django.core.cache import cache
from django.test import override_settings
from rest_framework import status
from rest_framework.renderers import JSONRenderer
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import AccessToken

from omnichannel.evolution import (
    BaseEvolutionClient,
    EvolutionAuthenticationError,
    EvolutionConnectionError,
    EvolutionInvalidResponseError,
    EvolutionTimeoutError,
)
from omnichannel.evolution_qr_cache import (
    EvolutionQRCodeCacheError,
    get_evolution_qr_code,
    store_evolution_qr_code,
)
from omnichannel.factories import WhatsAppChannelFactory
from omnichannel.models import WhatsAppChannel
from omnichannel.whatsapp_channel_views import WorkspaceWhatsAppChannelQRCodeView
from omnichannel.whatsapp_channel_qr_service import SAFE_QR_CACHE_ERROR_DETAIL
from workspaces.factories import MemberFactory, UserFactory, WorkspaceFactory
from workspaces.models import Member

pytestmark = pytest.mark.django_db

RAW_QR = 'Q' * 128
DATA_URI_QR = f'data:image/png;base64,{RAW_QR}'
QR_FIELDS = {'id', 'status', 'has_qr_code', 'qr_code', 'format'}


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


def _qr_url(workspace, channel) -> str:
    return f'/api/workspaces/{workspace.id}/whatsapp-channels/{channel.id}/qr/'


def _sensitive_channel(*, workspace, **kwargs):
    defaults = {
        'workspace': workspace,
        'status': WhatsAppChannel.Status.WAITING_QR,
        'instance_name': f'private-instance-{uuid4().hex}',
        'instance_id': 'private-instance-id',
        'instance_token': 'private-instance-token',
        'webhook_secret': 'private-webhook-secret',
        'phone_number': '5511999991234',
        'last_error_code': 'PRIVATE_LAST_ERROR',
    }
    defaults.update(kwargs)
    return WhatsAppChannelFactory(**defaults)


def _evolution_client(response: dict | None = None) -> Mock:
    client = Mock(spec=BaseEvolutionClient)
    client.get_qr_code.return_value = response if response is not None else {
        'data': {'qrcode': {'base64': RAW_QR}},
    }
    return client


def _assert_safe_qr_headers(response) -> None:
    assert response['Cache-Control'] == 'no-store, private, max-age=0'
    assert response['Pragma'] == 'no-cache'
    assert response['Expires'] == '0'
    assert response['X-Content-Type-Options'] == 'nosniff'
    assert 'Authorization' in response['Vary']


def test_qr_requires_authentication() -> None:
    workspace = WorkspaceFactory()
    channel = WhatsAppChannelFactory(workspace=workspace)
    response = APIClient().get(_qr_url(workspace, channel))
    assert response.status_code == status.HTTP_401_UNAUTHORIZED
    _assert_safe_qr_headers(response)


@pytest.mark.parametrize('role', [Member.Role.OWNER, Member.Role.ADMIN])
def test_owner_and_admin_can_get_cached_qr(role: str) -> None:
    client, _, workspace = _member_client(role=role)
    channel = _sensitive_channel(workspace=workspace)
    store_evolution_qr_code(channel.id, RAW_QR)

    response = client.get(_qr_url(workspace, channel))

    assert response.status_code == status.HTTP_200_OK
    assert response.json() == {
        'id': str(channel.id),
        'status': WhatsAppChannel.Status.WAITING_QR,
        'has_qr_code': True,
        'qr_code': RAW_QR,
        'format': 'base64',
    }


def test_superuser_can_get_qr_without_membership() -> None:
    user = UserFactory(is_superuser=True, is_staff=True)
    workspace = WorkspaceFactory()
    channel = _sensitive_channel(workspace=workspace)
    store_evolution_qr_code(channel.id, RAW_QR)
    response = _client_for(user).get(_qr_url(workspace, channel))
    assert response.status_code == status.HTTP_200_OK
    assert response.json()['qr_code'] == RAW_QR


@pytest.mark.parametrize('access_kind', ['agent', 'non_member'])
def test_agent_and_non_member_cannot_get_qr(access_kind: str) -> None:
    workspace = WorkspaceFactory()
    channel = _sensitive_channel(workspace=workspace)
    store_evolution_qr_code(channel.id, RAW_QR)
    if access_kind == 'agent':
        client, _, _ = _member_client(role=Member.Role.AGENT, workspace=workspace)
    else:
        client = _client_for(UserFactory())

    response = client.get(_qr_url(workspace, channel))

    assert response.status_code == status.HTTP_403_FORBIDDEN
    assert RAW_QR not in response.content.decode()


def test_cross_tenant_channel_and_qr_are_hidden() -> None:
    client, _, workspace = _member_client()
    other = _sensitive_channel(workspace=WorkspaceFactory())
    store_evolution_qr_code(other.id, RAW_QR)

    response = client.get(
        f'{_qr_url(workspace, other)}?workspace_id={other.workspace_id}'
        f'&channel_id={other.id}&instance_name={other.instance_name}',
    )

    assert response.status_code == status.HTTP_404_NOT_FOUND
    rendered = response.content.decode()
    assert RAW_QR not in rendered
    assert other.instance_name not in rendered


@pytest.mark.parametrize(
    ('qr_code', 'expected_format'),
    [(RAW_QR, 'base64'), (DATA_URI_QR, 'data_uri')],
)
def test_cached_qr_preserves_value_and_identifies_format(
    qr_code: str,
    expected_format: str,
) -> None:
    client, _, workspace = _member_client()
    channel = _sensitive_channel(workspace=workspace)
    store_evolution_qr_code(channel.id, qr_code)
    with patch('omnichannel.whatsapp_channel_qr_service.get_evolution_client') as factory:
        response = client.get(_qr_url(workspace, channel))
    assert response.status_code == status.HTTP_200_OK
    assert response.json()['qr_code'] == qr_code
    assert response.json()['format'] == expected_format
    factory.assert_not_called()


@pytest.mark.parametrize(
    'channel_status',
    [
        WhatsAppChannel.Status.CONNECTED,
        WhatsAppChannel.Status.CONNECTING,
        WhatsAppChannel.Status.RECONNECTING,
        WhatsAppChannel.Status.DISCONNECTED,
        WhatsAppChannel.Status.ERROR,
        WhatsAppChannel.Status.PROVISIONING,
        WhatsAppChannel.Status.DELETING,
    ],
)
def test_ineligible_status_never_returns_qr_or_calls_evolution(
    channel_status: str,
) -> None:
    client, _, workspace = _member_client()
    channel = _sensitive_channel(workspace=workspace, status=channel_status)
    store_evolution_qr_code(channel.id, RAW_QR)
    with patch('omnichannel.whatsapp_channel_qr_service.get_evolution_client') as factory:
        response = client.get(_qr_url(workspace, channel))

    assert response.status_code == status.HTTP_200_OK
    assert response.json() == {
        'id': str(channel.id),
        'status': channel_status,
        'has_qr_code': False,
        'qr_code': None,
        'format': None,
    }
    factory.assert_not_called()
    if channel_status == WhatsAppChannel.Status.CONNECTED:
        assert get_evolution_qr_code(channel.id) is None


def test_cache_miss_uses_central_client_once_and_caches_remote_qr() -> None:
    client, _, workspace = _member_client()
    channel = _sensitive_channel(workspace=workspace)
    evolution = _evolution_client()
    with patch(
        'omnichannel.whatsapp_channel_qr_service.get_evolution_client',
        return_value=evolution,
    ) as factory:
        response = client.get(_qr_url(workspace, channel))

    assert response.status_code == status.HTTP_200_OK
    assert response.json()['qr_code'] == RAW_QR
    assert response.json()['has_qr_code'] is True
    assert get_evolution_qr_code(channel.id) == RAW_QR
    factory.assert_called_once_with()
    evolution.get_qr_code.assert_called_once_with(instance_name=channel.instance_name)
    assert channel.instance_name not in response.content.decode()


def test_fallback_uses_no_direct_http_forbidden_operation_or_celery() -> None:
    client, _, workspace = _member_client()
    channel = _sensitive_channel(workspace=workspace)
    evolution = _evolution_client()
    with (
        patch(
            'omnichannel.whatsapp_channel_qr_service.get_evolution_client',
            return_value=evolution,
        ),
        patch('requests.sessions.Session.request') as http_call,
        patch('omnichannel.tasks.process_evolution_channel_webhook_task.delay') as task_call,
    ):
        response = client.get(_qr_url(workspace, channel))

    assert response.status_code == status.HTTP_200_OK
    evolution.get_qr_code.assert_called_once()
    for method_name in (
        'get_connection_state',
        'configure_webhook',
        'create_instance',
        'restart_instance',
        'logout_instance',
        'delete_instance',
        'send_text',
    ):
        getattr(evolution, method_name).assert_not_called()
    http_call.assert_not_called()
    task_call.assert_not_called()


@pytest.mark.parametrize(
    'remote_payload',
    [
        {},
        {'data': {}},
        {'qrcode': {'pairingCode': 'private-pairing-code'}},
        {'data': {'qrcode': {'count': 1, 'code': 'private-code'}}},
    ],
)
def test_remote_response_without_supported_qr_is_safe(remote_payload: dict) -> None:
    client, _, workspace = _member_client()
    channel = _sensitive_channel(workspace=workspace)
    evolution = _evolution_client(remote_payload)
    with patch(
        'omnichannel.whatsapp_channel_qr_service.get_evolution_client',
        return_value=evolution,
    ):
        response = client.get(_qr_url(workspace, channel))

    assert response.status_code == status.HTTP_200_OK
    assert response.json()['has_qr_code'] is False
    assert response.json()['qr_code'] is None
    assert response.json()['format'] is None
    rendered = response.content.decode()
    assert 'private-pairing-code' not in rendered
    assert 'private-code' not in rendered
    assert 'count' not in rendered


def test_cache_read_failure_is_safe_503_and_skips_evolution() -> None:
    client, _, workspace = _member_client()
    channel = _sensitive_channel(workspace=workspace)
    evolution = _evolution_client()
    with (
        patch(
            'omnichannel.whatsapp_channel_qr_service.get_evolution_qr_code',
            side_effect=EvolutionQRCodeCacheError('QR_CACHE_UNAVAILABLE'),
        ),
        patch(
            'omnichannel.whatsapp_channel_qr_service.get_evolution_client',
            return_value=evolution,
        ) as factory,
    ):
        response = client.get(_qr_url(workspace, channel))

    assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
    assert response.json() == {
        'detail': SAFE_QR_CACHE_ERROR_DETAIL,
        'error_code': 'QR_CACHE_UNAVAILABLE',
    }
    factory.assert_not_called()
    evolution.get_qr_code.assert_not_called()
    assert RAW_QR not in response.content.decode()
    _assert_safe_qr_headers(response)


def test_cache_write_failure_is_safe_503_and_hides_remote_qr() -> None:
    client, _, workspace = _member_client()
    channel = _sensitive_channel(workspace=workspace)
    evolution = _evolution_client()
    with (
        patch(
            'omnichannel.whatsapp_channel_qr_service.store_evolution_qr_code',
            side_effect=EvolutionQRCodeCacheError('QR_CACHE_UNAVAILABLE'),
        ),
        patch(
            'omnichannel.whatsapp_channel_qr_service.get_evolution_client',
            return_value=evolution,
        ),
    ):
        response = client.get(_qr_url(workspace, channel))

    assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
    assert response.json()['error_code'] == 'QR_CACHE_UNAVAILABLE'
    assert RAW_QR not in response.content.decode()
    evolution.get_qr_code.assert_called_once()


@pytest.mark.parametrize(
    ('error', 'expected_status', 'expected_code'),
    [
        (EvolutionTimeoutError('private-timeout-body'), 504, 'EVOLUTION_TIMEOUT'),
        (
            EvolutionAuthenticationError('private-auth-body'),
            503,
            'EVOLUTION_AUTHENTICATION_ERROR',
        ),
        (
            EvolutionConnectionError('private-connection-body'),
            503,
            'EVOLUTION_CONNECTION_ERROR',
        ),
        (
            EvolutionInvalidResponseError('private-invalid-body'),
            502,
            'EVOLUTION_INVALID_RESPONSE',
        ),
    ],
)
def test_evolution_errors_are_safely_mapped(
    error,
    expected_status: int,
    expected_code: str,
) -> None:
    client, _, workspace = _member_client()
    channel = _sensitive_channel(workspace=workspace)
    evolution = _evolution_client()
    evolution.get_qr_code.side_effect = error
    with patch(
        'omnichannel.whatsapp_channel_qr_service.get_evolution_client',
        return_value=evolution,
    ):
        response = client.get(_qr_url(workspace, channel))

    rendered = response.content.decode()
    assert response.status_code == expected_status
    assert response.json()['error_code'] == expected_code
    assert response.json()['detail'] == 'N\u00e3o foi poss\u00edvel obter o QR Code.'
    assert str(error) not in rendered
    assert channel.instance_name not in rendered
    assert channel.instance_token not in rendered
    _assert_safe_qr_headers(response)


def test_qr_logs_exclude_qr_phone_instance_and_external_error(caplog) -> None:
    client, _, workspace = _member_client()
    phone = '5511999991234'
    instance = 'private-instance-log-sentinel'
    channel = _sensitive_channel(
        workspace=workspace,
        phone_number=phone,
        instance_name=instance,
    )
    evolution = _evolution_client()
    caplog.set_level(logging.INFO, logger='omnichannel.whatsapp_channel_qr_service')
    with patch(
        'omnichannel.whatsapp_channel_qr_service.get_evolution_client',
        return_value=evolution,
    ):
        response = client.get(_qr_url(workspace, channel))

    rendered_logs = ' '.join(
        record.getMessage() + repr(record.__dict__) for record in caplog.records
    )
    assert response.status_code == status.HTTP_200_OK
    assert RAW_QR not in rendered_logs
    assert phone not in rendered_logs
    assert instance not in rendered_logs


@pytest.mark.parametrize(
    'current_status',
    [WhatsAppChannel.Status.CONNECTED, WhatsAppChannel.Status.DELETING],
)
def test_pre_fallback_race_skips_evolution_and_never_returns_qr(
    current_status: str,
) -> None:
    client, _, workspace = _member_client()
    channel = _sensitive_channel(workspace=workspace)
    evolution = _evolution_client()
    with (
        patch(
            'omnichannel.whatsapp_channel_qr_service.get_evolution_client',
            return_value=evolution,
        ) as client_factory,
        patch(
            'omnichannel.whatsapp_channel_qr_service._get_current_status',
            return_value=current_status,
        ),
    ):
        response = client.get(_qr_url(workspace, channel))

    assert response.status_code == status.HTTP_200_OK
    assert response.json()['status'] == current_status
    assert response.json()['has_qr_code'] is False
    assert RAW_QR not in response.content.decode()
    assert get_evolution_qr_code(channel.id) is None
    client_factory.assert_not_called()
    evolution.get_qr_code.assert_not_called()
    _assert_safe_qr_headers(response)


def test_race_after_cache_write_removes_qr_and_hides_response() -> None:
    client, _, workspace = _member_client()
    channel = _sensitive_channel(workspace=workspace)
    evolution = _evolution_client()
    with (
        patch(
            'omnichannel.whatsapp_channel_qr_service.get_evolution_client',
            return_value=evolution,
        ),
        patch(
            'omnichannel.whatsapp_channel_qr_service._get_current_status',
            side_effect=[
                WhatsAppChannel.Status.WAITING_QR,
                WhatsAppChannel.Status.WAITING_QR,
                WhatsAppChannel.Status.CONNECTED,
            ],
        ),
    ):
        response = client.get(_qr_url(workspace, channel))

    assert response.json()['status'] == WhatsAppChannel.Status.CONNECTED
    assert response.json()['has_qr_code'] is False
    assert RAW_QR not in response.content.decode()
    assert get_evolution_qr_code(channel.id) is None


def test_qr_uses_only_json_renderer_and_rejects_browsable_html() -> None:
    client, _, workspace = _member_client()
    channel = _sensitive_channel(workspace=workspace)
    store_evolution_qr_code(channel.id, RAW_QR)

    json_response = client.get(_qr_url(workspace, channel), HTTP_ACCEPT='application/json')
    html_response = client.get(_qr_url(workspace, channel), HTTP_ACCEPT='text/html')

    assert WorkspaceWhatsAppChannelQRCodeView.renderer_classes == [JSONRenderer]
    assert isinstance(json_response.accepted_renderer, JSONRenderer)
    assert json_response.status_code == status.HTTP_200_OK
    assert html_response.status_code == status.HTTP_406_NOT_ACCEPTABLE
    assert RAW_QR not in html_response.content.decode()
    _assert_safe_qr_headers(html_response)


@pytest.mark.parametrize('method', ['head', 'post', 'put', 'patch', 'delete'])
def test_qr_rejects_unsupported_methods(method: str) -> None:
    client, _, workspace = _member_client()
    channel = _sensitive_channel(workspace=workspace)
    response = getattr(client, method)(_qr_url(workspace, channel), {}, format='json')
    assert response.status_code == status.HTTP_405_METHOD_NOT_ALLOWED
    _assert_safe_qr_headers(response)


def test_qr_allows_options_without_exposing_qr() -> None:
    client, _, workspace = _member_client()
    channel = _sensitive_channel(workspace=workspace)
    store_evolution_qr_code(channel.id, RAW_QR)
    response = client.options(_qr_url(workspace, channel))
    assert response.status_code == status.HTTP_200_OK
    assert RAW_QR not in response.content.decode()
    _assert_safe_qr_headers(response)


def test_qr_headers_are_applied_on_success_and_empty_response() -> None:
    client, _, workspace = _member_client()
    waiting = _sensitive_channel(workspace=workspace)
    connected = _sensitive_channel(
        workspace=workspace,
        status=WhatsAppChannel.Status.CONNECTED,
    )
    store_evolution_qr_code(waiting.id, RAW_QR)
    for channel in (waiting, connected):
        response = client.get(_qr_url(workspace, channel))
        assert response.status_code == status.HTTP_200_OK
        _assert_safe_qr_headers(response)


def test_qr_throttle_is_scoped_per_user_workspace_and_channel() -> None:
    client, _, workspace = _member_client()
    first_channel = _sensitive_channel(workspace=workspace)
    second_channel = _sensitive_channel(workspace=workspace)
    store_evolution_qr_code(first_channel.id, RAW_QR)
    store_evolution_qr_code(second_channel.id, RAW_QR)
    rates = {
        **django_settings.REST_FRAMEWORK['DEFAULT_THROTTLE_RATES'],
        'whatsapp_channel_qr': '1/minute',
    }
    framework_settings = {**django_settings.REST_FRAMEWORK, 'DEFAULT_THROTTLE_RATES': rates}
    cache.clear()
    store_evolution_qr_code(first_channel.id, RAW_QR)
    store_evolution_qr_code(second_channel.id, RAW_QR)
    with override_settings(REST_FRAMEWORK=framework_settings):
        first = client.get(_qr_url(workspace, first_channel))
        limited = client.get(_qr_url(workspace, first_channel))
        independent = client.get(_qr_url(workspace, second_channel))
    assert first.status_code == status.HTTP_200_OK
    assert limited.status_code == status.HTTP_429_TOO_MANY_REQUESTS
    assert independent.status_code == status.HTTP_200_OK
    _assert_safe_qr_headers(limited)


def test_duplicate_get_uses_cache_before_evolution() -> None:
    client, _, workspace = _member_client()
    channel = _sensitive_channel(workspace=workspace)
    evolution = _evolution_client()
    with patch(
        'omnichannel.whatsapp_channel_qr_service.get_evolution_client',
        return_value=evolution,
    ):
        first = client.get(_qr_url(workspace, channel))
        second = client.get(_qr_url(workspace, channel))

    assert first.status_code == status.HTTP_200_OK
    assert second.status_code == status.HTTP_200_OK
    assert first.json()['qr_code'] == second.json()['qr_code'] == RAW_QR
    evolution.get_qr_code.assert_called_once_with(instance_name=channel.instance_name)


def test_qr_response_contains_only_public_contract() -> None:
    client, _, workspace = _member_client()
    channel = _sensitive_channel(workspace=workspace)
    store_evolution_qr_code(channel.id, RAW_QR)
    response = client.get(_qr_url(workspace, channel))
    assert set(response.json()) == QR_FIELDS
    rendered = response.content.decode()
    for secret in (
        channel.instance_name,
        channel.instance_id,
        channel.instance_token,
        channel.webhook_secret,
        channel.phone_number,
        channel.last_error_code,
        str(channel.webhook_public_id),
    ):
        assert secret not in rendered
