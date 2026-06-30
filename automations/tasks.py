from __future__ import annotations

import logging

from celery import shared_task

from .engine import FlowEngine

logger = logging.getLogger(__name__)


@shared_task(name='automations.execute_flow')
def execute_flow_task(
    flow_id: str,
    conversation_id: str,
    current_node_id: str | None = None,
) -> None:
    """Executa um flow em background via Celery."""
    logger.info(
        'Iniciando task execute_flow (flow_id=%s, conversation_id=%s, current_node_id=%s)',
        flow_id,
        conversation_id,
        current_node_id,
    )

    FlowEngine().execute_flow(
        flow_id=flow_id,
        conversation_id=conversation_id,
        current_node_id=current_node_id,
    )

    logger.info(
        'Finalizando task execute_flow (flow_id=%s, conversation_id=%s, current_node_id=%s)',
        flow_id,
        conversation_id,
        current_node_id,
    )
