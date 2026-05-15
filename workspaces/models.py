"""
Multi-tenant B2B: workspaces isolam dados; Member amarra usuário + papel no tenant.
"""
import uuid  # noqa: F401

from django.conf import settings
from django.db import models

from core.models import BaseModel


class Workspace(BaseModel):
    """Tenant lógico (organização / conta SaaS)."""

    name = models.CharField(max_length=255, db_index=True)
    slug = models.SlugField(max_length=128, unique=True, db_index=True)
    users = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        through='Member',
        related_name='workspaces',
    )

    class Meta:
        ordering = ('name',)
        verbose_name = 'workspace'
        verbose_name_plural = 'workspaces'

    def __str__(self) -> str:
        return self.name


class Member(BaseModel):
    """Associação usuário ↔ workspace com papel operacional no tenant."""

    class Role(models.TextChoices):
        OWNER = 'owner', 'Owner'
        ADMIN = 'admin', 'Admin'
        AGENT = 'agent', 'Agent'

    workspace = models.ForeignKey(
        Workspace,
        on_delete=models.CASCADE,
        related_name='memberships',
        db_index=True,
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='memberships',
        db_index=True,
    )
    role = models.CharField(
        max_length=16,
        choices=Role.choices,
        default=Role.AGENT,
        db_index=True,
    )

    class Meta:
        ordering = ('workspace', 'user')
        indexes = [
            models.Index(fields=['workspace', 'user']),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=('workspace', 'user'),
                name='workspaces_member_unique_workspace_user',
            ),
        ]

    def __str__(self) -> str:
        return f'{self.user_id} @ {self.workspace_id} ({self.role})'


class WorkspaceInvite(BaseModel):
    """Convite pendente para ingressar em um workspace (Card #008)."""

    class Role(models.TextChoices):
        ADMIN = 'admin', 'Admin'
        AGENT = 'agent', 'Agent'

    email = models.EmailField(db_index=True)
    workspace = models.ForeignKey(
        Workspace,
        on_delete=models.CASCADE,
        related_name='invites',
        db_index=True,
    )
    invited_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='workspace_invites_sent',
    )
    role = models.CharField(
        max_length=16,
        choices=Role.choices,
        default=Role.AGENT,
        db_index=True,
    )
    token = models.UUIDField(default=uuid.uuid4, unique=True, editable=False, db_index=True)
    accepted = models.BooleanField(default=False, db_index=True)
    expires_at = models.DateTimeField(db_index=True)

    class Meta:
        ordering = ('-created_at',)
        verbose_name = 'convite de workspace'
        verbose_name_plural = 'convites de workspace'
        indexes = [
            models.Index(fields=['workspace', 'email']),
        ]

    def __str__(self) -> str:
        return f'Convite {self.email} → {self.workspace.name}'
