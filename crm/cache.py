from __future__ import annotations

import logging
from uuid import UUID

from django.core.cache import cache

DASHBOARD_METRICS_CACHE_TIMEOUT = 60 * 15
logger = logging.getLogger(__name__)


def get_dashboard_metrics_cache_key(workspace_id: str | UUID) -> str:
    """Chave de cache isolada por tenant/workspace."""
    return f'dashboard_metrics_{workspace_id}'


def invalidate_dashboard_metrics_cache(workspace_id: str | UUID | None) -> None:
    """Remove metricas cacheadas de um workspace."""
    if workspace_id is None:
        return
    try:
        cache.delete(get_dashboard_metrics_cache_key(workspace_id))
    except Exception as exc:
        logger.warning(
            'Falha ao invalidar cache de dashboard (workspace_id=%s): %s',
            workspace_id,
            exc,
            exc_info=True,
        )
