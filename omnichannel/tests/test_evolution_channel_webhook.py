from __future__ import annotations

import json
import logging
import secrets
from unittest.mock import patch
from uuid import uuid4

import pytest
from django.core.cache import cache
from rest_framework import status
from rest_framework.test import APIClient

from crm.models import Contact
from omnichannel.evolution_webhook import EVOLUTION_WEBHOOK_SECRET_HEADER
from omnichannel.evolution_webhook_views import (
    EvolutionChannelWebhookThrottle,
    EvolutionChannelWebhookView,
)
from omnichannel.factories import WhatsAppChannelFactory
from omnichannel.models import Conversation, Message
from workspaces.factories import WorkspaceFactory

pytestmark = pytest.mark.django_db

SECRET_META_HEADER = 'HTTP_X_SILVERTECH_WEBHOOK_SECRET'


@pytest.fixture(autouse=True)
def clear_webhook_cache():
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def webhook_client() -> APIClient:
    return APIClient()


@pytest.fixture
def channel():
    return WhatsAppChannelFactory(
        instance_name='st_secure_channel',
        webhook_secret='channel-specific-secret',
    )


def _url(channel_or_public_id) -> str:
    public_id = getattr(channel_or_public_id, 'webhook_public_id', channel_or_public_id)
    return f'/api/omnichannel/webhooks/evolution/{public_id}/'


def _payload(channel, **extra) -> dict:
    payload = {
        'event': 'messages.upsert',
        'instance': channel.instance_name,
        'data': {'key': {'id': 'safe-event-id'}},
    }
    payload.update(extra)
    return payload


def _post(
    client: APIClient,
    channel,
    payload: dict,
    *,
    secret: str | None = None,
    query: str = '',
):
    headers = {}
    if secret is not None:
        headers[SECRET_META_HEADER] = secret
    return client.post(
        f'{_url(channel)}{query}',
        payload,
        format='json',
        **headers,
    )


def test_valid_webhook_queues_channel_and_payload_once(
    webhook_client: APIClient,
    channel,
) -> None:
    payload = _payload(channel)

    with patch(
        'omnichannel.evolution_webhook_views.process_evolution_channel_webhook_task.delay',
    ) as delay:
        response = _post(
            webhook_client,
            channel,
            payload,
            secret=channel.webhook_secret,
        )

    assert response.status_code == status.HTTP_200_OK
    assert response.json() == {'status': 'received'}
    delay.assert_called_once_with(str(channel.id), payload)
    queued_args = delay.call_args.args
    assert len(queued_args) == 2
    assert channel.webhook_secret not in repr(queued_args)
    assert str(channel.workspace_id) not in queued_args


def test_public_uuid_without_secret_does_not_authenticate(
    webhook_client: APIClient,
    channel,
) -> None:
    with patch(
        'omnichannel.evolution_webhook_views.process_evolution_channel_webhook_task.delay',
    ) as delay:
        response = _post(webhook_client, channel, _payload(channel))

    assert response.status_code == status.HTTP_404_NOT_FOUND
    assert response.json() == {'detail': 'Webhook inválido.'}
    delay.assert_not_called()


def test_invalid_authentication_cases_are_indistinguishable(
    webhook_client: APIClient,
    channel,
) -> None:
    empty_secret_channel = WhatsAppChannelFactory(webhook_secret='')
    cases = [
        (_url(uuid4()), 'known-secret'),
        (_url(channel), None),
        (_url(channel), ''),
        (_url(channel), 'incorrect-secret'),
        (_url(empty_secret_channel), 'any-secret'),
    ]
    responses = []

    with patch(
        'omnichannel.evolution_webhook_views.process_evolution_channel_webhook_task.delay',
    ) as delay:
        for url, provided_secret in cases:
            headers = (
                {SECRET_META_HEADER: provided_secret}
                if provided_secret is not None
                else {}
            )
            responses.append(
                webhook_client.post(url, _payload(channel), format='json', **headers),
            )

    first = responses[0]
    for response in responses:
        assert response.status_code == first.status_code == status.HTTP_404_NOT_FOUND
        assert response.content == first.content
        assert response['Content-Type'] == first['Content-Type'] == 'application/json'
    delay.assert_not_called()


