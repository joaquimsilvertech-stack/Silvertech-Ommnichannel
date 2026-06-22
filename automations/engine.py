"""
Motor de execucao dos flows de automacao.
"""
from __future__ import annotations

import logging
from typing import Any

from omnichannel.models import Conversation

from .models import Flow

logger = logging.getLogger(__name__)


class FlowEngine:
    """Executa flows a partir dos nos JSON configurados no workspace."""

    DELAY_NODE_TYPES = {'wait_delay', 'delay'}

    def execute_flow(
        self,
        flow_id: str,
        conversation_id: str,
        current_node_id: str | None = None,
    ) -> None:
        """Executa um flow para uma conversa, a partir do no informado."""
        try:
            flow = Flow.objects.select_related('workspace').get(id=flow_id)
        except Flow.DoesNotExist:
            logger.warning('Flow nao encontrado para execucao (flow_id=%s)', flow_id)
            return

        try:
            conversation = Conversation.objects.select_related('workspace', 'contact').get(
                id=conversation_id,
            )
        except Conversation.DoesNotExist:
            logger.warning(
                'Conversa nao encontrada para execucao de flow (conversation_id=%s)',
                conversation_id,
            )
            return

        if flow.workspace_id != conversation.workspace_id:
            logger.warning(
                'Execucao de flow abortada por divergencia de workspace '
                '(flow_id=%s, flow_workspace=%s, conversation_id=%s, conversation_workspace=%s)',
                flow.id,
                flow.workspace_id,
                conversation.id,
                conversation.workspace_id,
            )
            return

        if conversation.is_human_handoff:
            logger.info(
                'Execucao de flow abortada: conversa em handoff humano '
                '(flow_id=%s, conversation_id=%s)',
                flow.id,
                conversation.id,
            )
            return

        node = self._get_start_node(flow.nodes) if current_node_id is None else self._find_node(
            flow.nodes,
            current_node_id,
        )

        if node is None:
            logger.info(
                'Nenhum node encontrado para execucao (flow_id=%s, current_node_id=%s)',
                flow.id,
                current_node_id,
            )
            return

        while node is not None:
            self._execute_node(node, conversation)

            next_node_id = node.get('next_node_id')
            if not next_node_id:
                logger.info('Flow finalizado (flow_id=%s, conversation_id=%s)', flow.id, conversation.id)
                return

            next_node = self._find_node(flow.nodes, str(next_node_id))
            if next_node is None:
                logger.warning(
                    'Proximo node nao encontrado (flow_id=%s, next_node_id=%s)',
                    flow.id,
                    next_node_id,
                )
                return

            if self._is_delay_node(next_node):
                logger.info(
                    'Execucao pausada antes de node de delay '
                    '(flow_id=%s, conversation_id=%s, next_node_id=%s)',
                    flow.id,
                    conversation.id,
                    next_node_id,
                )
                return

            node = next_node

    def _execute_node(self, node: dict[str, Any], conversation: Conversation) -> None:
        """Despacha a execucao do node atual."""
        node_type = node.get('type')
        logger.info(
            'Executando node de flow (node_id=%s, type=%s, conversation_id=%s)',
            node.get('id'),
            node_type,
            conversation.id,
        )
        pass

    def _get_start_node(self, nodes: Any) -> dict[str, Any] | None:
        """Retorna o primeiro node da lista configurada."""
        if not isinstance(nodes, list) or not nodes:
            return None
        first_node = nodes[0]
        return first_node if isinstance(first_node, dict) else None

    def _find_node(self, nodes: Any, node_id: str) -> dict[str, Any] | None:
        """Busca um node pelo campo id."""
        if not isinstance(nodes, list):
            return None

        for node in nodes:
            if isinstance(node, dict) and str(node.get('id')) == str(node_id):
                return node
        return None

    def _is_delay_node(self, node: dict[str, Any]) -> bool:
        """Indica se o node deve pausar a execucao imediata."""
        return str(node.get('type')) in self.DELAY_NODE_TYPES
