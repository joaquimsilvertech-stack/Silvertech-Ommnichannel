from __future__ import annotations

from rest_framework import serializers

from omnichannel.models import AIObservabilityEvent


class AIObservabilityEventSerializer(serializers.ModelSerializer):
    """Serializer read-only para eventos seguros de observabilidade da IA."""

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
