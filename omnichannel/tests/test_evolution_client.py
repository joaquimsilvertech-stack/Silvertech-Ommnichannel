from __future__ import annotations

import inspect
import logging
from typing import Any
from unittest.mock import Mock, patch

import pytest
import requests
from django.test import override_settings

from omnichannel import services
from omnichannel.evolution import (
    EvolutionAPIClient,
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
    get_evolution_client,
)
from omnichannel.evolution.endpoints import (
    CONNECT_INSTANCE_PATH,
    CONNECTION_STATE_PATH,
    CREATE_INSTANCE_PATH,
    DELETE_INSTANCE_PATH,
    LOGOUT_INSTANCE_PATH,
    RESTART_INSTANCE_PATH,
    SEND_TEXT_PATH,
    SET_WEBHOOK_PATH,
)


class StubResponse:
    def __init__(
        self,
        *,
        status_code: int = 200,
        json_data: Any = None,
        content: bytes = b'{}',
        json_exception: Exception | None = None,
    ) -> None:
        self.status_code = status_code
        self.content = content
        self._json_data = {} if json_data is None else json_data
        self._json_exception = json_exception

    def json(self) -> Any:
        if self._json_exception is not None:
            raise self._json_exception
        return self._json_data


@pytest.fixture
def mock_session() -> Mock:
    session = Mock(spec=requests.Session)
    session.request.return_value = StubResponse(json_data={'ok': True})
    return session


@pytest.fixture
def evolution_client(mock_session: Mock) -> EvolutionAPIClient:
    return EvolutionAPIClient(
        base_url='http://evolution.test/',
        api_key='safe-test-api-key',
        timeout_seconds=17,
        session=mock_session,
    )


@pytest.mark.parametrize('base_url', ['', '   ', None])
def test_client_rejects_empty_base_url(base_url: str | None) -> None:
    with pytest.raises(EvolutionConfigurationError):
        EvolutionAPIClient(base_url=base_url, api_key='key')  # type: ignore[arg-type]


@pytest.mark.parametrize('api_key', ['', '   ', None])
def test_client_rejects_empty_api_key(api_key: str | None) -> None:
    with pytest.raises(EvolutionConfigurationError):
        EvolutionAPIClient(base_url='http://evolution.test', api_key=api_key)  # type: ignore[arg-type]


@pytest.mark.parametrize('timeout', [0, -1, True, float('inf'), float('nan'), '30'])
def test_client_rejects_invalid_timeout(timeout: Any) -> None:
    with pytest.raises(EvolutionConfigurationError):
        EvolutionAPIClient(
            base_url='http://evolution.test',
            api_key='key',
            timeout_seconds=timeout,
        )


def test_client_normalizes_base_url_and_has_safe_repr(mock_session: Mock) -> None:
    client = EvolutionAPIClient(
        base_url=' HTTPS://evolution.test/api/// ',
        api_key='super-secret-key',
        session=mock_session,
    )

    assert client.base_url == 'https://evolution.test/api'
    assert 'super-secret-key' not in repr(client)
    assert '<redacted>' in repr(client)


@pytest.mark.parametrize(
    'base_url',
    [
        'ftp://evolution.test',
        'evolution.test',
        'http://',
        'http://user:password@evolution.test',
        'http://evolution.test?token=secret',
        'http://evolution.test/#fragment',
        'http://evolution.test:99999',
    ],
)
def test_client_rejects_invalid_base_url(base_url: str) -> None:
    with pytest.raises(EvolutionConfigurationError):
        EvolutionAPIClient(base_url=base_url, api_key='key')


def test_session_is_injectable_and_constructor_does_not_request(mock_session: Mock) -> None:
    client = EvolutionAPIClient(
        base_url='http://evolution.test',
        api_key='key',
        session=mock_session,
    )

    assert client.session is mock_session
    mock_session.request.assert_not_called()


def test_request_uses_auth_content_type_and_timeout(
    evolution_client: EvolutionAPIClient,
    mock_session: Mock,
) -> None:
    evolution_client.send_text(instance_name='main', number='5511000000000', text='Oi')

    call = mock_session.request.call_args
    assert call.kwargs['headers'] == {
        'apikey': 'safe-test-api-key',
        'Content-Type': 'application/json',
    }
    assert call.kwargs['timeout'] == 17


def test_get_request_omits_content_type_and_json_body(
    evolution_client: EvolutionAPIClient,
    mock_session: Mock,
) -> None:
    evolution_client.get_connection_state(instance_name='main')

    call = mock_session.request.call_args
    assert call.kwargs['headers'] == {'apikey': 'safe-test-api-key'}
    assert 'json' not in call.kwargs