@pytest.mark.parametrize('case', ['missing-channel', 'wrong-secret'])
def test_constant_time_comparison_runs_for_invalid_authentication(
    case: str,
    webhook_client: APIClient,
    channel,
) -> None:
    url = _url(uuid4()) if case == 'missing-channel' else _url(channel)

    with patch(
        'omnichannel.evolution_webhook_views.secrets.compare_digest',
        wraps=secrets.compare_digest,
    ) as compare_digest:
        response = webhook_client.post(
            url,
            _payload(channel),
            format='json',
            **{SECRET_META_HEADER: 'wrong-secret'},
        )

    assert response.status_code == status.HTTP_404_NOT_FOUND
    compare_digest.assert_called_once()
    first_digest, second_digest = compare_digest.call_args.args
    assert isinstance(first_digest, bytes)
    assert isinstance(second_digest, bytes)
    assert len(first_digest) == len(second_digest) == 32


def test_secret_from_channel_a_cannot_authenticate_channel_b(
    webhook_client: APIClient,
) -> None:
    channel_a = WhatsAppChannelFactory(webhook_secret='secret-a')
    channel_b = WhatsAppChannelFactory(webhook_secret='secret-b')

    with patch(
        'omnichannel.evolution_webhook_views.process_evolution_channel_webhook_task.delay',
    ) as delay:
        response = _post(
            webhook_client,
            channel_b,
            _payload(channel_b),
            secret=channel_a.webhook_secret,
        )

    assert response.status_code == status.HTTP_404_NOT_FOUND
    delay.assert_not_called()


@pytest.mark.parametrize(
    'invalid_secret',
    ['x' * 513, 'secret-with-control\x01character'],
)
def test_invalid_secret_header_is_bounded_and_still_compared(
    invalid_secret: str,
    webhook_client: APIClient,
    channel,
) -> None:
    with patch(
        'omnichannel.evolution_webhook_views.secrets.compare_digest',
        wraps=secrets.compare_digest,
    ) as compare_digest:
        response = _post(
            webhook_client,
            channel,
            _payload(channel),
            secret=invalid_secret,
        )

    assert response.status_code == status.HTTP_404_NOT_FOUND
    compare_digest.assert_called_once()


def test_workspace_from_query_or_payload_never_controls_routing(
    webhook_client: APIClient,
    channel,
) -> None:
    foreign_workspace = WorkspaceFactory()
    payload = _payload(channel, workspace_id=str(foreign_workspace.id))

    with patch(
        'omnichannel.evolution_webhook_views.process_evolution_channel_webhook_task.delay',
    ) as delay:
        response = _post(
            webhook_client,
            channel,
            payload,
            secret=channel.webhook_secret,
            query=f'?workspace={foreign_workspace.id}',
        )

    assert response.status_code == status.HTTP_200_OK
    delay.assert_called_once_with(str(channel.id), payload)


def test_foreign_instance_name_is_rejected_without_redirecting_channel(
    webhook_client: APIClient,
    channel,
) -> None:
    foreign_channel = WhatsAppChannelFactory()
    payload = _payload(channel, instance=foreign_channel.instance_name)

    with patch(
        'omnichannel.evolution_webhook_views.process_evolution_channel_webhook_task.delay',
    ) as delay:
        response = _post(
            webhook_client,
            channel,
            payload,
            secret=channel.webhook_secret,
        )

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert response.json() == {'detail': 'Payload inválido.'}
    delay.assert_not_called()


