from __future__ import annotations

from rest_framework import serializers

from omnichannel.models import AIObservabilityEvent
from omnichannel.observability import sanitize_observability_metadata


class AIObservabilityEventSerializer(serializers.ModelSerializer):
    """Serializer read-only para eventos seguros de observabilidade da IA."""

    metadata = serializers.SerializerMethodField()
    whatsapp_channel_id = serializers.SerializerMethodField()

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
            'whatsapp_channel_id',
            'metadata',
        )
        read_only_fields = fields

    def get_metadata(self, obj: AIObservabilityEvent) -> dict:
        return sanitize_observability_metadata(obj.metadata)

    def get_whatsapp_channel_id(self, obj: AIObservabilityEvent) -> str | None:
        channel_id = obj.whatsapp_channel_id or obj.whatsapp_channel_id_snapshot
        return str(channel_id) if channel_id is not None else None


class ChannelObservabilityQuerySerializer(serializers.Serializer):
    period = serializers.ChoiceField(choices=('24h', '7d', '30d'), default='24h')
    provider = serializers.CharField(required=False, allow_blank=True)
    event_type = serializers.CharField(required=False, allow_blank=True)
    status = serializers.CharField(required=False, allow_blank=True)
    error_code = serializers.CharField(required=False, allow_blank=True)


class ChannelObservabilityTotalsSerializer(serializers.Serializer):
    channels_created = serializers.IntegerField()
    channels_provisioned = serializers.IntegerField()
    webhooks_configured = serializers.IntegerField()
    qr_generated = serializers.IntegerField()
    channels_connected = serializers.IntegerField(
        help_text=(
            'Snapshot atual de canais com status connected no Workspace; '
            'independe da janela temporal.'
        ),
    )
    channels_disconnected = serializers.IntegerField(
        help_text=(
            'Snapshot atual de canais com status disconnected no Workspace; '
            'independe da janela temporal.'
        ),
    )
    channel_connected_events = serializers.IntegerField(
        help_text='Transicoes historicas para connected dentro da janela.',
    )
    channel_disconnected_events = serializers.IntegerField(
        help_text='Transicoes historicas para disconnected dentro da janela.',
    )
    channels_reconnecting = serializers.IntegerField()
    channels_error = serializers.IntegerField()
    provisioning_failed = serializers.IntegerField()
    channels_removed = serializers.IntegerField()
    inbound_received = serializers.IntegerField()
    outbound_attempt = serializers.IntegerField()
    outbound_success = serializers.IntegerField()
    outbound_failed = serializers.IntegerField()


class ChannelObservabilityRatesSerializer(serializers.Serializer):
    outbound_success_rate = serializers.FloatField()


class ChannelObservabilityLatencySerializer(serializers.Serializer):
    avg_time_to_qr_ms = serializers.IntegerField(allow_null=True)
    avg_time_to_connection_ms = serializers.IntegerField(
        allow_null=True,
        help_text=(
            'Media entre CHANNEL_CREATED e o primeiro CHANNEL_CONNECTED do mesmo '
            'Workspace/canal. A janela considera o timestamp da primeira conexao; '
            'reconexoes e pares incompletos sao ignorados.'
        ),
    )
    avg_delivery_latency_ms = serializers.IntegerField(allow_null=True)


class ChannelObservabilityByChannelSerializer(serializers.Serializer):
    whatsapp_channel_id = serializers.UUIDField(
        help_text='UUID vivo do canal ou snapshot imutavel apos hard-delete.',
    )
    connected = serializers.IntegerField()
    disconnected = serializers.IntegerField()
    errors = serializers.IntegerField()
    inbound_received = serializers.IntegerField()
    outbound_success = serializers.IntegerField()
    outbound_failed = serializers.IntegerField()


class ObservabilityErrorCountSerializer(serializers.Serializer):
    error_code = serializers.CharField()
    count = serializers.IntegerField()


class ChannelObservabilitySummarySerializer(serializers.Serializer):
    workspace_id = serializers.UUIDField()
    period = serializers.ChoiceField(choices=('24h', '7d', '30d'))
    totals = ChannelObservabilityTotalsSerializer()
    rates = ChannelObservabilityRatesSerializer()
    latency = ChannelObservabilityLatencySerializer()
    by_channel = ChannelObservabilityByChannelSerializer(many=True)
    errors = ObservabilityErrorCountSerializer(many=True)


class ChannelObservabilityPointSerializer(serializers.Serializer):
    timestamp = serializers.DateTimeField()
    connected = serializers.IntegerField()
    disconnected = serializers.IntegerField()
    errors = serializers.IntegerField()
    inbound_received = serializers.IntegerField()
    outbound_success = serializers.IntegerField()
    outbound_failed = serializers.IntegerField()


class ChannelObservabilityTimeseriesSerializer(serializers.Serializer):
    workspace_id = serializers.UUIDField()
    period = serializers.ChoiceField(choices=('24h', '7d', '30d'))
    bucket = serializers.ChoiceField(choices=('hour', 'day'))
    points = ChannelObservabilityPointSerializer(many=True)
