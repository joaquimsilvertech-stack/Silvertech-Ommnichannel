from __future__ import annotations

import logging
from collections.abc import Callable
from queue import Empty, Queue
from threading import Thread

import redis
from django.conf import settings
from django.db import connection
from django.http import JsonResponse
from django.views.decorators.http import require_GET

from silvertech.celery import app as celery_app

logger = logging.getLogger(__name__)
HEALTHCHECK_TIMEOUT_SECONDS = 2


def _check_database() -> str:
    """Executa uma query minima no PostgreSQL."""
    with connection.cursor() as cursor:
        cursor.execute('SELECT 1')
        cursor.fetchone()
    return 'ok'


def _check_redis() -> str:
    """Valida conectividade com Redis usado por Celery/SSE."""
    redis_client = redis.from_url(
        settings.CELERY_BROKER_URL,
        socket_connect_timeout=1,
        socket_timeout=1,
    )
    redis_client.ping()
    return 'ok'


def _check_celery() -> str:
    """Verifica se ha pelo menos um worker Celery respondendo."""
    inspector = celery_app.control.inspect(timeout=1)
    response = inspector.ping()
    if not response:
        raise RuntimeError('Nenhum worker Celery respondeu ao ping.')
    return 'ok'


def _run_check(service_name: str, check: Callable[[], str]) -> str:
    """Executa um check com timeout duro para nao travar o endpoint."""
    result_queue = Queue(maxsize=1)

    def runner() -> None:
        try:
            result_queue.put(('ok', check()))
        except Exception as exc:
            result_queue.put(('error', exc))

    thread = Thread(target=runner, daemon=True)
    thread.start()

    try:
        status, result = result_queue.get(timeout=HEALTHCHECK_TIMEOUT_SECONDS)
    except Empty:
        logger.error('Healthcheck excedeu timeout para %s', service_name)
        return 'down'

    if status == 'error':
        logger.error(
            'Healthcheck falhou para %s: %s',
            service_name,
            result,
            exc_info=(type(result), result, result.__traceback__),
        )
        return 'down'

    return result


@require_GET
def health_check(request) -> JsonResponse:
    """Endpoint publico de diagnostico dos servicos essenciais."""
    services = {
        'database': 'down',
        'redis': 'down',
        'celery': 'down',
    }

    checks = {
        'database': _check_database,
        'redis': _check_redis,
        'celery': _check_celery,
    }

    for service_name, check in checks.items():
        services[service_name] = _run_check(service_name, check)

    is_healthy = all(status == 'ok' for status in services.values())
    http_status = 200 if is_healthy else 503

    return JsonResponse(
        {
            'status': 'healthy' if is_healthy else 'unhealthy',
            'services': services,
        },
        status=http_status,
    )
