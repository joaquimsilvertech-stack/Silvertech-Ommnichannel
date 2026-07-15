from __future__ import annotations

from rest_framework import serializers

from omnichannel.models import AIObservabilityEvent
from omnichannel.observability import sanitize_observability_metadata


class AIObservabilityEventSerializer(serializers.ModelSerializer):
    """Serializer read-only para eventos seguros de observabilidade da IA."""

    metadata = serializers.SerializerMethodField()

    class Meta:
        model = AIObservabilityEvent
        fields = (
            'id',
            'created_at',
            'event_type',
            'status',
            'provider',
            'model_name',
            'reason_code',
            'error_code',
            'latency_ms',
            'attempt_count',
            'metadata',
        )
        read_only_fields = fields

    def get_metadata(self, obj: AIObservabilityEvent) -> dict:
        return sanitize_observability_metadata(obj.metadata)
