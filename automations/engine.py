"""
Motor de execucao dos flows de automacao.
"""
from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

import requests
from django.utils import timezone

from omnichannel.models import Conversation
from omnichannel.services import send_whatsapp_message

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
            should_continue = self._execute_node(flow, node, conversation)
            if not should_continue:
                return

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

            node = next_node

    def _execute_node(
        self,
        flow: Flow,
        node: dict[str, Any],
        conversation: Conversation,
    ) -> bool:
        """Despacha a execucao do node atual."""
        node_type = node.get('type')
        logger.info(
            'Executando node de flow (node_id=%s, type=%s, conversation_id=%s)',
            node.get('id'),
            node_type,
            conversation.id,
        )

        config = node.get('config', {})
        if not isinstance(config, dict):
            logger.warning(
                'Config de node invalida; esperado objeto JSON '
                '(flow_id=%s, node_id=%s, type=%s)',
                flow.id,
                node.get('id'),
                node_type,
            )
            config = {}

        if node_type == 'send_whatsapp':
            return self._execute_send_whatsapp_node(flow, node, conversation, config)

        if self._is_delay_node(node):
            self._schedule_wait_delay_node(flow, node, conversation, config)
            return False

        logger.info(
            'Tipo de node ainda sem implementacao real (flow_id=%s, node_id=%s, type=%s)',
            flow.id,
            node.get('id'),
            node_type,
        )
        return True

    def _execute_send_whatsapp_node(
        self,
        flow: Flow,
        node: dict[str, Any],
        conversation: Conversation,
        config: dict[str, Any],
    ) -> bool:
        """Envia uma mensagem WhatsApp via Evolution API."""
        text = config.get('text')
        if not text or not isinstance(text, str):
            logger.warning(
                'Node send_whatsapp sem texto valido (flow_id=%s, node_id=%s)',
                flow.id,
                node.get('id'),
            )
            return True

        phone = conversation.contact.phone
        if not phone:
            logger.warning(
                'Node send_whatsapp ignorado: contato sem telefone '
                '(flow_id=%s, node_id=%s, conversation_id=%s)',
                flow.id,
                node.get('id'),
                conversation.id,
            )
            return True

        try:
            send_whatsapp_message(phone=phone, text=text)
        except requests.exceptions.RequestException as exc:
            logger.error(
                'Falha ao enviar WhatsApp por flow '
                '(flow_id=%s, node_id=%s, conversation_id=%s): %s',
                flow.id,
                node.get('id'),
                conversation.id,
                exc,
                exc_info=True,
            )
            return True

        logger.info(
            'Mensagem WhatsApp enviada por flow (flow_id=%s, node_id=%s, conversation_id=%s)',
            flow.id,
            node.get('id'),
            conversation.id,
        )
        return True

    def _schedule_wait_delay_node(
        self,
        flow: Flow,
        node: dict[str, Any],
        conversation: Conversation,
        config: dict[str, Any],
    ) -> None:
        """Agenda a continuacao do flow apos um intervalo."""
        raw_seconds = config.get('seconds', 0)
        try:
            seconds = max(0, int(raw_seconds))
        except (TypeError, ValueError):
            logger.warning(
                'Node wait_delay com seconds invalido; usando 0 '
                '(flow_id=%s, node_id=%s, seconds=%s)',
                flow.id,
                node.get('id'),
                raw_seconds,
            )
            seconds = 0

        next_node_id = node.get('next_node_id')
        if not next_node_id:
            logger.info(
                'Node wait_delay sem proximo node; flow encerrado '
                '(flow_id=%s, node_id=%s, conversation_id=%s)',
                flow.id,
                node.get('id'),
                conversation.id,
            )
            return

        from automations.tasks import execute_flow_task

        future_datetime = timezone.now() + timedelta(seconds=seconds)
        execute_flow_task.apply_async(
            args=[str(flow.id), str(conversation.id), str(next_node_id)],
            eta=future_datetime,
        )
        logger.info(
            'Flow agendado por wait_delay '
            '(flow_id=%s, node_id=%s, conversation_id=%s, next_node_id=%s, eta=%s)',
            flow.id,
            node.get('id'),
            conversation.id,
            next_node_id,
            future_datetime.isoformat(),
        )

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
