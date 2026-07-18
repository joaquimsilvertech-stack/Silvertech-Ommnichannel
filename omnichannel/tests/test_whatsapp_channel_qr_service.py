from __future__ import annotations

import logging
from unittest.mock import Mock, patch

import pytest
from django.core.cache import cache

from crm.models import Contact
from omnichannel.evolution import (
    BaseEvolutionClient,
    EvolutionAuthenticationError,
    EvolutionConnectionError,
    EvolutionInvalidResponseError,
    EvolutionTimeoutError,
)
from omnichannel.evolution_qr_cache import (
    extract_evolution_qr_code,
    get_evolution_qr_code,
    store_evolution_qr_code,
)
from omnichannel.factories import WhatsAppChannelFactory
from omnichannel.models import Conversation, EvolutionWebhookEvent, Message, WhatsAppChannel
from omnichannel.whatsapp_channel_qr_service import (
    SAFE_QR_CACHE_ERROR_DETAIL,
    SAFE_QR_ERROR_DETAIL,
    WhatsAppChannelQRCodeError,
    get_whatsapp_channel_qr_code,
)

pytestmark = pytest.mark.django_db

RAW_QR = 'A' * 128
DATA_URI_QR = f'data:image/png;base64,{RAW_QR}'


@pytest.fixture(autouse=True)
def clear_qr_cache():
    cache.clear()
    yield
    cache.clear()


def _client(response: dict | None = None) -> Mock:
    client = Mock(spec=BaseEvolutionClient)
    client.get_qr_code.return_value = response if response is not None else {
        'data': {'qrcode': {'base64': RAW_QR}},
    }
    return client


def _channel(**kwargs):
    kwargs.setdefault('status', WhatsAppChannel.Status.WAITING_QR)
    return WhatsAppChannelFactory(**kwargs)


def test_cache_hit_returns_qr_without_evolution() -> None:
    channel = _channel()
    client = _client()
    store_evolution_qr_code(channel.id, RAW_QR)

    result = get_whatsapp_channel_qr_code(channel=channel, client=client)

    assert result.has_qr_code is True
    assert result.qr_code == RAW_QR
    assert result.qr_format == 'base64'
    assert result.source == 'cache'
    client.get_qr_code.assert_not_called()


def test_cache_miss_calls_central_client_once_and_caches_result() -> None:
    channel = _channel(instance_name='private-instance-name')
    client = _client()

    result = get_whatsapp_channel_qr_code(channel=channel, client=client)

    client.get_qr_code.assert_called_once_with(instance_name='private-instance-name')
    assert result.has_qr_code is True
    assert result.source == 'evolution'
    assert get_evolution_qr_code(channel.id) == RAW_QR


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
def test_ineligible_status_never_returns_qr_or_calls_evolution(channel_status: str) -> None:
    channel = _channel(status=channel_status)
    client = _client()
    store_evolution_qr_code(channel.id, RAW_QR)

    result = get_whatsapp_channel_qr_code(channel=channel, client=client)

    assert result.status == channel_status
    assert result.has_qr_code is False
    assert result.qr_code is None
    client.get_qr_code.assert_not_called()


@pytest.mark.parametrize(
    'payload',
    [
        {'data': {'qrcode': {'base64': RAW_QR}}},
        {'data': {'base64': RAW_QR}},
        {'qrcode': {'base64': RAW_QR}},
    ],
)
def test_shared_extractor_supports_only_confirmed_shapes(payload: dict) -> None:
    assert extract_evolution_qr_code(payload) == RAW_QR


@pytest.mark.parametrize(
    'payload',
    [
        {'qrcode': {'pairingCode': 'private-pairing'}},
        {'base64': RAW_QR},
        {'data': {'code': RAW_QR}},
        ['not-an-object'],
        None,
    ],
)
def test_shared_extractor_rejects_pairing_and_unconfirmed_shapes(payload) -> None:
    assert extract_evolution_qr_code(payload) is None


def test_remote_response_without_qr_returns_safe_empty_result() -> None:
    channel = _channel()
    client = _client({'qrcode': {'pairingCode': 'private-pairing'}})

    result = get_whatsapp_channel_qr_code(channel=channel, client=client)

    assert result.has_qr_code is False
    assert result.qr_code is None
    assert result.qr_format is None
    assert get_evolution_qr_code(channel.id) is None
    assert channel.status == WhatsAppChannel.Status.WAITING_QR


def test_data_uri_format_is_preserved_without_transformation() -> None:
    channel = _channel()
    client = _client({'data': {'base64': DATA_URI_QR}})
    result = get_whatsapp_channel_qr_code(channel=channel, client=client)
    assert result.qr_code == DATA_URI_QR
    assert result.qr_format == 'data_uri'


def test_state_change_before_cache_write_discards_remote_qr() -> None:
    channel = _channel()
    client = _client()
    with patch(
        'omnichannel.whatsapp_channel_qr_service._get_current_status',
        return_value=WhatsAppChannel.Status.CONNECTED,
    ):
        result = get_whatsapp_channel_qr_code(channel=channel, client=client)

    assert result.has_qr_code is False
    assert result.status == WhatsAppChannel.Status.CONNECTED
    assert get_evolution_qr_code(channel.id) is None


