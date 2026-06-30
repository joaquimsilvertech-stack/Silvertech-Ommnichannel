from django.apps import AppConfig


class CoreConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'core'
    verbose_name = 'SilverTech Omnichannel - Core'

    def ready(self) -> None:
        from .signals import connect_audit_signals

        connect_audit_signals()
