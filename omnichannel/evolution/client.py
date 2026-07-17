from __future__ import annotations

import logging
import math
import re
import unicodedata
from typing import Any
from urllib.parse import quote, urlsplit, urlunsplit

import requests
from django.conf import settings

from .base import BaseEvolutionClient
from .endpoints import (
    CONNECT_INSTANCE_PATH,
    CONNECTION_STATE_PATH,
    CREATE_INSTANCE_PATH,
    DELETE_INSTANCE_PATH,
    LOGOUT_INSTANCE_PATH,
    RESTART_INSTANCE_PATH,
    SEND_TEXT_PATH,
    SET_WEBHOOK_PATH,
)
from .exceptions import (
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
from .types import (
    MAX_INSTANCE_NAME_LENGTH,
    SUPPORTED_INTEGRATIONS,
    EvolutionResponse,
)

logger = logging.getLogger(__name__)

_HEADER_NAME_PATTERN = re.compile(r"^[!#$%&'*+\-.^_`|~0-9A-Za-z]+$")
_PROTECTED_HEADER_NAMES = frozenset(
    {
        'apikey',
        'authorization',
        'content-type',
        'host',
        'content-length',
    },
)


class EvolutionAPIClient(BaseEvolutionClient):
    """Adapter HTTP central para o contrato Evolution API v2."""

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        timeout_seconds: int | float = 30,
        session: requests.Session | None = None,
    ) -> None:
        self.base_url = self._normalize_base_url(base_url)
        self._api_key = self._normalize_api_key(api_key)
        self.timeout_seconds = self._validate_timeout(timeout_seconds)
        self.session = session if session is not None else requests.Session()

    def __repr__(self) -> str:
        return (
            f'{type(self).__name__}(base_url={self.base_url!r}, '
            f'api_key=<redacted>, timeout_seconds={self.timeout_seconds!r})'
        )

    def create_instance(
        self,
        *,
        instance_name: str,
        qrcode: bool = True,
        integration: str = 'WHATSAPP-BAILEYS',
    ) -> EvolutionResponse:
        normalized_instance = self._normalize_instance_name(instance_name)
        normalized_integration = self._normalize_integration(integration)
        return self._request(
            method='POST',
            path=CREATE_INSTANCE_PATH,
            operation='create_instance',
            json_body={
                'instanceName': normalized_instance,
                'qrcode': bool(qrcode),
                'integration': normalized_integration,
            },
        )

    def configure_webhook(
        self,
        *,
        instance_name: str,
        url: str,
        events: list[str],
        enabled: bool = True,
        webhook_by_events: bool = False,
        headers: dict[str, str] | None = None,
    ) -> EvolutionResponse:
        encoded_instance = self._encode_instance_name(instance_name)
        normalized_url = self._normalize_webhook_url(url)
        normalized_events = self._normalize_events(events)
        normalized_headers = self._normalize_webhook_headers(headers)
        webhook: dict[str, Any] = {
            'enabled': bool(enabled),
            'url': normalized_url,
            'byEvents': bool(webhook_by_events),
            'base64': False,
            'events': normalized_events,
        }
        if normalized_headers:
            webhook['headers'] = normalized_headers

        return self._request(
            method='POST',
            path=SET_WEBHOOK_PATH.format(instance_name=encoded_instance),
            operation='configure_webhook',
            json_body={'webhook': webhook},
        )

    def get_qr_code(self, *, instance_name: str) -> EvolutionResponse:
        encoded_instance = self._encode_instance_name(instance_name)
        return self._request(
            method='GET',
            path=CONNECT_INSTANCE_PATH.format(instance_name=encoded_instance),
            operation='get_qr_code',
        )

    def get_connection_state(self, *, instance_name: str) -> EvolutionResponse:
        encoded_instance = self._encode_instance_name(instance_name)
        return self._request(
            method='GET',
            path=CONNECTION_STATE_PATH.format(instance_name=encoded_instance),
            operation='get_connection_state',
        )

    def send_text(
        self,
        *,
        instance_name: str,
        number: str,
        text: str,
    ) -> EvolutionResponse:
        encoded_instance = self._encode_instance_name(instance_name)
        normalized_number = self._normalize_number(number)
        normalized_text = self._validate_text(text)
        return self._request(
            method='POST',
            path=SEND_TEXT_PATH.format(instance_name=encoded_instance),
            operation='send_text',
            json_body={
                'number': normalized_number,
                'text': normalized_text,
            },
        )

    def restart_instance(self, *, instance_name: str) -> EvolutionResponse:
        encoded_instance = self._encode_instance_name(instance_name)
        return self._request(
            method='POST',
            path=RESTART_INSTANCE_PATH.format(instance_name=encoded_instance),
            operation='restart_instance',
        )

    def logout_instance(self, *, instance_name: str) -> EvolutionResponse:
        encoded_instance = self._encode_instance_name(instance_name)
        return self._request(
            method='DELETE',
            path=LOGOUT_INSTANCE_PATH.format(instance_name=encoded_instance),
            operation='logout_instance',
        )

    def delete_instance(self, *, instance_name: str) -> EvolutionResponse:
        encoded_instance = self._encode_instance_name(instance_name)
        return self._request(
            method='DELETE',
            path=DELETE_INSTANCE_PATH.format(instance_name=encoded_instance),
            operation='delete_instance',
        )

    def _request(
        self,
        *,
        method: str,
        path: str,
        operation: str,
        json_body: dict[str, Any] | None = None,
        extra_headers: dict[str, str] | None = None,
    ) -> EvolutionResponse:
        headers = {'apikey': self._api_key}
        if json_body is not None:
            headers['Content-Type'] = 'application/json'
        if extra_headers:
            headers.update(self._normalize_request_headers(extra_headers))

        request_kwargs: dict[str, Any] = {
            'headers': headers,
            'timeout': self.timeout_seconds,
        }
        if json_body is not None:
            request_kwargs['json'] = json_body

        logger.info(
            'Chamada a Evolution API iniciada',
            extra={'operation': operation, 'http_method': method},
        )
        try:
            response = self.session.request(
                method=method,
                url=f'{self.base_url}{path}',
                **request_kwargs,
            )
        except requests.exceptions.Timeout as exc:
            error = EvolutionTimeoutError(operation=operation)
            self._log_failure(error, method=method, exception_type=type(exc).__name__)
            raise error from exc
        except requests.exceptions.ConnectionError as exc:
            error = EvolutionConnectionError(operation=operation)
            self._log_failure(error, method=method, exception_type=type(exc).__name__)
            raise error from exc
        except requests.exceptions.RequestException as exc:
            error = EvolutionAPIError(operation=operation, retryable=True)
            self._log_failure(error, method=method, exception_type=type(exc).__name__)
            raise error from exc

        status_code = getattr(response, 'status_code', None)
        if not isinstance(status_code, int):
            error = EvolutionInvalidResponseError(operation=operation)
            self._log_failure(error, method=method, exception_type=type(response).__name__)
            raise error
        if not 200 <= status_code < 300:
            error = self._build_http_error(operation=operation, status_code=status_code)
            self._log_failure(error, method=method)
            raise error

        if status_code == 204 or not getattr(response, 'content', b''):
            result: EvolutionResponse = {}
        else:
            try:
                parsed = response.json()
            except (TypeError, ValueError) as exc:
                error = EvolutionInvalidResponseError(
                    operation=operation,
                    status_code=status_code,
                )
                self._log_failure(error, method=method, exception_type=type(exc).__name__)
                raise error from exc
            if not isinstance(parsed, dict):
                error = EvolutionInvalidResponseError(
                    operation=operation,
                    status_code=status_code,
                )
                self._log_failure(error, method=method, exception_type=type(parsed).__name__)
                raise error
            result = parsed

        logger.info(
            'Chamada a Evolution API concluida',
            extra={
                'operation': operation,
                'http_method': method,
                'status_code': status_code,
            },
        )
        return result

    @staticmethod
    def _normalize_base_url(base_url: str) -> str:
        if not isinstance(base_url, str) or not base_url.strip():
            raise EvolutionConfigurationError()
        candidate = base_url.strip()
        if EvolutionAPIClient._has_control_characters(candidate):
            raise EvolutionConfigurationError()

        parsed = urlsplit(candidate)
        try:
            parsed_port = parsed.port
        except ValueError as exc:
            raise EvolutionConfigurationError() from exc
        if (
            parsed.scheme.lower() not in {'http', 'https'}
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
            or parsed_port is not None and not 1 <= parsed_port <= 65535
        ):
            raise EvolutionConfigurationError()

        normalized_path = parsed.path.rstrip('/')
        return urlunsplit(
            (
                parsed.scheme.lower(),
                parsed.netloc,
                normalized_path,
                '',
                '',
            ),
        )

    @staticmethod
    def _normalize_api_key(api_key: str) -> str:
        if not isinstance(api_key, str) or not api_key.strip():
            raise EvolutionConfigurationError()
        if EvolutionAPIClient._has_control_characters(api_key):
            raise EvolutionConfigurationError()
        return api_key.strip()

    @staticmethod
    def _validate_timeout(timeout_seconds: int | float) -> int | float:
        if isinstance(timeout_seconds, bool) or not isinstance(timeout_seconds, (int, float)):
            raise EvolutionConfigurationError()
        if timeout_seconds <= 0 or not math.isfinite(float(timeout_seconds)):
            raise EvolutionConfigurationError()
        return timeout_seconds

    @staticmethod
    def _normalize_instance_name(instance_name: str) -> str:
        if not isinstance(instance_name, str):
            raise EvolutionInvalidRequestError(operation='validate_instance_name')
        normalized = instance_name.strip()
        if (
            not normalized
            or len(normalized) > MAX_INSTANCE_NAME_LENGTH
            or EvolutionAPIClient._has_control_characters(normalized)
        ):
            raise EvolutionInvalidRequestError(operation='validate_instance_name')
        return normalized

    @classmethod
    def _encode_instance_name(cls, instance_name: str) -> str:
        return quote(cls._normalize_instance_name(instance_name), safe='')

    @staticmethod
    def _normalize_integration(integration: str) -> str:
        if not isinstance(integration, str):
            raise EvolutionInvalidRequestError(operation='create_instance')
        normalized = integration.strip().upper()
        if normalized not in SUPPORTED_INTEGRATIONS:
            raise EvolutionInvalidRequestError(operation='create_instance')
        return normalized

    @staticmethod
    def _normalize_number(number: str) -> str:
        if not isinstance(number, str):
            raise EvolutionInvalidRequestError(operation='send_text')
        normalized = number.strip()
        if not normalized or EvolutionAPIClient._has_control_characters(normalized):
            raise EvolutionInvalidRequestError(operation='send_text')
        return normalized

    @staticmethod
    def _validate_text(text: str) -> str:
        if not isinstance(text, str) or not text.strip():
            raise EvolutionInvalidRequestError(operation='send_text')
        return text

    @staticmethod
    def _normalize_webhook_url(url: str) -> str:
        if not isinstance(url, str) or not url.strip():
            raise EvolutionInvalidRequestError(operation='configure_webhook')
        normalized = url.strip()
        if any(character.isspace() for character in normalized):
            raise EvolutionInvalidRequestError(operation='configure_webhook')
        parsed = urlsplit(normalized)
        try:
            parsed_port = parsed.port
        except ValueError as exc:
            raise EvolutionInvalidRequestError(operation='configure_webhook') from exc
        if (
            parsed.scheme.lower() not in {'http', 'https'}
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed_port is not None and not 1 <= parsed_port <= 65535
        ):
            raise EvolutionInvalidRequestError(operation='configure_webhook')
        return normalized

    @staticmethod
    def _normalize_events(events: list[str]) -> list[str]:
        if not isinstance(events, list) or not events:
            raise EvolutionInvalidRequestError(operation='configure_webhook')
        normalized_events: list[str] = []
        seen: set[str] = set()
        for event in events:
            if not isinstance(event, str):
                raise EvolutionInvalidRequestError(operation='configure_webhook')
            normalized = event.strip()
            if not normalized or EvolutionAPIClient._has_control_characters(normalized):
                raise EvolutionInvalidRequestError(operation='configure_webhook')
            if normalized not in seen:
                seen.add(normalized)
                normalized_events.append(normalized)
        return normalized_events

    @classmethod
    def _normalize_webhook_headers(
        cls,
        headers: dict[str, str] | None,
    ) -> dict[str, str]:
        if headers is None:
            return {}
        if not isinstance(headers, dict):
            raise EvolutionInvalidRequestError(operation='configure_webhook')
        normalized: dict[str, str] = {}
        for raw_name, raw_value in headers.items():
            if not isinstance(raw_name, str) or not isinstance(raw_value, str):
                raise EvolutionInvalidRequestError(operation='configure_webhook')
            name = raw_name.strip()
            if (
                not name
                or not _HEADER_NAME_PATTERN.fullmatch(name)
                or name.lower() in _PROTECTED_HEADER_NAMES
                or cls._has_control_characters(raw_value)
            ):
                raise EvolutionInvalidRequestError(operation='configure_webhook')
            normalized[name] = raw_value
        return normalized

    @classmethod
    def _normalize_request_headers(cls, headers: dict[str, str]) -> dict[str, str]:
        normalized = cls._normalize_webhook_headers(headers)
        return normalized

    @staticmethod
    def _has_control_characters(value: str) -> bool:
        return any(unicodedata.category(character) == 'Cc' for character in value)

    @staticmethod
    def _build_http_error(
        *,
        operation: str,
        status_code: int,
    ) -> EvolutionAPIError:
        exception_class: type[EvolutionAPIError]
        if status_code in {400, 422}:
            exception_class = EvolutionInvalidRequestError
        elif status_code in {401, 403}:
            exception_class = EvolutionAuthenticationError
        elif status_code == 404:
            exception_class = EvolutionNotFoundError
        elif status_code == 409:
            exception_class = EvolutionConflictError
        elif status_code == 429:
            exception_class = EvolutionRateLimitError
        elif status_code in {500, 502, 503, 504}:
            exception_class = EvolutionUnavailableError
        else:
            exception_class = EvolutionUnexpectedResponseError
        return exception_class(operation=operation, status_code=status_code)

    @staticmethod
    def _log_failure(
        error: EvolutionAPIError,
        *,
        method: str,
        exception_type: str | None = None,
    ) -> None:
        logger.warning(
            'Chamada a Evolution API falhou',
            extra={
                'operation': error.operation,
                'http_method': method,
                'status_code': error.status_code,
                'error_code': error.error_code,
                'exception_type': exception_type or type(error).__name__,
            },
        )


def get_evolution_client() -> EvolutionAPIClient:
    """Cria o adapter a partir das configuracoes globais sem resolver instancia."""
    return EvolutionAPIClient(
        base_url=getattr(settings, 'EVOLUTION_API_URL', ''),
        api_key=getattr(settings, 'EVOLUTION_API_KEY', ''),
        timeout_seconds=getattr(settings, 'EVOLUTION_API_TIMEOUT_SECONDS', 30),
    )