def test_create_instance_contract(
    evolution_client: EvolutionAPIClient,
    mock_session: Mock,
) -> None:
    evolution_client.create_instance(
        instance_name=' tenant-main ',
        qrcode=False,
        integration='whatsapp-baileys',
    )

    call = mock_session.request.call_args
    assert call.kwargs['method'] == 'POST'
    assert call.kwargs['url'] == f'http://evolution.test{CREATE_INSTANCE_PATH}'
    assert call.kwargs['json'] == {
        'instanceName': 'tenant-main',
        'qrcode': False,
        'integration': 'WHATSAPP-BAILEYS',
    }


def test_configure_webhook_contract_normalizes_events(
    evolution_client: EvolutionAPIClient,
    mock_session: Mock,
) -> None:
    evolution_client.configure_webhook(
        instance_name='main',
        url='http://localhost:8000/api/webhook/?source=test',
        events=['MESSAGES_UPSERT', 'CONNECTION_UPDATE', 'MESSAGES_UPSERT'],
        enabled=True,
        webhook_by_events=True,
        headers={'X-Webhook-Secret': 'safe-secret'},
    )

    call = mock_session.request.call_args
    assert call.kwargs['method'] == 'POST'
    assert call.kwargs['url'] == 'http://evolution.test/webhook/set/main'
    assert call.kwargs['json'] == {
        'webhook': {
            'enabled': True,
            'url': 'http://localhost:8000/api/webhook/?source=test',
            'byEvents': True,
            'base64': False,
            'events': ['MESSAGES_UPSERT', 'CONNECTION_UPDATE'],
            'headers': {'X-Webhook-Secret': 'safe-secret'},
        },
    }


@pytest.mark.parametrize(
    ('method_name', 'expected_method', 'expected_path'),
    [
        ('get_qr_code', 'GET', CONNECT_INSTANCE_PATH),
        ('get_connection_state', 'GET', CONNECTION_STATE_PATH),
        ('restart_instance', 'PUT', RESTART_INSTANCE_PATH),
        ('logout_instance', 'DELETE', LOGOUT_INSTANCE_PATH),
        ('delete_instance', 'DELETE', DELETE_INSTANCE_PATH),
    ],
)
def test_instance_operation_contracts(
    method_name: str,
    expected_method: str,
    expected_path: str,
    evolution_client: EvolutionAPIClient,
    mock_session: Mock,
) -> None:
    method = getattr(evolution_client, method_name)
    method(instance_name='main')

    call = mock_session.request.call_args
    assert call.kwargs['method'] == expected_method
    assert call.kwargs['url'] == f"http://evolution.test{expected_path.format(instance_name='main')}"


def test_restart_instance_uses_put_once_without_body_retry_or_secret_leak(
    evolution_client: EvolutionAPIClient,
    mock_session: Mock,
    caplog: pytest.LogCaptureFixture,
) -> None:
    mock_session.request.return_value = StubResponse(status_code=503, content=b'private-body')
    caplog.set_level(logging.INFO, logger='omnichannel.evolution.client')

    with pytest.raises(EvolutionUnavailableError) as exc_info:
        evolution_client.restart_instance(instance_name='main')

    mock_session.request.assert_called_once()
    call = mock_session.request.call_args
    assert call.kwargs['method'] == 'PUT'
    assert call.kwargs['url'] == (
        f"http://evolution.test{RESTART_INSTANCE_PATH.format(instance_name='main')}"
    )
    assert 'json' not in call.kwargs
    assert 'safe-test-api-key' not in str(exc_info.value)
    assert 'safe-test-api-key' not in caplog.text


def test_send_text_contract_preserves_unicode(
    evolution_client: EvolutionAPIClient,
    mock_session: Mock,
) -> None:
    message = 'Ol\u00e1, mundo \U0001f44b'

    evolution_client.send_text(
        instance_name='main',
        number=' +5511999999999 ',
        text=message,
    )

    call = mock_session.request.call_args
    assert call.kwargs['method'] == 'POST'
    assert call.kwargs['url'] == f'http://evolution.test{SEND_TEXT_PATH.format(instance_name="main")}'
    assert call.kwargs['json'] == {
        'number': '+5511999999999',
        'text': message,
    }


