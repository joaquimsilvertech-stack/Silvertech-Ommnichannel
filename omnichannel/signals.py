from django.db.models.signals import post_save
from django.dispatch import receiver
from django_eventstream import send_event

from .models import Conversation, Message
from .serializers import MessageSerializer


@receiver(post_save, sender=Message)
def broadcast_message_event(sender, instance: Message, created: bool, **kwargs) -> None:
    """Publica mensagem ou atualização de status no canal SSE do workspace."""
    update_fields = kwargs.get('update_fields')
    if not created:
        if update_fields is None or 'status' not in update_fields:
            return
        event_type = 'message_status'
    else:
        event_type = 'message'

    workspace_id = (
        Conversation.objects.filter(pk=instance.conversation_id)
        .values_list('workspace_id', flat=True)
        .first()
    )
    if workspace_id is None:
        return

    payload = MessageSerializer(instance).data
    send_event(f'workspace-{workspace_id}', event_type, payload)