def test_missing_instance_name_is_allowed(
    webhook_client: APIClient,
    channel,
) -> None:
    payload = {'event': 'messages.upsert', 'data': {}}

    with patch(
        'omnichannel.evolution_webhook_views.process_evolution_channel_webhook_task.delay',
    ) as delay:
        response = _post(
            webhook_client,
            channel,
            payload,
            secret=channel.webhook_secret,
        )

    assert response.status_code == status.HTTP_200_OK
    delay.assert_called_once_with(str(channel.id), payload)


@pytest.mark.parametrize('raw_body', [b'{invalid', b'', b'[]', b'"text"', b'null', b'true', b'1'])
def test_invalid_json_or_non_object_root_is_rejected(
    raw_body: bytes,
    webhook_client: APIClient,
    channel,
) -> None:
    response = webhook_client.generic(
        'POST',
        _url(channel),
        data=raw_body,
        content_type='application/json',
        **{SECRET_META_HEADER: channel.webhook_secret},
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert response.json() == {'detail': 'Payload inválido.'}


@pytest.mark.parametrize(
    'content_type',
    ['text/plain', 'application/x-www-form-urlencoded', 'application/json; charset=unknown-x'],
)
def test_unsupported_content_type_is_rejected(
    content_type: str,
    webhook_client: APIClient,
    channel,
) -> None:
    response = webhook_client.generic(
        'POST',
        _url(channel),
        data=b'{}',
        content_type=content_type,
        **{SECRET_META_HEADER: channel.webhook_secret},
    )

    assert response.status_code == status.HTTP_415_UNSUPPORTED_MEDIA_TYPE


def test_json_content_type_with_valid_charset_is_accepted(
    webhook_client: APIClient,
    channel,
) -> None:
    payload = {'event': 'MESSAGES_UPSERT'}

    with patch(
        'omnichannel.evolution_webhook_views.process_evolution_channel_webhook_task.delay',
    ):
        response = webhook_client.generic(
            'POST',
            _url(channel),
            data=json.dumps(payload).encode('utf-8'),
            content_type='application/json; charset=utf-8',
            **{SECRET_META_HEADER: channel.webhook_secret},
        )

    assert response.status_code == status.HTTP_200_OK


def test_actual_payload_above_limit_returns_413_before_queue(
    webhook_client: APIClient,
    channel,
    settings,
) -> None:
    settings.EVOLUTION_WEBHOOK_MAX_BODY_BYTES = 32
    raw_body = json.dumps({'data': 'x' * 40}).encode('utf-8')

    with patch(
        'omnichannel.evolution_webhook_views.process_evolution_channel_webhook_task.delay',
    ) as delay:
        response = webhook_client.generic(
            'POST',
            _url(channel),
            data=raw_body,
            content_type='application/json',
            **{SECRET_META_HEADER: channel.webhook_secret},
        )

    assert response.status_code == status.HTTP_413_REQUEST_ENTITY_TOO_LARGE
    delay.assert_not_called()


def test_content_length_above_limit_returns_413_without_reading_body(
    webhook_client: APIClient,
    channel,
    settings,
) -> None:
    settings.EVOLUTION_WEBHOOK_MAX_BODY_BYTES = 10

    response = webhook_client.generic(
        'POST',
        _url(channel),
        data=b'{}',
        content_type='application/json',
        CONTENT_LENGTH='11',
        **{SECRET_META_HEADER: channel.webhook_secret},
    )

    assert response.status_code == status.HTTP_413_REQUEST_ENTITY_TOO_LARGE


def test_payload_exactly_at_limit_is_accepted(
    webhook_client: APIClient,
    channel,
    settings,
) -> None:
    raw_body = json.dumps({'event': 'MESSAGES_UPSERT'}).encode('utf-8')
    settings.EVOLUTION_WEBHOOK_MAX_BODY_BYTES = len(raw_body)

    with patch(
        'omnichannel.evolution_webhook_views.process_evolution_channel_webhook_task.delay',
    ) as delay:
        response = webhook_client.generic(
            'POST',
            _url(channel),
            data=raw_body,
            content_type='application/json',
            **{SECRET_META_HEADER: channel.webhook_secret},
        )

    assert response.status_code == status.HTTP_200_OK
    delay.assert_called_once()


def test_new_event_reserves_cache_with_hash_only(
    webhook_client: APIClient,
    channel,
    settings,
) -> None:
    sensitive_body_value = 'private-message-content'
    payload = _payload(channel, data={'message': sensitive_body_value})

    with (
        patch('omnichannel.evolution_webhook_views.cache.add', return_value=True) as add,
        patch(
            'omnichannel.evolution_webhook_views.process_evolution_channel_webhook_task.delay',
        ),
    ):
        response = _post(
            webhook_client,
            channel,
            payload,
            secret=channel.webhook_secret,
        )

    assert response.status_code == status.HTTP_200_OK
    add.assert_called_once()
    cache_key = add.call_args.args[0]
    assert cache_key.startswith(f'evolution-webhook:{channel.id}:')
    assert sensitive_body_value not in cache_key
    assert channel.webhook_secret not in cache_key
    assert add.call_args.kwargs['timeout'] == settings.EVOLUTION_WEBHOOK_DEDUP_TTL_SECONDS


def test_duplicate_payload_returns_same_response_without_second_task(
    webhook_client: APIClient,
    channel,
) -> None:
    payload = _payload(channel)

    with patch(
        'omnichannel.evolution_webhook_views.process_evolution_channel_webhook_task.delay',
    ) as delay:
        first = _post(webhook_client, channel, payload, secret=channel.webhook_secret)
        duplicate = _post(webhook_client, channel, payload, secret=channel.webhook_secret)

    assert first.status_code == duplicate.status_code == status.HTTP_200_OK
    assert first.content == duplicate.content
    delay.assert_called_once_with(str(channel.id), payload)


def test_canonical_json_deduplicates_equivalent_key_order(
    webhook_client: APIClient,
    channel,
) -> None:
    first_payload = {'event': 'MESSAGES_UPSERT', 'data': {'a': 1, 'b': 2}}
    reordered_payload = {'data': {'b': 2, 'a': 1}, 'event': 'MESSAGES_UPSERT'}

    with patch(
        'omnichannel.evolution_webhook_views.process_evolution_channel_webhook_task.delay',
    ) as delay:
        first = _post(
            webhook_client,
            channel,
            first_payload,
            secret=channel.webhook_secret,
        )
        duplicate = _post(
            webhook_client,
            channel,
            reordered_payload,
            secret=channel.webhook_secret,
        )

    assert first.status_code == duplicate.status_code == status.HTTP_200_OK
    delay.assert_called_once()


def test_same_payload_in_different_channels_queues_each_channel(
    webhook_client: APIClient,
) -> None:
    first = WhatsAppChannelFactory(webhook_secret='first-secret')
    second = WhatsAppChannelFactory(webhook_secret='second-secret')
    payload = {'event': 'MESSAGES_UPSERT', 'data': {'same': True}}

    with patch(
        'omnichannel.evolution_webhook_views.process_evolution_channel_webhook_task.delay',
    ) as delay:
        first_response = _post(webhook_client, first, payload, secret=first.webhook_secret)
        second_response = _post(webhook_client, second, payload, secret=second.webhook_secret)

    assert first_response.status_code == second_response.status_code == 200
    assert delay.call_count == 2
    assert {call.args[0] for call in delay.call_args_list} == {str(first.id), str(second.id)}


def test_different_payloads_in_same_channel_queue_twice(
    webhook_client: APIClient,
    channel,
) -> None:
    first_payload = _payload(channel, data={'sequence': 1})
    second_payload = _payload(channel, data={'sequence': 2})

    with patch(
        'omnichannel.evolution_webhook_views.process_evolution_channel_webhook_task.delay',
    ) as delay:
        _post(webhook_client, channel, first_payload, secret=channel.webhook_secret)
        _post(webhook_client, channel, second_payload, secret=channel.webhook_secret)

    assert delay.call_count == 2


def test_cache_failure_returns_503_without_queue(
    webhook_client: APIClient,
    channel,
) -> None:
    with (
        patch(
            'omnichannel.evolution_webhook_views.cache.add',
            side_effect=RuntimeError('private-cache-error'),
        ),
        patch(
            'omnichannel.evolution_webhook_views.process_evolution_channel_webhook_task.delay',
        ) as delay,
    ):
        response = _post(
            webhook_client,
            channel,
            _payload(channel),
            secret=channel.webhook_secret,
        )

    assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
    assert response.json() == {'detail': 'Webhook temporariamente indisponível.'}
    delay.assert_not_called()


def test_queue_failure_releases_dedupe_and_next_attempt_can_queue(
    webhook_client: APIClient,
    channel,
) -> None:
    payload = _payload(channel)

    with patch(
        'omnichannel.evolution_webhook_views.process_evolution_channel_webhook_task.delay',
        side_effect=[RuntimeError('private-celery-error'), None],
    ) as delay:
        failed = _post(webhook_client, channel, payload, secret=channel.webhook_secret)
        retried = _post(webhook_client, channel, payload, secret=channel.webhook_secret)

    assert failed.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
    assert retried.status_code == status.HTTP_200_OK
    assert delay.call_count == 2


def test_queue_failure_explicitly_deletes_reserved_cache_key(
    webhook_client: APIClient,
    channel,
) -> None:
    with (
        patch('omnichannel.evolution_webhook_views.cache.add', return_value=True),
        patch('omnichannel.evolution_webhook_views.cache.delete') as delete,
        patch(
            'omnichannel.evolution_webhook_views.process_evolution_channel_webhook_task.delay',
            side_effect=RuntimeError('private-queue-error'),
        ),
    ):
        response = _post(
            webhook_client,
            channel,
            _payload(channel),
            secret=channel.webhook_secret,
        )

    assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
    delete.assert_called_once()
    assert delete.call_args.args[0].startswith(f'evolution-webhook:{channel.id}:')


@pytest.mark.parametrize(
    'setting_name',
    ['EVOLUTION_WEBHOOK_MAX_BODY_BYTES', 'EVOLUTION_WEBHOOK_DEDUP_TTL_SECONDS'],
)
def test_invalid_positive_integer_runtime_setting_fails_closed(
    setting_name: str,
    webhook_client: APIClient,
    channel,
    settings,
) -> None:
    setattr(settings, setting_name, 0)

    with patch(
        'omnichannel.evolution_webhook_views.process_evolution_channel_webhook_task.delay',
    ) as delay:
        response = _post(
            webhook_client,
            channel,
            _payload(channel),
            secret=channel.webhook_secret,
        )

    assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
    delay.assert_not_called()


def test_dedicated_throttle_returns_429_and_is_isolated_by_channel(
    webhook_client: APIClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(EvolutionChannelWebhookThrottle, 'rate', '1/minute', raising=False)
    first = WhatsAppChannelFactory(webhook_secret='first-throttle-secret')
    second = WhatsAppChannelFactory(webhook_secret='second-throttle-secret')

    with patch(
        'omnichannel.evolution_webhook_views.process_evolution_channel_webhook_task.delay',
    ):
        accepted = _post(webhook_client, first, {'sequence': 1}, secret=first.webhook_secret)
        throttled = _post(webhook_client, first, {'sequence': 2}, secret=first.webhook_secret)
        isolated = _post(webhook_client, second, {'sequence': 1}, secret=second.webhook_secret)

    assert accepted.status_code == status.HTTP_200_OK
    assert throttled.status_code == status.HTTP_429_TOO_MANY_REQUESTS
    assert isolated.status_code == status.HTTP_200_OK


def test_webhook_view_has_expected_public_security_configuration(settings) -> None:
    assert EvolutionChannelWebhookView.authentication_classes == []
    assert EvolutionChannelWebhookView.permission_classes
    assert EvolutionChannelWebhookThrottle.scope == 'evolution_channel_webhook'
    assert (
        settings.REST_FRAMEWORK['DEFAULT_THROTTLE_RATES']['evolution_channel_webhook']
        == '300/minute'
    )
    assert EVOLUTION_WEBHOOK_SECRET_HEADER == 'X-SilverTech-Webhook-Secret'


@pytest.mark.parametrize('method', ['get', 'put', 'patch', 'delete', 'head'])
def test_disallowed_methods_return_405_without_channel_disclosure(
    method: str,
    webhook_client: APIClient,
    channel,
) -> None:
    response = getattr(webhook_client, method)(_url(channel))

    assert response.status_code == status.HTTP_405_METHOD_NOT_ALLOWED


def test_options_is_allowed(webhook_client: APIClient, channel) -> None:
    response = webhook_client.options(_url(channel))

    assert response.status_code == status.HTTP_200_OK


def test_webhook_boundary_creates_no_domain_objects_or_ai_calls(
    webhook_client: APIClient,
    channel,
) -> None:
    baseline = (Contact.objects.count(), Conversation.objects.count(), Message.objects.count())

    with (
        patch(
            'omnichannel.evolution_webhook_views.process_evolution_channel_webhook_task.delay',
        ) as channel_task,
        patch('omnichannel.tasks.process_ai_response.delay') as ai_task,
        patch('omnichannel.views.process_whatsapp_webhook_task.delay') as legacy_task,
        patch('omnichannel.services.process_whatsapp_payload') as legacy_processor,
    ):
        response = _post(
            webhook_client,
            channel,
            _payload(channel),
            secret=channel.webhook_secret,
        )

    assert response.status_code == status.HTTP_200_OK
    assert (Contact.objects.count(), Conversation.objects.count(), Message.objects.count()) == baseline
    channel_task.assert_called_once()
    ai_task.assert_not_called()
    legacy_task.assert_not_called()
    legacy_processor.assert_not_called()


def test_payload_secret_qr_phone_and_query_never_appear_in_webhook_logs(
    webhook_client: APIClient,
    channel,
    caplog: pytest.LogCaptureFixture,
) -> None:
    sensitive_values = {
        'secret': channel.webhook_secret,
        'message': 'private-message-body',
        'phone': '5511999999999',
        'qr': 'private-qr-base64',
        'query': 'private-query-workspace',
    }
    payload = {
        'event': sensitive_values['message'],
        'instance': channel.instance_name,
        'data': {
            'message': sensitive_values['message'],
            'remoteJid': sensitive_values['phone'],
            'qrcode': sensitive_values['qr'],
        },
    }
    caplog.set_level(logging.INFO, logger='omnichannel.evolution_webhook_views')

    with patch(
        'omnichannel.evolution_webhook_views.process_evolution_channel_webhook_task.delay',
    ):
        response = _post(
            webhook_client,
            channel,
            payload,
            secret=channel.webhook_secret,
            query=f'?workspace={sensitive_values["query"]}',
        )

    assert response.status_code == status.HTTP_200_OK
    module_records = [
        record
        for record in caplog.records
        if record.name == 'omnichannel.evolution_webhook_views'
    ]
    serialized_records = ' '.join(
        f'{record.getMessage()} {record.__dict__}'
        for record in module_records
    )
    for sensitive_value in sensitive_values.values():
        assert sensitive_value not in serialized_records
    response_text = response.content.decode('utf-8')
    for forbidden in ('channel_id', 'workspace_id', 'webhook_public_id', 'event', 'duplicate'):
        assert forbidden not in response_text