@pytest.mark.parametrize(
    ('instance_name', 'encoded'),
    [
        ('tenant/name', 'tenant%2Fname'),
        ('../tenant?x=1', '..%2Ftenant%3Fx%3D1'),
        ('tenant%2Fname', 'tenant%252Fname'),
        ('instancia com espaco', 'instancia%20com%20espaco'),
    ],
)
def test_instance_name_is_encoded_as_single_path_segment(
    instance_name: str,
    encoded: str,
    evolution_client: EvolutionAPIClient,
    mock_session: Mock,
) -> None:
    evolution_client.get_qr_code(instance_name=instance_name)

    assert mock_session.request.call_args.kwargs['url'].endswith(f'/instance/connect/{encoded}')


@pytest.mark.parametrize(
    'instance_name',
    ['', '   ', 'bad\nname', 'x' * 129, None],
)
def test_instance_name_validation_rejects_invalid_values(
    instance_name: str | None,
    evolution_client: EvolutionAPIClient,
    mock_session: Mock,
) -> None:
    with pytest.raises(EvolutionInvalidRequestError):
        evolution_client.get_qr_code(instance_name=instance_name)  # type: ignore[arg-type]

    mock_session.request.assert_not_called()


@pytest.mark.parametrize('number', ['', '   ', '55\n11', None])
def test_number_validation_rejects_invalid_values(
    number: str | None,
    evolution_client: EvolutionAPIClient,
    mock_session: Mock,
) -> None:
    with pytest.raises(EvolutionInvalidRequestError):
        evolution_client.send_text(
            instance_name='main',
            number=number,  # type: ignore[arg-type]
            text='Oi',
        )

    mock_session.request.assert_not_called()


@pytest.mark.parametrize('text', ['', '   ', '\n\t', None])
def test_text_validation_rejects_empty_values(
    text: str | None,
    evolution_client: EvolutionAPIClient,
    mock_session: Mock,
) -> None:
    with pytest.raises(EvolutionInvalidRequestError):
        evolution_client.send_text(
            instance_name='main',
            number='5511000000000',
            text=text,  # type: ignore[arg-type]
        )

    mock_session.request.assert_not_called()


@pytest.mark.parametrize(
    'url',
    [
        '',
        'not-a-url',
        'ftp://webhook.test/path',
        'https://user:password@webhook.test/path',
        'https://webhook.test/path with space',
        'https://webhook.test:99999/path',
    ],
)
def test_webhook_url_validation_rejects_invalid_values(
    url: str,
    evolution_client: EvolutionAPIClient,
    mock_session: Mock,
) -> None:
    with pytest.raises(EvolutionInvalidRequestError):
        evolution_client.configure_webhook(
            instance_name='main',
            url=url,
            events=['MESSAGES_UPSERT'],
        )

    mock_session.request.assert_not_called()


@pytest.mark.parametrize('events', [[], [''], ['   '], ['VALID', 1], 'VALID'])
def test_events_validation_rejects_invalid_values(
    events: Any,
    evolution_client: EvolutionAPIClient,
    mock_session: Mock,
) -> None:
    with pytest.raises(EvolutionInvalidRequestError):
        evolution_client.configure_webhook(
            instance_name='main',
            url='https://webhook.test/path',
            events=events,
        )

    mock_session.request.assert_not_called()


@pytest.mark.parametrize(
    'header_name',
    ['apikey', 'APIKEY', 'Authorization', 'Content-Type', 'Host', 'Content-Length'],
)
def test_webhook_headers_cannot_override_protected_headers(
    header_name: str,
    evolution_client: EvolutionAPIClient,
    mock_session: Mock,
) -> None:
    with pytest.raises(EvolutionInvalidRequestError):
        evolution_client.configure_webhook(
            instance_name='main',
            url='https://webhook.test/path',
            events=['MESSAGES_UPSERT'],
            headers={header_name: 'secret'},
        )

    mock_session.request.assert_not_called()


@pytest.mark.parametrize(
    'headers',
    [
        {'Invalid Header': 'value'},
        {'X-Test': 'value\r\ninjected'},
        {'X-Test': 10},
        [('X-Test', 'value')],
    ],
)
def test_webhook_headers_reject_malformed_names_values_and_types(
    headers: Any,
    evolution_client: EvolutionAPIClient,
) -> None:
    with pytest.raises(EvolutionInvalidRequestError):
        evolution_client.configure_webhook(
            instance_name='main',
            url='https://webhook.test/path',
            events=['MESSAGES_UPSERT'],
            headers=headers,
        )