def test_state_change_after_cache_write_removes_qr_and_discards_response() -> None:
    channel = _channel()
    client = _client()
    with patch(
        'omnichannel.whatsapp_channel_qr_service._get_current_status',
        side_effect=[WhatsAppChannel.Status.WAITING_QR, WhatsAppChannel.Status.CONNECTED],
    ):
        result = get_whatsapp_channel_qr_code(channel=channel, client=client)

    assert result.has_qr_code is False
    assert result.status == WhatsAppChannel.Status.CONNECTED
    assert get_evolution_qr_code(channel.id) is None


def test_cache_read_failure_is_503_and_does_not_call_evolution() -> None:
    channel = _channel()
    client = _client()
    with (
        patch('omnichannel.evolution_qr_cache.cache.get', side_effect=RuntimeError),
        pytest.raises(WhatsAppChannelQRCodeError) as raised,
    ):
        get_whatsapp_channel_qr_code(channel=channel, client=client)

    assert raised.value.http_status == 503
    assert raised.value.error_code == 'QR_CACHE_UNAVAILABLE'
    assert raised.value.detail == SAFE_QR_CACHE_ERROR_DETAIL
    client.get_qr_code.assert_not_called()


def test_cache_write_failure_is_503_and_never_returns_remote_qr() -> None:
    channel = _channel()
    client = _client()
    with (
        patch('omnichannel.evolution_qr_cache.cache.set', side_effect=RuntimeError),
        pytest.raises(WhatsAppChannelQRCodeError) as raised,
    ):
        get_whatsapp_channel_qr_code(channel=channel, client=client)

    assert raised.value.http_status == 503
    assert raised.value.error_code == 'QR_CACHE_UNAVAILABLE'
    assert RAW_QR not in str(raised.value)
    client.get_qr_code.assert_called_once()


@pytest.mark.parametrize(
    ('error', 'expected_status', 'expected_code'),
    [
        (EvolutionTimeoutError(), 504, 'EVOLUTION_TIMEOUT'),
        (EvolutionAuthenticationError(), 503, 'EVOLUTION_AUTHENTICATION_ERROR'),
        (EvolutionConnectionError(), 503, 'EVOLUTION_CONNECTION_ERROR'),
        (EvolutionInvalidResponseError(), 502, 'EVOLUTION_INVALID_RESPONSE'),
    ],
)
def test_evolution_errors_are_mapped_without_external_details(
    error,
    expected_status: int,
    expected_code: str,
) -> None:
    channel = _channel()
    client = _client()
    client.get_qr_code.side_effect = error

    with pytest.raises(WhatsAppChannelQRCodeError) as raised:
        get_whatsapp_channel_qr_code(channel=channel, client=client)

    assert raised.value.http_status == expected_status
    assert raised.value.error_code == expected_code
    assert raised.value.detail == SAFE_QR_ERROR_DETAIL
    assert str(error) not in str(raised.value)
    client.get_qr_code.assert_called_once()


def test_service_has_no_retry_and_opens_no_atomic_block() -> None:
    channel = _channel()
    client = _client()
    with patch('django.db.transaction.atomic') as atomic:
        get_whatsapp_channel_qr_code(channel=channel, client=client)
    atomic.assert_not_called()
    client.get_qr_code.assert_called_once()


def test_service_does_not_persist_or_create_domain_objects() -> None:
    channel = _channel()
    baseline = {
        'contacts': Contact.objects.count(),
        'conversations': Conversation.objects.count(),
        'messages': Message.objects.count(),
        'receipts': EvolutionWebhookEvent.objects.count(),
        'status': channel.status,
    }

    get_whatsapp_channel_qr_code(channel=channel, client=_client())
    channel.refresh_from_db()

    assert Contact.objects.count() == baseline['contacts']
    assert Conversation.objects.count() == baseline['conversations']
    assert Message.objects.count() == baseline['messages']
    assert EvolutionWebhookEvent.objects.count() == baseline['receipts']
    assert channel.status == baseline['status']
    assert not any(field.name in {'qr', 'qrcode', 'base64'} for field in channel._meta.fields)


def test_service_logs_exclude_qr_phone_instance_and_external_exception(caplog) -> None:
    phone = '5511999991234'
    instance = 'private-instance-sentinel'
    channel = _channel(phone_number=phone, instance_name=instance)
    client = _client({'data': {'base64': RAW_QR}})
    caplog.set_level(logging.INFO, logger='omnichannel.whatsapp_channel_qr_service')

    get_whatsapp_channel_qr_code(channel=channel, client=client)

    rendered = ' '.join(record.getMessage() + repr(record.__dict__) for record in caplog.records)
    assert RAW_QR not in rendered
    assert phone not in rendered
    assert instance not in rendered
