from __future__ import annotations

import logging
from typing import Any

from django.db.models.signals import post_save
from django.dispatch import receiver

from omnichannel.models import Message

from .models import Flow
from .tasks import execute_flow_task

logger = logging.getLogger(__name__)


@receiver(post_save, sender=Message)
def trigger_flow_on_new_message(
    sender: type[Message],
    instance: Message,
    created: bool,
    **kwargs: Any,
) -> None:
    """Dispara flows ativos quando uma nova mensagem inbound e criada."""
    if not created:
        return

    if instance.direction != Message.Direction.INBOUND:
        return

    conversation = instance.conversation
    if conversation.is_human_handoff:
        logger.info(
            'Signal de flow ignorado: conversa em handoff humano '
            '(conversation_id=%s, message_id=%s)',
            conversation.id,
            instance.id,
        )
        return

    flows = list(Flow.objects.filter(
        workspace=conversation.workspace,
        is_active=True,
        trigger__type='new_message',
    ))

    logger.info(
        'Signal de nova mensagem inbound detectado '
        '(message_id=%s, conversation_id=%s, workspace_id=%s, flows=%s)',
        instance.id,
        conversation.id,
        conversation.workspace_id,
        len(flows),
    )

    for flow in flows:
        execute_flow_task.delay(str(flow.id), str(conversation.id))
        logger.info(
            'Flow enviado para Celery via signal '
            '(flow_id=%s, conversation_id=%s, message_id=%s)',
            flow.id,
            conversation.id,
            instance.id,
        )