def test_valid_json_object_is_returned(
    evolution_client: EvolutionAPIClient,
    mock_session: Mock,
) -> None:
    expected = {'instance': {'state': 'open'}}
    mock_session.request.return_value = StubResponse(json_data=expected)

    result = evolution_client.get_connection_state(instance_name='main')

    assert result == expected


@pytest.mark.parametrize(
    ('status_code', 'content'),
    [(204, b''), (200, b''), (201, b'')],
)
def test_no_content_or_empty_success_body_returns_empty_dict(
    status_code: int,
    content: bytes,
    evolution_client: EvolutionAPIClient,
    mock_session: Mock,
) -> None:
    response = StubResponse(status_code=status_code, content=content)
    response.json = Mock(side_effect=AssertionError('json() nao deveria ser chamado'))
    mock_session.request.return_value = response

    assert evolution_client.get_qr_code(instance_name='main') == {}
    response.json.assert_not_called()


def test_invalid_json_raises_safe_invalid_response_error(
    evolution_client: EvolutionAPIClient,
    mock_session: Mock,
) -> None:
    mock_session.request.return_value = StubResponse(
        content=b'not-json',
        json_exception=ValueError('raw response secret'),
    )

    with pytest.raises(EvolutionInvalidResponseError) as exc_info:
        evolution_client.get_qr_code(instance_name='main')

    assert 'raw response secret' not in str(exc_info.value)


@pytest.mark.parametrize('json_data', [[], ['item'], 'text', 10, True])
def test_non_object_json_root_is_rejected(
    json_data: Any,
    evolution_client: EvolutionAPIClient,
    mock_session: Mock,
) -> None:
    mock_session.request.return_value = StubResponse(json_data=json_data)

    with pytest.raises(EvolutionInvalidResponseError):
        evolution_client.get_qr_code(instance_name='main')


@pytest.mark.parametrize(
    ('status_code', 'exception_class'),
    [
        (400, EvolutionInvalidRequestError),
        (401, EvolutionAuthenticationError),
        (403, EvolutionAuthenticationError),
        (404, EvolutionNotFoundError),
        (409, EvolutionConflictError),
        (422, EvolutionInvalidRequestError),
        (429, EvolutionRateLimitError),
        (500, EvolutionUnavailableError),
        (502, EvolutionUnavailableError),
        (503, EvolutionUnavailableError),
        (504, EvolutionUnavailableError),
        (418, EvolutionUnexpectedResponseError),
    ],
)
def test_http_status_is_mapped_to_safe_exception(
    status_code: int,
    exception_class: type[EvolutionAPIError],
    evolution_client: EvolutionAPIClient,
    mock_session: Mock,
) -> None:
    mock_session.request.return_value = StubResponse(
        status_code=status_code,
        content=b'raw response must stay private',
    )

    with pytest.raises(exception_class) as exc_info:
        evolution_client.send_text(instance_name='main', number='5511000000000', text='Oi')

    assert exc_info.value.status_code == status_code
    assert 'raw response must stay private' not in str(exc_info.value)
    assert mock_session.request.call_count == 1


@pytest.mark.parametrize(
    ('request_exception', 'exception_class', 'retryable'),
    [
        (requests.exceptions.Timeout('private-url'), EvolutionTimeoutError, True),
        (requests.exceptions.ConnectionError('private-url'), EvolutionConnectionError, True),
        (requests.exceptions.RequestException('private-url'), EvolutionAPIError, True),
    ],
)
def test_network_errors_are_converted_without_retry(
    request_exception: Exception,
    exception_class: type[EvolutionAPIError],
    retryable: bool,
    evolution_client: EvolutionAPIClient,
    mock_session: Mock,
) -> None:
    mock_session.request.side_effect = request_exception

    with pytest.raises(exception_class) as exc_info:
        evolution_client.send_text(instance_name='main', number='5511000000000', text='Oi')

    assert exc_info.value.retryable is retryable
    assert 'private-url' not in str(exc_info.value)
    assert mock_session.request.call_count == 1


