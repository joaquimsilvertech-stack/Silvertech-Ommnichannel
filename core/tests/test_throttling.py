from __future__ import annotations

import pytest
from django.core.cache import cache
from rest_framework import status
from rest_framework.test import APIClient


@pytest.mark.django_db
def test_auth_token_endpoint_is_throttled() -> None:
    cache.clear()
    client = APIClient()

    response = None
    for _ in range(6):
        response = client.post(
            '/api/auth/token/',
            {
                'email': 'missing@example.com',
                'password': 'wrong-password',
            },
            format='json',
            REMOTE_ADDR='198.51.100.10',
        )

    assert response is not None
    assert response.status_code == status.HTTP_429_TOO_MANY_REQUESTS


@pytest.mark.django_db
def test_auth_refresh_endpoint_is_throttled() -> None:
    cache.clear()
    client = APIClient()

    response = None
    for _ in range(6):
        response = client.post(
            '/api/auth/token/refresh/',
            {'refresh': 'invalid-refresh-token'},
            format='json',
            REMOTE_ADDR='198.51.100.11',
        )

    assert response is not None
    assert response.status_code == status.HTTP_429_TOO_MANY_REQUESTS


@pytest.mark.django_db
def test_webhook_endpoint_is_throttled() -> None:
    cache.clear()
    client = APIClient()
    payload = {
        'event': 'messages.upsert',
        'instance': 'silvertech_whatsapp',
        'data': {},
    }

    response = None
    for _ in range(121):
        response = client.post(
            '/api/omnichannel/webhooks/whatsapp/',
            payload,
            format='json',
            REMOTE_ADDR='198.51.100.12',
        )

    assert response is not None
    assert response.status_code == status.HTTP_429_TOO_MANY_REQUESTS
