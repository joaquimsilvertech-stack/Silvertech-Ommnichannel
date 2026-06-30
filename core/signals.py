from __future__ import annotations

import logging
from typing import Any

from django.apps import apps
from django.db import models
from django.db.models.signals import post_delete, post_save, pre_delete, pre_save
from django.dispatch import receiver

from .audit import (
    calculate_changes,
    get_actor,
    get_client_ip,
    get_request_id,
    get_user_agent,
    resolve_workspace,
    serialize_instance,
    short_repr,
)
from .middleware import get_current_request
from .models import AuditLog

logger = logging.getLogger(__name__)

AUDITED_MODEL_LABELS = (
    'workspaces.Workspace',
    'workspaces.Member',
    'workspaces.WorkspaceInvite',
    'crm.Contact',
    'crm.Lead',
    'crm.Organization',
    'omnichannel.Conversation',
    'tickets.Ticket',
    'automations.Flow',
)


def connect_audit_signals() -> None:
    """Conecta auditoria somente para models instalados no projeto."""
    for label in AUDITED_MODEL_LABELS:
        try:
            model = apps.get_model(label)
        except LookupError:
            continue

        pre_save.connect(
            capture_before_state,
            sender=model,
            dispatch_uid=f'audit_pre_save_{label}',
        )
        post_save.connect(
            create_audit_log_on_save,
            sender=model,
            dispatch_uid=f'audit_post_save_{label}',
        )
        pre_delete.connect(
            capture_delete_state,
            sender=model,
            dispatch_uid=f'audit_pre_delete_{label}',
        )
        post_delete.connect(
            create_audit_log_on_delete,
            sender=model,
            dispatch_uid=f'audit_post_delete_{label}',
        )


@receiver(pre_save, sender=AuditLog)
def skip_auditlog_pre_save(sender: type[AuditLog], **kwargs: Any) -> None:
    """Marcador explicito: AuditLog nunca deve auditar a si mesmo."""
    return None


def capture_before_state(sender: type[models.Model], instance: models.Model, **kwargs: Any) -> None:
    if instance._state.adding or not instance.pk:
        instance._audit_before = None
        return

    try:
        previous = sender.objects.get(pk=instance.pk)
    except sender.DoesNotExist:
        instance._audit_before = None
        return

    instance._audit_before = serialize_instance(previous)


def create_audit_log_on_save(
    sender: type[models.Model],
    instance: models.Model,
    created: bool,
    **kwargs: Any,
) -> None:
    before = getattr(instance, '_audit_before', None)
    after = serialize_instance(instance)

    if created:
        _create_audit_log(instance, AuditLog.Action.CREATE, before=None, after=after, changes=None)
        return

    changes = calculate_changes(before, after)
    if not changes:
        return

    _create_audit_log(instance, AuditLog.Action.UPDATE, before=before, after=after, changes=changes)


def capture_delete_state(sender: type[models.Model], instance: models.Model, **kwargs: Any) -> None:
    instance._audit_before_delete = serialize_instance(instance)


def create_audit_log_on_delete(
    sender: type[models.Model],
    instance: models.Model,
    **kwargs: Any,
) -> None:
    before = getattr(instance, '_audit_before_delete', None) or serialize_instance(instance)
    _create_audit_log(instance, AuditLog.Action.DELETE, before=before, after=None, changes=None)


def _create_audit_log(
    instance: models.Model,
    action: str,
    before: dict[str, Any] | None,
    after: dict[str, Any] | None,
    changes: dict[str, Any] | None,
) -> None:
    workspace = resolve_workspace(instance)
    if workspace is None:
        logger.debug(
            'AuditLog ignorado: workspace nao resolvido para %s:%s',
            instance.__class__.__name__,
            instance.pk,
        )
        return

    request = get_current_request()
    try:
        AuditLog.objects.create(
            workspace=workspace,
            actor=get_actor(request),
            action=action,
            model_name=instance.__class__.__name__,
            object_id=str(instance.pk),
            object_repr=short_repr(instance),
            before=before,
            after=after,
            changes=changes,
            ip_address=get_client_ip(request),
            user_agent=get_user_agent(request),
            request_id=get_request_id(request),
        )
    except Exception as exc:
        logger.warning(
            'Falha ao criar AuditLog para %s:%s: %s',
            instance.__class__.__name__,
            instance.pk,
            exc,
            exc_info=True,
        )
