from django.db.models.signals import post_save
from django.dispatch import receiver
from django_eventstream import send_event

from .models import Conversation, Message
from .serializers import MessageSerializer


@receiver(post_save, sender=Message)
def broadcast_message_event(sender, instance: Message, created: bool, **kwargs) -> None:
    """Publica nova mensagem no canal SSE do workspace (Card #024)."""
    if not created:
        return

    workspace_id = (
        Conversation.objects.filter(pk=instance.conversation_id)
        .values_list('workspace_id', flat=True)
        .first()
    )
    if workspace_id is None:
        return

    payload = MessageSerializer(instance).data
    send_event(f'workspace-{workspace_id}', 'message', payload)
