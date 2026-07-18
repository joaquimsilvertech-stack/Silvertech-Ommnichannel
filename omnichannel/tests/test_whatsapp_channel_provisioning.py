from __future__ import annotations

import inspect
import logging
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest
from django.db import DatabaseError, connection

from crm.models import Contact
from omnichannel.evolution import (
    BaseEvolutionClient,
    EvolutionAPIError,
    EvolutionAuthenticationError,
    EvolutionConfigurationError,
    EvolutionConflictError,
    EvolutionConnectionError,
    EvolutionInvalidRequestError,
    EvolutionInvalidResponseError,
    EvolutionNotFoundError,
    EvolutionRateLimitError,
    EvolutionTimeoutError,
    EvolutionUnavailableError,
    EvolutionUnexpectedResponseError,
)
from omnichannel.factories import WhatsAppChannelFactory
from omnichannel.models import Conversation, Message, WhatsAppChannel
from omnichannel.whatsapp_channel_provisioning import (
    MAX_INSTANCE_NAME_GENERATION_ATTEMPTS,
    WhatsAppChannelProvisioningError,
    _finalize_local_channel,
    _reserve_local_channel,
    provision_whatsapp_channel,
)
from workspaces.factories import WorkspaceFactory

pytestmark = pytest.mark.django_db


def _success_response() -> dict:
    return {
        'instance': {
            'instanceName': 'remote-name-that-is-not-trusted',
            'instanceId': 'remote-instance-id',
            'status': 'created',
        },
        'hash': {'apikey': 'remote-instance-token'},
        'qrcode': {'base64': 'private-qr-base64', 'pairingCode': 'PRIVATE-PAIRING'},
    }


@pytest.fixture
def evolution_client() -> Mock:
    client = Mock(spec=BaseEvolutionClient)
    client.create_instance.return_value = _success_response()
    client.delete_instance.return_value = {}
    return client


def test_provisioning_generates_private_instance_name_without_tenant_data(
    evolution_client: Mock,
) -> None:
    workspace = WorkspaceFactory(
        name='Private Workspace Name',
        slug='private-workspace-slug',
    )

    result = provision_whatsapp_channel(
        workspace=workspace,
        channel_name='WhatsApp principal',
        client=evolution_client,
    )

    instance_name = result.channel.instance_name
    assert instance_name.startswith('st_')
    assert len(instance_name) == 35
    assert len(instance_name) <= 128
    assert workspace.name.lower() not in instance_name.lower()
    assert workspace.slug.lower() not in instance_name.lower()
    assert 'whatsapp' not in instance_name.lower()
    assert 'principal' not in instance_name.lower()


@pytest.mark.django_db(transaction=True)
def test_remote_create_runs_after_local_reservation_commit_and_outside_atomic() -> None:
    workspace = WorkspaceFactory()
    client = Mock(spec=BaseEvolutionClient)

    def create_instance(**kwargs):
        assert connection.in_atomic_block is False
        channel = WhatsAppChannel.objects.get(instance_name=kwargs['instance_name'])
        assert channel.status == WhatsAppChannel.Status.PROVISIONING
        return {}

    client.create_instance.side_effect = create_instance

    result = provision_whatsapp_channel(
        workspace=workspace,
        channel_name='Canal transacional',
        client=client,
    )

    assert result.channel.status == WhatsAppChannel.Status.WAITING_QR
    client.create_instance.assert_called_once()


def test_new_channel_is_reserved_with_explicit_safe_defaults(evolution_client: Mock) -> None:
    workspace = WorkspaceFactory()
    observed: dict[str, object] = {}

    def create_instance(**kwargs):
        channel = WhatsAppChannel.objects.get(instance_name=kwargs['instance_name'])
        observed.update(
            status=channel.status,
            instance_id=channel.instance_id,
            instance_token=channel.instance_token,
            webhook_secret=channel.webhook_secret,
            phone_number=channel.phone_number,
            last_error_code=channel.last_error_code,
            connected_at=channel.connected_at,
            last_connection_update_at=channel.last_connection_update_at,
        )
        return _success_response()

    evolution_client.create_instance.side_effect = create_instance

    result = provision_whatsapp_channel(
        workspace=workspace,
        channel_name='  WhatsApp   principal  ',
        client=evolution_client,
    )

    assert result.created is True
    assert result.remote_instance_created is True
    assert result.idempotent_reuse is False
    assert result.channel.name == 'WhatsApp principal'
    assert observed == {
        'status': WhatsAppChannel.Status.PROVISIONING,
        'instance_id': '',
        'instance_token': '',
        'webhook_secret': '',
        'phone_number': '',
        'last_error_code': '',
        'connected_at': None,
        'last_connection_update_at': None,
    }


