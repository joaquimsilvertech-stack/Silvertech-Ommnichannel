from __future__ import annotations

import pytest

from omnichannel.ai.exceptions import AIProviderInvalidRequestError
from omnichannel.ai.providers.openai_settings import validate_openai_settings


def test_validate_openai_settings_accepts_none_as_empty_settings() -> None:
    assert validate_openai_settings(None) == {}


def test_validate_openai_settings_accepts_empty_dict() -> None:
    assert validate_openai_settings({}) == {}


@pytest.mark.parametrize('setting_payload', [[], '', 0, False])
def test_validate_openai_settings_rejects_falsy_non_dict_values(setting_payload) -> None:
    with pytest.raises(AIProviderInvalidRequestError):
        validate_openai_settings(setting_payload)


def test_validate_openai_settings_accepts_valid_temperature() -> None:
    assert validate_openai_settings({'temperature': 0.7}) == {'temperature': 0.7}


@pytest.mark.parametrize('temperature', [-0.1, 2.1, True, '0.7'])
def test_validate_openai_settings_rejects_invalid_temperature(temperature) -> None:
    with pytest.raises(AIProviderInvalidRequestError):
        validate_openai_settings({'temperature': temperature})


def test_validate_openai_settings_accepts_valid_top_p() -> None:
    assert validate_openai_settings({'top_p': 1}) == {'top_p': 1}


@pytest.mark.parametrize('top_p', [-0.1, 1.1, False, '1'])
def test_validate_openai_settings_rejects_invalid_top_p(top_p) -> None:
    with pytest.raises(AIProviderInvalidRequestError):
        validate_openai_settings({'top_p': top_p})


def test_validate_openai_settings_accepts_max_tokens() -> None:
    assert validate_openai_settings({'max_tokens': 100}) == {'max_tokens': 100}


def test_validate_openai_settings_accepts_max_completion_tokens() -> None:
    assert validate_openai_settings({'max_completion_tokens': 100}) == {'max_completion_tokens': 100}


def test_validate_openai_settings_rejects_both_token_limits() -> None:
    with pytest.raises(AIProviderInvalidRequestError) as exc_info:
        validate_openai_settings({'max_tokens': 100, 'max_completion_tokens': 100})

    assert '100' not in str(exc_info.value)


def test_validate_openai_settings_rejects_bool_as_integer() -> None:
    with pytest.raises(AIProviderInvalidRequestError):
        validate_openai_settings({'max_tokens': True})


def test_validate_openai_settings_accepts_positive_timeout() -> None:
    assert validate_openai_settings({'timeout': 30}) == {'timeout': 30}


@pytest.mark.parametrize('timeout', [-1, 0, 121, False, '30'])
def test_validate_openai_settings_rejects_invalid_timeout(timeout) -> None:
    with pytest.raises(AIProviderInvalidRequestError):
        validate_openai_settings({'timeout': timeout})


@pytest.mark.parametrize(
    'setting_payload',
    [
        {'api_key': 'sk-secret'},
        {'Authorization': 'Bearer secret'},
        {'metadata': {'secret': 'nested-secret'}},
    ],
)
def test_validate_openai_settings_rejects_sensitive_keys_without_values(setting_payload) -> None:
    with pytest.raises(AIProviderInvalidRequestError) as exc_info:
        validate_openai_settings(setting_payload)

    message = str(exc_info.value)
    assert 'sk-secret' not in message
    assert 'Bearer secret' not in message
    assert 'nested-secret' not in message


def test_validate_openai_settings_rejects_unknown_keys_without_values() -> None:
    with pytest.raises(AIProviderInvalidRequestError) as exc_info:
        validate_openai_settings({'unknown': 'sensitive-value'})

    assert 'sensitive-value' not in str(exc_info.value)


def test_validate_openai_settings_returns_normalized_copy_without_mutating_input() -> None:
    settings = {'temperature': 0.2, 'max_tokens': None, 'top_p': 0.9}

    result = validate_openai_settings(settings)

    assert result == {'temperature': 0.2, 'top_p': 0.9}
    assert settings == {'temperature': 0.2, 'max_tokens': None, 'top_p': 0.9}