def test_logs_never_include_api_key_phone_text_qr_headers_or_response_body(
    mock_session: Mock,
    caplog: pytest.LogCaptureFixture,
) -> None:
    secrets = {
        'api_key': 'secret-api-key-value',
        'phone': '5511888888888',
        'text': 'private-message-text',
        'qr': 'private-qr-base64',
        'header': 'private-webhook-header',
        'body': 'private-response-body',
    }
    client = EvolutionAPIClient(
        base_url='http://evolution.test',
        api_key=secrets['api_key'],
        session=mock_session,
    )
    caplog.set_level(logging.INFO, logger='omnichannel.evolution.client')

    mock_session.request.return_value = StubResponse(json_data={'qrcode': secrets['qr']})
    assert client.get_qr_code(instance_name='main')['qrcode'] == secrets['qr']

    mock_session.request.return_value = StubResponse(json_data={'ok': True})
    client.send_text(instance_name='main', number=secrets['phone'], text=secrets['text'])
    client.configure_webhook(
        instance_name='main',
        url='https://webhook.test/path?secret=private-query',
        events=['MESSAGES_UPSERT'],
        headers={'X-Webhook-Secret': secrets['header']},
    )

    mock_session.request.return_value = StubResponse(
        status_code=500,
        content=secrets['body'].encode(),
    )
    with pytest.raises(EvolutionUnavailableError):
        client.get_connection_state(instance_name='main')

    serialized_logs = ' '.join(
        f'{record.getMessage()} {record.__dict__}'
        for record in caplog.records
    )
    for secret in secrets.values():
        assert secret not in serialized_logs
    assert 'private-query' not in serialized_logs


def test_evolution_package_has_no_database_or_celery_dependency() -> None:
    source = inspect.getsource(inspect.getmodule(EvolutionAPIClient))

    assert 'django.db' not in source
    assert 'celery' not in source.lower()


def test_endpoint_paths_are_centralized() -> None:
    assert CREATE_INSTANCE_PATH == '/instance/create'
    assert SET_WEBHOOK_PATH == '/webhook/set/{instance_name}'
    assert CONNECT_INSTANCE_PATH == '/instance/connect/{instance_name}'
    assert CONNECTION_STATE_PATH == '/instance/connectionState/{instance_name}'
    assert SEND_TEXT_PATH == '/message/sendText/{instance_name}'
    assert RESTART_INSTANCE_PATH == '/instance/restart/{instance_name}'
    assert LOGOUT_INSTANCE_PATH == '/instance/logout/{instance_name}'
    assert DELETE_INSTANCE_PATH == '/instance/delete/{instance_name}'


@override_settings(
    EVOLUTION_API_URL='http://settings-evolution.test/',
    EVOLUTION_API_KEY='settings-api-key',
    EVOLUTION_API_TIMEOUT_SECONDS=23,
)
def test_factory_builds_client_from_settings_without_instance_name() -> None:
    with patch('omnichannel.evolution.client.requests.Session') as session_class:
        client = get_evolution_client()

    assert client.base_url == 'http://settings-evolution.test'
    assert client.timeout_seconds == 23
    assert 'settings-api-key' not in repr(client)
    session_class.assert_called_once_with()


@override_settings(EVOLUTION_INSTANCE_NAME='legacy-global-instance')
def test_legacy_wrapper_delegates_to_client_and_returns_response() -> None:
    client = Mock()
    client.send_text.return_value = {'key': {'id': 'message-id'}}

    with patch('omnichannel.services.get_evolution_client', return_value=client) as factory:
        result = services.send_whatsapp_message('5511999999999', 'Mensagem legada')

    assert result == {'key': {'id': 'message-id'}}
    factory.assert_called_once_with()
    client.send_text.assert_called_once_with(
        instance_name='legacy-global-instance',
        number='5511999999999',
        text='Mensagem legada',
    )


def test_legacy_wrapper_keeps_public_signature_and_has_no_direct_http_or_channel_lookup() -> None:
    signature = inspect.signature(services.send_whatsapp_message)
    source = inspect.getsource(services.send_whatsapp_message)

    assert list(signature.parameters) == ['phone', 'text']
    assert signature.return_annotation == 'dict[str, Any]'
    assert 'requests.' not in source
    assert 'WhatsAppChannel' not in source
    assert 'Conversation' not in source
    assert 'EVOLUTION_API_URL' not in source
    assert 'EVOLUTION_API_KEY' not in source
    assert 'settings.EVOLUTION_INSTANCE_NAME' in source


@override_settings(
    EVOLUTION_INSTANCE_NAME='',
    EVOLUTION_API_KEY='api-key-must-not-leak',
)
def test_legacy_wrapper_rejects_missing_instance_with_safe_configuration_error() -> None:
    with (
        patch('omnichannel.services.get_evolution_client') as factory,
        pytest.raises(EvolutionConfigurationError) as exc_info,
    ):
        services.send_whatsapp_message('5511999999999', 'Mensagem')

    factory.assert_not_called()
    assert 'api-key-must-not-leak' not in str(exc_info.value)
