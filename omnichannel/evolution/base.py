from __future__ import annotations

from abc import ABC, abstractmethod

from .types import EvolutionResponse


class BaseEvolutionClient(ABC):
    """Contrato HTTP independente de Workspace e de persistencia local."""

    @abstractmethod
    def create_instance(
        self,
        *,
        instance_name: str,
        qrcode: bool = True,
        integration: str = 'WHATSAPP-BAILEYS',
    ) -> EvolutionResponse:
        raise NotImplementedError

    @abstractmethod
    def configure_webhook(
        self,
        *,
        instance_name: str,
        url: str,
        events: list[str],
        enabled: bool = True,
        webhook_by_events: bool = False,
        headers: dict[str, str] | None = None,
    ) -> EvolutionResponse:
        raise NotImplementedError

    @abstractmethod
    def get_qr_code(self, *, instance_name: str) -> EvolutionResponse:
        raise NotImplementedError

    @abstractmethod
    def get_connection_state(self, *, instance_name: str) -> EvolutionResponse:
        raise NotImplementedError

    @abstractmethod
    def send_text(
        self,
        *,
        instance_name: str,
        number: str,
        text: str,
    ) -> EvolutionResponse:
        raise NotImplementedError

    @abstractmethod
    def restart_instance(self, *, instance_name: str) -> EvolutionResponse:
        raise NotImplementedError

    @abstractmethod
    def logout_instance(self, *, instance_name: str) -> EvolutionResponse:
        raise NotImplementedError

    @abstractmethod
    def delete_instance(self, *, instance_name: str) -> EvolutionResponse:
        raise NotImplementedError

