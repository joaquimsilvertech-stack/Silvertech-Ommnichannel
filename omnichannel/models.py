"""
Conversas omnichannel por workspace e contato (Card #021).
"""
import uuid  # noqa: F401

from django.db import models

from core.models import BaseModel


class Conversation(BaseModel):
    """Thread de atendimento em um canal (ex.: WhatsApp) ligada a um contato."""

    class Status(models.TextChoices):
        OPEN = 'open', 'Aberta'
        CLOSED = 'closed', 'Fechada'
        PENDING = 'pending', 'Pendente'

    workspace = models.ForeignKey(
        'workspaces.Workspace',
        on_delete=models.CASCADE,
        related_name='conversations',
        db_index=True,
    )
    contact = models.ForeignKey(
        'crm.Contact',
        on_delete=models.CASCADE,
        related_name='conversations',
        db_index=True,
    )
    channel = models.CharField(max_length=64, db_index=True)
    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.OPEN,
        db_index=True,
    )
    is_human_handoff = models.BooleanField(default=False, db_index=True)

    class Meta:
        ordering = ('-created_at',)
        verbose_name = 'conversa'
        verbose_name_plural = 'conversas'
        indexes = [
            models.Index(fields=['workspace', 'status']),
            models.Index(fields=['contact', 'channel']),
        ]

    def __str__(self) -> str:
        return f'{self.channel} — {self.contact.name} ({self.status})'


class Message(BaseModel):
    """Mensagem individual dentro de uma conversa."""

    class Direction(models.TextChoices):
        INBOUND = 'inbound', 'Entrada'
        OUTBOUND = 'outbound', 'Saída'

    class Status(models.TextChoices):
        SENT = 'sent', 'Enviada'
        DELIVERED = 'delivered', 'Entregue'
        READ = 'read', 'Lida'
        FAILED = 'failed', 'Falhou'

    conversation = models.ForeignKey(
        Conversation,
        on_delete=models.CASCADE,
        related_name='messages',
        db_index=True,
    )
    body = models.TextField()
    direction = models.CharField(
        max_length=16,
        choices=Direction.choices,
        db_index=True,
    )
    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        null=True,
        blank=True,
        db_index=True,
    )
    external_id = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        db_index=True,
        help_text='ID da mensagem no provedor (ex.: wamid da Meta).',
    )

    class Meta:
        ordering = ('-created_at',)
        verbose_name = 'mensagem'
        verbose_name_plural = 'mensagens'
        indexes = [
            models.Index(fields=['conversation', 'created_at']),
        ]

    def __str__(self) -> str:
        return f'{self.direction} @ {self.conversation_id}'
