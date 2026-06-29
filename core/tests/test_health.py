from __future__ import annotations

from unittest.mock import patch

import pytest


@pytest.mark.django_db
@patch('core.views._check_celery', return_value='ok')
@patch('core.views._check_redis', return_value='ok')
@patch('core.views._check_database', return_value='ok')
def test_health_check_all_healthy(
    mock_database,
    mock_redis,
    mock_celery,
    client,
) -> None:
    response = client.get('/api/health/')

    assert response.status_code == 200
    assert response.json() == {
        'status': 'healthy',
        'services': {
            'database': 'ok',
            'redis': 'ok',
            'celery': 'ok',
        },
    }


@pytest.mark.django_db
@patch('core.views._check_celery', return_value='ok')
@patch('core.views._check_redis', return_value='ok')
@patch('core.views._check_database', return_value='down')
def test_health_check_database_down(
    mock_database,
    mock_redis,
    mock_celery,
    client,
) -> None:
    response = client.get('/api/health/')
    payload = response.json()

    assert response.status_code == 503
    assert payload['status'] == 'unhealthy'
    assert payload['services']['database'] == 'down'
    assert payload['services']['redis'] == 'ok'
    assert payload['services']['celery'] == 'ok'


@pytest.mark.django_db
@patch('core.views._check_celery', return_value='ok')
@patch('core.views._check_redis', return_value='down')
@patch('core.views._check_database', return_value='ok')
def test_health_check_redis_down(
    mock_database,
    mock_redis,
    mock_celery,
    client,
) -> None:
    response = client.get('/api/health/')
    payload = response.json()

    assert response.status_code == 503
    assert payload['status'] == 'unhealthy'
    assert payload['services']['database'] == 'ok'
    assert payload['services']['redis'] == 'down'
    assert payload['services']['celery'] == 'ok'


@pytest.mark.django_db
@patch('core.views._check_celery', return_value='down')
@patch('core.views._check_redis', return_value='ok')
@patch('core.views._check_database', return_value='ok')
def test_health_check_celery_down(
    mock_database,
    mock_redis,
    mock_celery,
    client,
) -> None:
    response = client.get('/api/health/')
    payload = response.json()

    assert response.status_code == 503
    assert payload['status'] == 'unhealthy'
    assert payload['services']['database'] == 'ok'
    assert payload['services']['redis'] == 'ok'
    assert payload['services']['celery'] == 'down'
