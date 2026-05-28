from django.apps import AppConfig


class OmnichannelConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'omnichannel'
    verbose_name = 'SilverTech Omnichannel — Conversas'

    def ready(self) -> None:
        from . import signals  # noqa: F401