def test_create_instance_contract_and_successful_final_state(evolution_client: Mock) -> None:
    workspace = WorkspaceFactory()

    result = provision_whatsapp_channel(
        workspace=workspace,
        channel_name='WhatsApp principal',
        client=evolution_client,
    )

    channel = result.channel
    channel.refresh_from_db()
    evolution_client.create_instance.assert_called_once_with(
        instance_name=channel.instance_name,
        qrcode=True,
        integration='WHATSAPP-BAILEYS',
    )
    assert channel.status == WhatsAppChannel.Status.WAITING_QR
    assert channel.instance_id == 'remote-instance-id'
    assert channel.instance_token == 'remote-instance-token'
    assert channel.last_error_code == ''
    assert channel.webhook_secret == ''
    assert channel.phone_number == ''
    assert channel.connected_at is None
    assert channel.last_connection_update_at is None


@pytest.mark.parametrize(
    'response',
    [
        {},
        {'instance': {}},
        {'hash': {}},
        {'qrcode': {'base64': 'discard-me', 'pairingCode': 'discard-me-too'}},
    ],
)
def test_safe_partial_or_empty_response_can_complete_without_optional_identifiers(
    response: dict,
    evolution_client: Mock,
) -> None:
    evolution_client.create_instance.return_value = response

    result = provision_whatsapp_channel(
        workspace=WorkspaceFactory(),
        channel_name='Canal sem identificadores',
        client=evolution_client,
    )

    result.channel.refresh_from_db()
    assert result.channel.status == WhatsAppChannel.Status.WAITING_QR
    assert result.channel.instance_id == ''
    assert result.channel.instance_token == ''
    assert not hasattr(result.channel, 'qrcode')
    assert not hasattr(result.channel, 'pairingCode')


def test_instance_id_falls_back_to_compatible_instance_id_field(evolution_client: Mock) -> None:
    evolution_client.create_instance.return_value = {'instance': {'id': 'compatible-id'}}

    result = provision_whatsapp_channel(
        workspace=WorkspaceFactory(),
        channel_name='Canal fallback',
        client=evolution_client,
    )

    assert result.channel.instance_id == 'compatible-id'


def test_global_api_key_is_not_copied_when_response_has_no_instance_token(
    evolution_client: Mock,
    settings,
) -> None:
    settings.EVOLUTION_API_KEY = 'global-api-key-must-not-be-copied'
    evolution_client.create_instance.return_value = {'instance': {'instanceId': 'id-only'}}

    result = provision_whatsapp_channel(
        workspace=WorkspaceFactory(),
        channel_name='Canal sem token',
        client=evolution_client,
    )

    result.channel.refresh_from_db()
    assert result.channel.instance_token == ''
    assert result.channel.instance_token != settings.EVOLUTION_API_KEY


def test_instance_token_is_encrypted_at_rest(evolution_client: Mock) -> None:
    result = provision_whatsapp_channel(
        workspace=WorkspaceFactory(),
        channel_name='Canal criptografado',
        client=evolution_client,
    )
    channel = result.channel

    with connection.cursor() as cursor:
        cursor.execute(
            'SELECT instance_token FROM omnichannel_whatsappchannel WHERE id = %s',
            [str(channel.id)],
        )
        raw_values = cursor.fetchone()

    assert raw_values is not None
    serialized_raw_values = ' '.join(
        value.decode('utf-8', errors='ignore')
        if isinstance(value, bytes)
        else str(value)
        for value in raw_values
        if value is not None
    )
    assert channel.instance_token == 'remote-instance-token'
    assert 'remote-instance-token' not in serialized_raw_values


@pytest.mark.parametrize('status_value', list(WhatsAppChannel.Status.values))
def test_same_normalized_name_reuses_channel_in_every_status_without_remote_call(
    status_value: str,
    evolution_client: Mock,
) -> None:
    workspace = WorkspaceFactory()
    existing = WhatsAppChannelFactory(
        workspace=workspace,
        name='WhatsApp principal',
        status=status_value,
        instance_id='preserved-id',
        instance_token='preserved-token',
        last_error_code='PRESERVED_ERROR',
    )

    result = provision_whatsapp_channel(
        workspace=workspace,
        channel_name='  WhatsApp   principal ',
        client=evolution_client,
    )

    existing.refresh_from_db()
    assert result.channel.id == existing.id
    assert result.created is False
    assert result.remote_instance_created is False
    assert result.idempotent_reuse is True
    assert existing.status == status_value
    assert existing.instance_id == 'preserved-id'
    assert existing.instance_token == 'preserved-token'
    assert existing.last_error_code == 'PRESERVED_ERROR'
    evolution_client.create_instance.assert_not_called()


