"""
Fluxos de automacao configuraveis por workspace.
"""
from __future__ import annotations

from django.db import models

from core.models import BaseModel


class Flow(BaseModel):
    """Automacao acionada por gatilhos e composta por nos JSON."""

    workspace = models.ForeignKey(
        'workspaces.Workspace',
        on_delete=models.CASCADE,
        related_name='flows',
        db_index=True,
    )
    name = models.CharField(max_length=255)
    trigger = models.JSONField(default=dict, blank=True)
    nodes = models.JSONField(default=list, blank=True)
    is_active = models.BooleanField(default=True, db_index=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Flow'
        verbose_name_plural = 'Flows'
        indexes = [
            models.Index(fields=['workspace', 'is_active']),
        ]

    def __str__(self) -> str:
        return self.name
