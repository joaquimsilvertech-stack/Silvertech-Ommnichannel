from __future__ import annotations

from typing import Any

from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from omnichannel.models import Message

from .cache import invalidate_dashboard_metrics_cache
from .models import Contact, Lead


@receiver([post_save, post_delete], sender=Contact)
def invalidate_dashboard_cache_on_contact_change(
    sender: type[Contact],
    instance: Contact,
    **kwargs: Any,
) -> None:
    invalidate_dashboard_metrics_cache(instance.workspace_id)


@receiver([post_save, post_delete], sender=Lead)
def invalidate_dashboard_cache_on_lead_change(
    sender: type[Lead],
    instance: Lead,
    **kwargs: Any,
) -> None:
    invalidate_dashboard_metrics_cache(instance.contact.workspace_id)


@receiver([post_save, post_delete], sender=Message)
def invalidate_dashboard_cache_on_message_change(
    sender: type[Message],
    instance: Message,
    **kwargs: Any,
) -> None:
    invalidate_dashboard_metrics_cache(instance.conversation.workspace_id)
