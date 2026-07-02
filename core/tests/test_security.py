from __future__ import annotations

import pytest
from rest_framework import status
from rest_framework.test import APIClient


@pytest.mark.django_db
def test_public_response_includes_security_headers() -> None:
    client = APIClient()

    response = client.get('/api/schema/swagger-ui/')

    assert response.status_code == status.HTTP_200_OK
    assert 'Content-Security-Policy' in response
    assert 'X-Content-Type-Options' in response
    assert response['X-Content-Type-Options'] == 'nosniff'
