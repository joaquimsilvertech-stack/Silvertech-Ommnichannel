from __future__ import annotations

import os
import subprocess
import sys

import pytest
from django.conf import settings
from django.db import connection

from core.sanitization import sanitize_sensitive_data, sentry_before_send
from workspaces.factories import WorkspaceFactory
from workspaces.models import WorkspaceAIConfig

TEST_FIELD_ENCRYPTION_KEY = '7EbNIqb9tM4Y-Q_XuIrkum0iErg9vNNtf5aeSZgAUPs='


def _settings_env(**overrides: str) -> dict[str, str]:
    env = {
        key: value
        for key, value in os.environ.items()
        if key not in {'SECRET_KEY', 'FIELD_ENCRYPTION_KEY'}
    }
    env.update(
        {
            'READ_DOT_ENV_FILE': 'false',
            'DJANGO_ENV': 'test',
            'ALLOWED_HOSTS': 'localhost,127.0.0.1,testserver',
            'POSTGRES_DB': 'silvertech',
            'POSTGRES_USER': 'postgres',
            'POSTGRES_PASSWORD': 'test-db-password',
            'POSTGRES_HOST': 'localhost',
            'POSTGRES_PORT': '5432',
            'REDIS_HOST': '127.0.0.1',
            'REDIS_PORT': '6379',
            'REDIS_DB': '0',
            'REDIS_CACHE_URL': 'redis://127.0.0.1:6379/0',
            'CELERY_BROKER_URL': 'redis://127.0.0.1:6379/0',
            'CELERY_RESULT_BACKEND': 'redis://127.0.0.1:6379/0',
            'EVOLUTION_API_URL': 'http://localhost:8080',
            'EVOLUTION_API_KEY': 'test-evolution-key',
            'EVOLUTION_INSTANCE_NAME': 'silvertech_whatsapp',
            'SECRET_KEY': 'test-secret-key-not-for-production',
            'FIELD_ENCRYPTION_KEY': TEST_FIELD_ENCRYPTION_KEY,
        },
    )
    env.update(overrides)
    return env


def _run_settings_import(env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, '-c', 'import silvertech.settings'],
        env=env,
        cwd=os.getcwd(),
        capture_output=True,
        text=True,
        check=False,
    )


def test_missing_secret_key_fails_fast() -> None:
    env = _settings_env()
    env.pop('SECRET_KEY')

    result = _run_settings_import(env)

    assert result.returncode != 0
    assert 'A variavel de ambiente SECRET_KEY e obrigatoria.' in result.stderr
    assert TEST_FIELD_ENCRYPTION_KEY not in result.stderr


def test_missing_field_encryption_key_fails_fast() -> None:
    env = _settings_env()
    env.pop('FIELD_ENCRYPTION_KEY')

    result = _run_settings_import(env)

    assert result.returncode != 0
    assert 'A variavel de ambiente FIELD_ENCRYPTION_KEY e obrigatoria.' in result.stderr


def test_debug_is_false_by_default() -> None:
    env = _settings_env()
    env.pop('DEBUG', None)
    result = subprocess.run(
        [sys.executable, '-c', 'from django.conf import settings; print(settings.DEBUG)'],
        env={**env, 'DJANGO_SETTINGS_MODULE': 'silvertech.settings'},
        cwd=os.getcwd(),
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    assert result.stdout.strip() == 'False'


def test_allowed_hosts_wildcard_is_rejected_in_production() -> None:
    result = _run_settings_import(
        _settings_env(DJANGO_ENV='production', ALLOWED_HOSTS='*'),
    )

    assert result.returncode != 0
    assert 'ALLOWED_HOSTS deve ser configurado sem wildcard em producao.' in result.stderr


def test_cors_cannot_be_open_in_production() -> None:
    result = _run_settings_import(
        _settings_env(
            DJANGO_ENV='production',
            ALLOWED_HOSTS='api.example.com',
            CORS_ALLOW_ALL_ORIGINS='True',
        ),
    )

    assert result.returncode != 0
    assert 'CORS_ALLOW_ALL_ORIGINS nao pode ser True em producao.' in result.stderr


def test_production_security_flags_are_enabled() -> None:
    env = _settings_env(DJANGO_ENV='production', ALLOWED_HOSTS='api.example.com')
    result = subprocess.run(
        [
            sys.executable,
            '-c',
            (
                'from django.conf import settings; '
                'print(settings.SESSION_COOKIE_SECURE, settings.CSRF_COOKIE_SECURE, '
                'settings.SECURE_SSL_REDIRECT, settings.SECURE_HSTS_SECONDS)'
            ),
        ],
        env={**env, 'DJANGO_SETTINGS_MODULE': 'silvertech.settings'},
        cwd=os.getcwd(),
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    assert result.stdout.strip() == 'True True True 31536000'


def test_ssl_redirect_is_disabled_for_tests() -> None:
    assert settings.SECURE_SSL_REDIRECT is False
    assert settings.SESSION_COOKIE_SECURE is False
    assert settings.CSRF_COOKIE_SECURE is False


def test_sensitive_values_are_sanitized() -> None:
    payload = {
        'headers': {
            'Authorization': 'Bearer secret-token',
            'X-Request-ID': 'request-id',
        },
        'data': {
            'openai_api_key': 'sk-test-secret',
            'nested': {'api_key': 'provider-key'},
        },
    }

    sanitized = sanitize_sensitive_data(payload)

    assert sanitized['headers']['Authorization'] == '***'
    assert sanitized['headers']['X-Request-ID'] == 'request-id'
    assert sanitized['data']['openai_api_key'] == '***'
    assert sanitized['data']['nested']['api_key'] == '***'


def test_sentry_before_send_sanitizes_event() -> None:
    event = {
        'request': {
            'headers': {'Authorization': 'Bearer token'},
            'data': {'FIELD_ENCRYPTION_KEY': TEST_FIELD_ENCRYPTION_KEY},
        },
    }

    sanitized = sentry_before_send(event, {})

    assert sanitized['request']['headers']['Authorization'] == '***'
    assert sanitized['request']['data']['FIELD_ENCRYPTION_KEY'] == '***'
    assert TEST_FIELD_ENCRYPTION_KEY not in str(sanitized)


@pytest.mark.django_db
def test_workspace_ai_config_keeps_api_key_encrypted_at_rest() -> None:
    workspace = WorkspaceFactory()
    config = WorkspaceAIConfig.objects.create(
        workspace=workspace,
        is_active=True,
        openai_api_key='sk-test-workspace-key',
    )

    config.refresh_from_db()
    assert config.openai_api_key == 'sk-test-workspace-key'

    with connection.cursor() as cursor:
        cursor.execute(
            'SELECT openai_api_key FROM workspaces_workspaceaiconfig WHERE id = %s',
            [str(config.id)],
        )
        raw_value = cursor.fetchone()[0]

    assert raw_value != 'sk-test-workspace-key'
    assert 'sk-test-workspace-key' not in raw_value
