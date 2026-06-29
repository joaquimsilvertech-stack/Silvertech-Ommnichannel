from __future__ import annotations

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
