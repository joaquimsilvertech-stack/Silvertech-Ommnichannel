from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from django.db import IntegrityError, transaction
from django.db.models import QuerySet

from omnichannel.models import Conversation, WhatsAppChannel
from workspaces.models import Workspace

LEGACY_WHATSAPP_CHANNEL = 'whatsapp'
DEFAULT_LEGACY_CHANNEL_NAME = 'WhatsApp legado'


class LegacyChannelMigrationError(Exception):
    """Erro operacional seguro durante a migracao do canal legado."""


@dataclass(frozen=True, slots=True)
class LegacyChannelMigrationResult:
    workspace_id: UUID
    channel_id: UUID | None
    instance_name: str
    channel_state: str
    eligible_count: int
    updated_count: int
    ignored_count: int
    dry_run: bool
    rollback: bool


def migrate_legacy_channel(
    *,
    workspace_id: UUID | str,
    instance_name: str,
    channel_name: str = DEFAULT_LEGACY_CHANNEL_NAME,
    dry_run: bool = False,
    rollback: bool = False,
) -> LegacyChannelMigrationResult:
    """Cria/reutiliza o canal legado e associa ou desassocia conversas locais."""
    normalized_workspace_id = _normalize_workspace_id(workspace_id)
    normalized_instance_name = _normalize_required_model_value(
        instance_name,
        field_name='instance_name',
    )
    normalized_channel_name = _normalize_required_model_value(
        channel_name,
        field_name='name',
    )

    try:
        with transaction.atomic():
            workspace = _get_locked_workspace(normalized_workspace_id)
            channel = _get_locked_channel(normalized_instance_name)

            if channel is not None and channel.workspace_id != workspace.id:
                raise LegacyChannelMigrationError(
                    'A instancia informada ja pertence a outro workspace.',
                )

            if rollback:
                return _rollback_channel_associations(
                    workspace=workspace,
                    channel=channel,
                    instance_name=normalized_instance_name,
                    dry_run=dry_run,
                )

            return _migrate_channel_associations(
                workspace=workspace,
                channel=channel,
                instance_name=normalized_instance_name,
                channel_name=normalized_channel_name,
                dry_run=dry_run,
            )
    except IntegrityError as exc:
        raise LegacyChannelMigrationError(
            'Conflito de integridade ao migrar o canal legado.',
        ) from exc


def _migrate_channel_associations(
    *,
    workspace: Workspace,
    channel: WhatsAppChannel | None,
    instance_name: str,
    channel_name: str,
    dry_run: bool,
) -> LegacyChannelMigrationResult:
    channel_state = 'reused'

    if channel is None:
        name_conflict = (
            WhatsAppChannel.objects.select_for_update()
            .filter(workspace=workspace, name=channel_name)
            .first()
        )
        if name_conflict is not None:
            raise LegacyChannelMigrationError(
                'Ja existe um canal com esse nome e outra instancia no workspace.',
            )

        if dry_run:
            channel_state = 'would_create'
        else:
            channel = WhatsAppChannel.objects.create(
                workspace=workspace,
                provider=WhatsAppChannel.Provider.EVOLUTION,
                name=channel_name,
                instance_name=instance_name,
                status=WhatsAppChannel.Status.DISCONNECTED,
            )
            channel_state = 'created'

    eligible = _eligible_migration_conversations(workspace)
    eligible_count = eligible.count()
    ignored_count = _already_associated_whatsapp_conversations(workspace).count()
    updated_count = 0

    if not dry_run:
        if channel is None:  # pragma: no cover - protegido pelo fluxo acima
            raise LegacyChannelMigrationError('Canal legado nao foi criado.')
        updated_count = _associate_eligible_conversations(eligible, channel)

    return LegacyChannelMigrationResult(
        workspace_id=workspace.id,
        channel_id=channel.id if channel is not None else None,
        instance_name=instance_name,
        channel_state=channel_state,
        eligible_count=eligible_count,
        updated_count=updated_count,
        ignored_count=ignored_count,
        dry_run=dry_run,
        rollback=False,
    )


def _rollback_channel_associations(
    *,
    workspace: Workspace,
    channel: WhatsAppChannel | None,
    instance_name: str,
    dry_run: bool,
) -> LegacyChannelMigrationResult:
    if channel is None:
        raise LegacyChannelMigrationError(
            'Canal legado nao encontrado para o workspace informado.',
        )

    associated = Conversation.objects.filter(
        workspace=workspace,
        channel=LEGACY_WHATSAPP_CHANNEL,
        whatsapp_channel=channel,
    )
    eligible_count = associated.count()
    ignored_count = (
        Conversation.objects.filter(
            workspace=workspace,
            channel=LEGACY_WHATSAPP_CHANNEL,
        )
        .exclude(whatsapp_channel=channel)
        .count()
    )
    updated_count = 0 if dry_run else _remove_channel_associations(associated)

    return LegacyChannelMigrationResult(
        workspace_id=workspace.id,
        channel_id=channel.id,
        instance_name=instance_name,
        channel_state='located',
        eligible_count=eligible_count,
        updated_count=updated_count,
        ignored_count=ignored_count,
        dry_run=dry_run,
        rollback=True,
    )


def _normalize_workspace_id(workspace_id: UUID | str) -> UUID:
    try:
        return UUID(str(workspace_id))
    except (AttributeError, TypeError, ValueError) as exc:
        raise LegacyChannelMigrationError(
            'workspace-id deve ser um UUID valido.',
        ) from exc


def _normalize_required_model_value(value: str, *, field_name: str) -> str:
    normalized = str(value or '').strip()
    if not normalized:
        raise LegacyChannelMigrationError(f'{field_name} nao pode ser vazio.')

    field = WhatsAppChannel._meta.get_field(field_name)
    if field.max_length is not None and len(normalized) > field.max_length:
        raise LegacyChannelMigrationError(
            f'{field_name} excede o limite de {field.max_length} caracteres.',
        )
    return normalized


def _get_locked_workspace(workspace_id: UUID) -> Workspace:
    try:
        return Workspace.objects.select_for_update().get(id=workspace_id)
    except Workspace.DoesNotExist as exc:
        raise LegacyChannelMigrationError('Workspace informado nao existe.') from exc


def _get_locked_channel(instance_name: str) -> WhatsAppChannel | None:
    return (
        WhatsAppChannel.objects.select_for_update()
        .filter(instance_name=instance_name)
        .first()
    )


def _eligible_migration_conversations(workspace: Workspace) -> QuerySet[Conversation]:
    return Conversation.objects.filter(
        workspace=workspace,
        channel=LEGACY_WHATSAPP_CHANNEL,
        whatsapp_channel__isnull=True,
    )


def _already_associated_whatsapp_conversations(
    workspace: Workspace,
) -> QuerySet[Conversation]:
    return Conversation.objects.filter(
        workspace=workspace,
        channel=LEGACY_WHATSAPP_CHANNEL,
        whatsapp_channel__isnull=False,
    )


def _associate_eligible_conversations(
    conversations: QuerySet[Conversation],
    channel: WhatsAppChannel,
) -> int:
    return conversations.update(whatsapp_channel=channel)


def _remove_channel_associations(conversations: QuerySet[Conversation]) -> int:
    return conversations.update(whatsapp_channel=None)
