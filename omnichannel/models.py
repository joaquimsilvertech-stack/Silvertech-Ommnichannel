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
        PENDING = 'pending', 'Pendente'
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
    send_error_code = models.CharField(max_length=64, blank=True)
    send_attempt_count = models.PositiveIntegerField(default=0)
    last_send_attempt_at = models.DateTimeField(null=True, blank=True)
    next_send_retry_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ('-created_at',)
        verbose_name = 'mensagem'
        verbose_name_plural = 'mensagens'
        indexes = [
            models.Index(fields=['conversation', 'created_at']),
        ]

    def __str__(self) -> str:
        return f'{self.direction} @ {self.conversation_id}'


class AIProcessingRun(BaseModel):
    """Controle idempotente de processamento de IA por mensagem inbound."""

    class Status(models.TextChoices):
        RUNNING = 'running', 'Em processamento'
        RETRYING = 'retrying', 'Aguardando retry'
        SUCCEEDED = 'succeeded', 'Concluido'
        FAILED = 'failed', 'Falhou'
        SKIPPED = 'skipped', 'Ignorado'

    workspace = models.ForeignKey(
        'workspaces.Workspace',
        on_delete=models.CASCADE,
        related_name='ai_processing_runs',
        db_index=True,
    )
    conversation = models.ForeignKey(
        Conversation,
        on_delete=models.CASCADE,
        related_name='ai_processing_runs',
        db_index=True,
    )
    source_message = models.OneToOneField(
        Message,
        on_delete=models.CASCADE,
        related_name='ai_processing_run',
    )
    provider_config = models.ForeignKey(
        'workspaces.WorkspaceAIProviderConfig',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='ai_processing_runs',
    )
    output_message = models.OneToOneField(
        Message,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='ai_processing_output_run',
    )
    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.RUNNING,
        db_index=True,
    )
    attempt_count = models.PositiveIntegerField(default=0)
    error_code = models.CharField(max_length=64, blank=True)
    last_error_code = models.CharField(max_length=64, blank=True)
    next_retry_at = models.DateTimeField(null=True, blank=True)
    last_attempt_at = models.DateTimeField(null=True, blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ('-created_at',)
        verbose_name = 'execucao de IA'
        verbose_name_plural = 'execucoes de IA'
        indexes = [
            models.Index(fields=['workspace', 'status']),
            models.Index(fields=['conversation', 'status']),
            models.Index(fields=['status', 'created_at']),
        ]

    def __str__(self) -> str:
        return f'AIProcessingRun {self.status} @ {self.source_message_id}'


class AIObservabilityEvent(BaseModel):
    """Evento append-only de observabilidade da IA com metadados seguros."""

    class EventType(models.TextChoices):
        AI_SCHEDULED = 'AI_SCHEDULED', 'AI scheduled'
        AI_SKIPPED = 'AI_SKIPPED', 'AI skipped'
        AI_PROVIDER_ATTEMPT = 'AI_PROVIDER_ATTEMPT', 'AI provider attempt'
        AI_PROVIDER_SUCCESS = 'AI_PROVIDER_SUCCESS', 'AI provider success'
        AI_PROVIDER_RETRYING = 'AI_PROVIDER_RETRYING', 'AI provider retrying'
        AI_PROVIDER_FAILED = 'AI_PROVIDER_FAILED', 'AI provider failed'
        OUTBOUND_DELIVERY_ATTEMPT = 'OUTBOUND_DELIVERY_ATTEMPT', 'Outbound delivery attempt'
        OUTBOUND_DELIVERY_SUCCESS = 'OUTBOUND_DELIVERY_SUCCESS', 'Outbound delivery success'
        OUTBOUND_DELIVERY_RETRYING = 'OUTBOUND_DELIVERY_RETRYING', 'Outbound delivery retrying'
        OUTBOUND_DELIVERY_FAILED = 'OUTBOUND_DELIVERY_FAILED', 'Outbound delivery failed'
        PROVIDER_TEST_SUCCESS = 'PROVIDER_TEST_SUCCESS', 'Provider test success'
        PROVIDER_TEST_FAILED = 'PROVIDER_TEST_FAILED', 'Provider test failed'
        PROVIDER_ACTIVATED = 'PROVIDER_ACTIVATED', 'Provider activated'
        PROVIDER_DEACTIVATED = 'PROVIDER_DEACTIVATED', 'Provider deactivated'
        CREDENTIAL_REPLACED = 'CREDENTIAL_REPLACED', 'Credential replaced'
        CREDENTIAL_REPLACE_FAILED = 'CREDENTIAL_REPLACE_FAILED', 'Credential replace failed'
        CREDENTIAL_REVOKED = 'CREDENTIAL_REVOKED', 'Credential revoked'

    class Status(models.TextChoices):
        SUCCESS = 'success', 'Success'
        FAILED = 'failed', 'Failed'
        SKIPPED = 'skipped', 'Skipped'
        RETRYING = 'retrying', 'Retrying'
        PENDING = 'pending', 'Pending'

    workspace = models.ForeignKey(
        'workspaces.Workspace',
        on_delete=models.CASCADE,
        related_name='ai_observability_events',
        db_index=True,
    )
    provider_config = models.ForeignKey(
        'workspaces.WorkspaceAIProviderConfig',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='observability_events',
    )
    conversation = models.ForeignKey(
        Conversation,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='ai_observability_events',
    )
    source_message = models.ForeignKey(
        Message,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='source_observability_events',
    )
    output_message = models.ForeignKey(
        Message,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='output_observability_events',
    )
    ai_processing_run = models.ForeignKey(
        AIProcessingRun,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='observability_events',
    )
    event_type = models.CharField(max_length=64, choices=EventType.choices, db_index=True)
    status = models.CharField(max_length=32, choices=Status.choices, db_index=True)
    provider = models.CharField(max_length=32, blank=True)
    model_name = models.CharField(max_length=128, blank=True)
    reason_code = models.CharField(max_length=64, blank=True)
    error_code = models.CharField(max_length=64, blank=True)
    latency_ms = models.PositiveIntegerField(null=True, blank=True)
    attempt_count = models.PositiveIntegerField(null=True, blank=True)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ('-created_at',)
        verbose_name = 'evento de observabilidade de IA'
        verbose_name_plural = 'eventos de observabilidade de IA'
        indexes = [
            models.Index(fields=['workspace', 'created_at']),
            models.Index(fields=['workspace', 'event_type', 'created_at']),
            models.Index(fields=['workspace', 'status', 'created_at']),
            models.Index(fields=['workspace', 'provider', 'created_at']),
            models.Index(fields=['workspace', 'error_code', 'created_at']),
        ]

    def __str__(self) -> str:
        return f'{self.event_type} {self.status} @ {self.workspace_id}'