def test_legacy_disconnected_channel_with_same_name_is_never_provisioned(
    evolution_client: Mock,
) -> None:
    workspace = WorkspaceFactory()
    legacy = WhatsAppChannelFactory(
        workspace=workspace,
        name='Canal legado',
        instance_name='legacy-global-instance',
        status=WhatsAppChannel.Status.DISCONNECTED,
    )

    result = provision_whatsapp_channel(
        workspace=workspace,
        channel_name='Canal legado',
        client=evolution_client,
    )

    assert result.channel.id == legacy.id
    evolution_client.create_instance.assert_not_called()


def test_different_names_create_distinct_channels(evolution_client: Mock) -> None:
    workspace = WorkspaceFactory()

    first = provision_whatsapp_channel(
        workspace=workspace,
        channel_name='Canal um',
        client=evolution_client,
    )
    second = provision_whatsapp_channel(
        workspace=workspace,
        channel_name='Canal dois',
        client=evolution_client,
    )

    assert first.channel.id != second.channel.id
    assert first.channel.instance_name != second.channel.instance_name
    assert evolution_client.create_instance.call_count == 2


def test_same_name_in_different_workspaces_creates_isolated_channels(
    evolution_client: Mock,
) -> None:
    first = provision_whatsapp_channel(
        workspace=WorkspaceFactory(),
        channel_name='WhatsApp principal',
        client=evolution_client,
    )
    second = provision_whatsapp_channel(
        workspace=WorkspaceFactory(),
        channel_name='WhatsApp principal',
        client=evolution_client,
    )

    assert first.channel.workspace_id != second.channel.workspace_id
    assert first.channel.id != second.channel.id
    assert evolution_client.create_instance.call_count == 2


def test_instance_name_collision_is_retried_with_a_bounded_new_value(
    evolution_client: Mock,
) -> None:
    collision_hex = 'a' * 32
    unique_hex = 'b' * 32
    WhatsAppChannelFactory(instance_name=f'st_{collision_hex}')

    with patch(
        'omnichannel.whatsapp_channel_provisioning.uuid.uuid4',
        side_effect=[SimpleNamespace(hex=collision_hex), SimpleNamespace(hex=unique_hex)],
    ) as uuid4:
        result = provision_whatsapp_channel(
            workspace=WorkspaceFactory(),
            channel_name='Canal com colisao',
            client=evolution_client,
        )

    assert result.channel.instance_name == f'st_{unique_hex}'
    assert uuid4.call_count == 2


def test_instance_name_collision_stops_after_limited_attempts(evolution_client: Mock) -> None:
    collision_hex = 'c' * 32
    WhatsAppChannelFactory(instance_name=f'st_{collision_hex}')
    workspace = WorkspaceFactory()

    with (
        patch(
            'omnichannel.whatsapp_channel_provisioning.uuid.uuid4',
            return_value=SimpleNamespace(hex=collision_hex),
        ) as uuid4,
        pytest.raises(WhatsAppChannelProvisioningError) as exc_info,
    ):
        provision_whatsapp_channel(
            workspace=workspace,
            channel_name='Canal sem nome disponivel',
            client=evolution_client,
        )

    assert exc_info.value.error_code == 'INSTANCE_NAME_GENERATION_FAILED'
    assert uuid4.call_count == MAX_INSTANCE_NAME_GENERATION_ATTEMPTS
    assert not WhatsAppChannel.objects.filter(workspace=workspace).exists()
    evolution_client.create_instance.assert_not_called()


