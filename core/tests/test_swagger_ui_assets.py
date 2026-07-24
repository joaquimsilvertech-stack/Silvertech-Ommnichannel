"""Garantias de que o Swagger UI é servido localmente sob CSP estrita.

Estes testes falhariam antes do micro-fix que troca o CDN externo
(cdn.jsdelivr.net) pelos assets locais do drf-spectacular-sidecar, servidos a
partir do próprio domínio ('self'). A CSP estrita (default-src 'none') deve
permanecer intacta.
"""
from __future__ import annotations

import pytest
from django.contrib.staticfiles import finders
from rest_framework import status
from rest_framework.test import APIClient


@pytest.mark.django_db
def test_swagger_ui_has_no_external_cdn() -> None:
    """O HTML do Swagger UI não referencia nenhum CDN externo."""
    client = APIClient()

    response = client.get('/api/schema/swagger-ui/')
    body = response.content.decode('utf-8')

    assert response.status_code == status.HTTP_200_OK
    assert 'cdn.jsdelivr.net' not in body
    assert 'unpkg.com' not in body
    assert '//cdn.' not in body


@pytest.mark.django_db
def test_swagger_ui_references_local_static_assets() -> None:
    """Os assets do Swagger UI são carregados sob STATIC_URL (/static/)."""
    client = APIClient()

    response = client.get('/api/schema/swagger-ui/')
    body = response.content.decode('utf-8')

    assert response.status_code == status.HTTP_200_OK
    assert '/static/' in body
    assert 'swagger-ui' in body


def _csp_directive(csp: str, name: str) -> str:
    """Extrai o valor de uma diretiva específica do header CSP."""
    for chunk in csp.split(';'):
        chunk = chunk.strip()
        if chunk == name or chunk.startswith(name + ' '):
            return chunk[len(name):].strip()
    return ''


@pytest.mark.django_db
def test_csp_header_remains_strict() -> None:
    """A CSP continua estrita: default-src 'none' e nenhum domínio externo em scripts/styles."""
    client = APIClient()

    response = client.get('/api/schema/swagger-ui/')
    csp = response['Content-Security-Policy']

    assert response.status_code == status.HTTP_200_OK
    assert "default-src 'none'" in csp
    # Nenhum CDN/domínio externo especificamente em script-src e style-src.
    for directive in ('script-src', 'style-src'):
        value = _csp_directive(csp, directive)
        for forbidden in ('cdn.jsdelivr.net', 'unpkg.com', '//cdn.', 'http://', 'https://'):
            assert forbidden not in value, f'{directive} não pode conter {forbidden}: {value!r}'


def test_sidecar_static_assets_actually_resolve() -> None:
    """O JS/CSS do sidecar é encontrado pelos finders — não é 404 local.

    Prova que não trocamos um 404 remoto (CDN) por um 404 local.
    """
    expected = (
        'drf_spectacular_sidecar/swagger-ui-dist/swagger-ui-bundle.js',
        'drf_spectacular_sidecar/swagger-ui-dist/swagger-ui.css',
    )
    for asset in expected:
        assert finders.find(asset) is not None, f'asset não encontrado pelo finder: {asset}'
