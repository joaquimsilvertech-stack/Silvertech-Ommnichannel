from __future__ import annotations

import os

os.environ.setdefault('DJANGO_ENV', 'test')
os.environ.setdefault('DEBUG', 'False')
os.environ.setdefault('SECRET_KEY', 'test-secret-key-not-for-production')
os.environ.setdefault('FIELD_ENCRYPTION_KEY', '7EbNIqb9tM4Y-Q_XuIrkum0iErg9vNNtf5aeSZgAUPs=')
os.environ.setdefault('ALLOWED_HOSTS', 'localhost,127.0.0.1,testserver')
os.environ.setdefault('CORS_ALLOWED_ORIGINS', 'http://localhost:3000,http://127.0.0.1:3000')
os.environ.setdefault('CSRF_TRUSTED_ORIGINS', 'http://localhost:3000,http://127.0.0.1:3000')
os.environ.setdefault('POSTGRES_DB', 'silvertech')
os.environ.setdefault('POSTGRES_USER', 'postgres')
os.environ.setdefault('POSTGRES_PASSWORD', '1234')
os.environ.setdefault('POSTGRES_HOST', 'localhost')
os.environ.setdefault('POSTGRES_PORT', '5432')
os.environ.setdefault('REDIS_HOST', '127.0.0.1')
os.environ.setdefault('REDIS_PORT', '6379')
os.environ.setdefault('REDIS_DB', '0')
os.environ.setdefault('REDIS_CACHE_URL', 'redis://127.0.0.1:6379/0')
os.environ.setdefault('CELERY_BROKER_URL', 'redis://127.0.0.1:6379/0')
os.environ.setdefault('CELERY_RESULT_BACKEND', 'redis://127.0.0.1:6379/0')
os.environ.setdefault('EVOLUTION_API_URL', 'http://localhost:8080')
os.environ.setdefault('EVOLUTION_API_KEY', 'test-evolution-key')
os.environ.setdefault('EVOLUTION_INSTANCE_NAME', 'silvertech_whatsapp')
os.environ.setdefault('SENTRY_DSN', '')

import pytest
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import AccessToken

from workspaces.factories import MemberFactory, UserFactory, WorkspaceFactory
from workspaces.models import Member, Workspace


@pytest.fixture(autouse=True)
def use_locmem_cache(settings):
    """Evita dependencia de Redis nos testes unitarios."""
    settings.CACHES = {
        'default': {
            'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
            'LOCATION': 'test-cache',
        },
    }


@pytest.fixture
def db_setup(db):
    """Ativa o banco de teste para fixtures que persistem dados."""
    return None


@pytest.fixture
def tenant_workspace(db_setup) -> Workspace:
    """Workspace tenant padrao para testes multi-tenant."""
    return WorkspaceFactory()


@pytest.fixture
def auth_user(db_setup):
    """Usuario autenticado padrao para testes de API."""
    return UserFactory()


@pytest.fixture
def tenant_member(auth_user, tenant_workspace) -> Member:
    """Vincula o usuario autenticado ao workspace tenant."""
    return MemberFactory(user=auth_user, workspace=tenant_workspace)


@pytest.fixture
def api_client(auth_user, tenant_member) -> APIClient:
    """DRF APIClient autenticado com JWT para views protegidas."""
    client = APIClient()
    token = AccessToken.for_user(auth_user)
    client.credentials(HTTP_AUTHORIZATION=f'Bearer {token}')
    return client