@pytest.mark.parametrize(
    ('exception', 'error_code', 'http_status', 'cleanup_expected'),
    [
        (EvolutionAuthenticationError(), 'EVOLUTION_AUTHENTICATION_ERROR', 503, False),
        (EvolutionConfigurationError(), 'EVOLUTION_CONFIGURATION_ERROR', 503, False),
        (EvolutionTimeoutError(), 'EVOLUTION_TIMEOUT', 504, True),
        (EvolutionConnectionError(), 'EVOLUTION_CONNECTION_ERROR', 503, True),
        (EvolutionUnavailableError(), 'EVOLUTION_UNAVAILABLE', 503, True),
        (EvolutionRateLimitError(), 'EVOLUTION_RATE_LIMIT', 503, False),
        (EvolutionConflictError(), 'EVOLUTION_CONFLICT', 409, False),
        (EvolutionInvalidRequestError(), 'EVOLUTION_INVALID_REQUEST', 502, False),
        (EvolutionNotFoundError(), 'EVOLUTION_NOT_FOUND', 502, False),
        (EvolutionInvalidResponseError(), 'EVOLUTION_INVALID_RESPONSE', 502, False),
        (EvolutionUnexpectedResponseError(), 'EVOLUTION_UNEXPECTED_RESPONSE', 502, False),
        (EvolutionAPIError(), 'EVOLUTION_REQUEST_ERROR', 502, False),
        (EvolutionAPIError(retryable=True), 'EVOLUTION_REQUEST_ERROR', 502, True),
    ],
)
def test_evolution_failures_mark_channel_error_and_apply_cleanup_policy(
    exception: EvolutionAPIError,
    error_code: str,
    http_status: int,
    cleanup_expected: bool,
    evolution_client: Mock,
) -> None:
    workspace = WorkspaceFactory()
    evolution_client.create_instance.side_effect = exception

    with pytest.raises(WhatsAppChannelProvisioningError) as exc_info:
        provision_whatsapp_channel(
            workspace=workspace,
            channel_name='Canal com falha',
            client=evolution_client,
        )

    channel = WhatsAppChannel.objects.get(workspace=workspace)
    assert channel.status == WhatsAppChannel.Status.ERROR
    assert channel.last_error_code == error_code
    assert channel.instance_id == ''
    assert channel.instance_token == ''
    assert exc_info.value.error_code == error_code
    assert exc_info.value.http_status == http_status
    assert evolution_client.create_instance.call_count == 1
    assert evolution_client.delete_instance.call_count == int(cleanup_expected)


def test_generic_unexpected_error_is_safely_mapped_and_not_persisted(
    evolution_client: Mock,
) -> None:
    external_detail = 'external payload with token=private-token'
    evolution_client.create_instance.side_effect = RuntimeError(external_detail)

    with pytest.raises(WhatsAppChannelProvisioningError) as exc_info:
        provision_whatsapp_channel(
            workspace=WorkspaceFactory(),
            channel_name='Canal erro inesperado',
            client=evolution_client,
        )

    channel = WhatsAppChannel.objects.get(id=exc_info.value.channel_id)
    assert channel.status == WhatsAppChannel.Status.ERROR
    assert channel.last_error_code == 'EVOLUTION_UNKNOWN_ERROR'
    assert external_detail not in channel.last_error_code
    assert external_detail not in str(exc_info.value)
    evolution_client.delete_instance.assert_not_called()


def test_error_code_is_sanitized_and_bounded(evolution_client: Mock) -> None:
    unsafe_code = 'bad-code\nwith spaces<' + ('x' * 200)
    evolution_client.create_instance.side_effect = EvolutionAPIError(error_code=unsafe_code)

    with pytest.raises(WhatsAppChannelProvisioningError) as exc_info:
        provision_whatsapp_channel(
            workspace=WorkspaceFactory(),
            channel_name='Canal codigo seguro',
            client=evolution_client,
        )

    channel = WhatsAppChannel.objects.get(id=exc_info.value.channel_id)
    assert channel.last_error_code == exc_info.value.error_code
    assert len(channel.last_error_code) <= 128
    assert channel.last_error_code.replace('_', '').isalnum()
    assert '\n' not in channel.last_error_code
    assert '<' not in channel.last_error_code


def test_cleanup_failure_does_not_hide_primary_timeout_error(
    evolution_client: Mock,
    caplog: pytest.LogCaptureFixture,
) -> None:
    evolution_client.create_instance.side_effect = EvolutionTimeoutError('private-create-detail')
    evolution_client.delete_instance.side_effect = EvolutionUnavailableError('private-cleanup-detail')
    caplog.set_level(logging.INFO, logger='omnichannel.whatsapp_channel_provisioning')

    with pytest.raises(WhatsAppChannelProvisioningError) as exc_info:
        provision_whatsapp_channel(
            workspace=WorkspaceFactory(),
            channel_name='Canal cleanup falho',
            client=evolution_client,
        )

    assert exc_info.value.error_code == 'EVOLUTION_TIMEOUT'
    assert exc_info.value.http_status == 504
    evolution_client.delete_instance.assert_called_once()
    assert 'private-create-detail' not in caplog.text
    assert 'private-cleanup-detail' not in caplog.text


