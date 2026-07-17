from __future__ import annotations

from typing import Any, TypeAlias

EvolutionResponse: TypeAlias = dict[str, Any]

MAX_INSTANCE_NAME_LENGTH = 128
SUPPORTED_INTEGRATIONS = frozenset(
    {
        'WHATSAPP-BAILEYS',
        'WHATSAPP-BUSINESS',
    },
)

