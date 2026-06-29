"""
Tickets de atendimento e transbordo humano.
"""
from __future__ import annotations

from django.conf import settings
from django.db import models

from core.models import BaseModel


class Ticket(BaseModel):
    """Solicitacao de atendimento humano associada a contato/conversa."""

    class Status(models.TextChoices):
        OPEN = 'open', 'Aberto'
        IN_PROGRESS = 'in_progress', 'Em andamento'
        RESOLVED = 'resolved', 'Resolvido'
        CLOSED = 'closed', 'Fechado'

    workspace = models.ForeignKey(
        'workspaces.Workspace',
        on_delete=models.CASCADE,
        related_name='tickets',
        db_index=True,
    )
    contact = models.ForeignKey(
        'crm.Contact',
        on_delete=models.CASCADE,
        related_name='tickets',
        db_index=True,
    )
    conversation = models.ForeignKey(
        'omnichannel.Conversation',
        on_delete=models.SET_NULL,
        related_name='tickets',
        null=True,
        blank=True,
        db_index=True,
    )
    title = models.CharField(max_length=255)
    status = models.CharField(
        max_length=32,
        choices=Status.choices,
        default=Status.OPEN,
        db_index=True,
    )
    assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name='tickets_assigned',
        null=True,
        blank=True,
        db_index=True,
    )
    due_at = models.DateTimeField(null=True, blank=True, db_index=True)

    class Meta:
        ordering = ('-created_at',)
        verbose_name = 'ticket'
        verbose_name_plural = 'tickets'
        indexes = [
            models.Index(fields=['workspace', 'status']),
            models.Index(fields=['workspace', 'due_at']),
            models.Index(fields=['assigned_to', 'status']),
        ]

    def __str__(self) -> str:
        return f'{self.title} ({self.status})'