def test_remote_success_followed_by_local_failure_compensates_and_keeps_local_channel(
    evolution_client: Mock,
    caplog: pytest.LogCaptureFixture,
) -> None:
    secret_token = 'remote-instance-token'
    secret_qr = 'private-qr-base64'
    caplog.set_level(logging.INFO, logger='omnichannel.whatsapp_channel_provisioning')

    with (
        patch(
            'omnichannel.whatsapp_channel_provisioning._finalize_local_channel',
            side_effect=DatabaseError('private database detail'),
        ),
        pytest.raises(WhatsAppChannelProvisioningError) as exc_info,
    ):
        provision_whatsapp_channel(
            workspace=WorkspaceFactory(),
            channel_name='Canal compensado',
            client=evolution_client,
        )

    channel = WhatsAppChannel.objects.get(id=exc_info.value.channel_id)
    assert channel.status == WhatsAppChannel.Status.ERROR
    assert channel.last_error_code == 'CHANNEL_FINALIZATION_FAILED'
    assert WhatsAppChannel.objects.filter(id=channel.id).exists()
    evolution_client.delete_instance.assert_called_once_with(
        instance_name=channel.instance_name,
    )
    assert secret_token not in caplog.text
    assert secret_qr not in caplog.text
    assert 'private database detail' not in caplog.text
    assert secret_token not in str(exc_info.value)
    assert secret_qr not in str(exc_info.value)


def test_invalid_success_response_compensates_remote_instance(evolution_client: Mock) -> None:
    evolution_client.create_instance.return_value = {'instance': {'instanceId': object()}}

    with pytest.raises(WhatsAppChannelProvisioningError) as exc_info:
        provision_whatsapp_channel(
            workspace=WorkspaceFactory(),
            channel_name='Canal resposta invalida',
            client=evolution_client,
        )

    channel = WhatsAppChannel.objects.get(id=exc_info.value.channel_id)
    assert channel.status == WhatsAppChannel.Status.ERROR
    assert channel.last_error_code == 'EVOLUTION_INVALID_RESPONSE'
    evolution_client.delete_instance.assert_called_once_with(
        instance_name=channel.instance_name,
    )


def test_no_webhook_qr_or_unrelated_evolution_operation_is_called(
    evolution_client: Mock,
) -> None:
    provision_whatsapp_channel(
        workspace=WorkspaceFactory(),
        channel_name='Canal operacoes minimas',
        client=evolution_client,
    )

    evolution_client.create_instance.assert_called_once()
    evolution_client.configure_webhook.assert_not_called()
    evolution_client.get_qr_code.assert_not_called()
    evolution_client.get_connection_state.assert_not_called()
    evolution_client.restart_instance.assert_not_called()
    evolution_client.logout_instance.assert_not_called()
    evolution_client.send_text.assert_not_called()
    evolution_client.delete_instance.assert_not_called()


def test_provisioning_does_not_create_conversations_messages_contacts_or_celery_tasks(
    evolution_client: Mock,
) -> None:
    baseline = (
        Conversation.objects.count(),
        Message.objects.count(),
        Contact.objects.count(),
    )

    with patch('celery.app.task.Task.delay') as delay:
        provision_whatsapp_channel(
            workspace=WorkspaceFactory(),
            channel_name='Canal sem efeitos colaterais',
            client=evolution_client,
        )

    assert (
        Conversation.objects.count(),
        Message.objects.count(),
        Contact.objects.count(),
    ) == baseline
    delay.assert_not_called()


@pytest.mark.parametrize(
    'invalid_name',
    ['', '   ', 'Canal\nmalicioso', 'x' * 129, None, 123],
)
def test_service_defensively_rejects_invalid_channel_names(
    invalid_name,
    evolution_client: Mock,
) -> None:
    workspace = WorkspaceFactory()

    with pytest.raises(WhatsAppChannelProvisioningError) as exc_info:
        provision_whatsapp_channel(
            workspace=workspace,
            channel_name=invalid_name,
            client=evolution_client,
        )

    assert exc_info.value.error_code == 'INVALID_CHANNEL_NAME'
    assert not WhatsAppChannel.objects.filter(workspace=workspace).exists()
    evolution_client.create_instance.assert_not_called()


def test_service_source_uses_locks_without_http_dependencies_or_celery() -> None:
    reserve_source = inspect.getsource(_reserve_local_channel)
    finalize_source = inspect.getsource(_finalize_local_channel)
    module_source = inspect.getsource(inspect.getmodule(provision_whatsapp_channel))

    assert 'Workspace.objects.select_for_update()' in reserve_source
    assert 'WhatsAppChannel.objects.select_for_update()' in finalize_source
    assert 'create_instance' not in reserve_source
    assert 'get_evolution_client' not in reserve_source
    assert 'requests.' not in module_source
    assert '.delay(' not in module_source
    assert 'EVOLUTION_API_KEY' not in module_source
    assert 'EVOLUTION_INSTANCE_NAME' not in module_source

