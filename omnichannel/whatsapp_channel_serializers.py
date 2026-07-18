from __future__ import annotations

import unicodedata
from collections.abc import Mapping
from typing import Any

from rest_framework import serializers

from omnichannel.models import WhatsAppChannel
from omnichannel.whatsapp_channel_read_service import mask_whatsapp_phone_number


class WhatsAppChannelCreateSerializer(serializers.Serializer):
    name = serializers.CharField(
        required=True,
        allow_blank=False,
        trim_whitespace=False,
    )

    def to_internal_value(self, data: Any) -> dict[str, Any]:
        if isinstance(data, Mapping):
            unknown_fields = set(data) - {'name'}
            if unknown_fields:
                raise serializers.ValidationError(
                    {
                        field: 'Campo nao permitido.'
                        for field in sorted(unknown_fields)
                    },
                )
            if 'name' in data and not isinstance(data['name'], str):
                raise serializers.ValidationError({'name': 'Deve ser uma string.'})
        return super().to_internal_value(data)

    def validate_name(self, value: str) -> str:
        if any(unicodedata.category(character) == 'Cc' for character in value):
            raise serializers.ValidationError('Caracteres de controle nao sao permitidos.')

        normalized = ' '.join(value.split())
        max_length = WhatsAppChannel._meta.get_field('name').max_length
        if not normalized:
            raise serializers.ValidationError('Este campo nao pode ficar vazio.')
        if max_length is not None and len(normalized) > max_length:
            raise serializers.ValidationError(
                f'Certifique-se de que este campo tenha no maximo {max_length} caracteres.',
            )
        return normalized


class WhatsAppChannelSafeSerializer(serializers.ModelSerializer):
    class Meta:
        model = WhatsAppChannel
        fields = (
            'id',
            'name',
            'provider',
            'status',
            'created_at',
            'updated_at',
        )
        read_only_fields = fields


class _WhatsAppChannelPublicFieldsMixin:
    def get_phone_number_masked(self, channel: WhatsAppChannel) -> str | None:
        return mask_whatsapp_phone_number(channel.phone_number)

    def get_has_qr_code(self, channel: WhatsAppChannel) -> bool:
        availability = self.context.get('qr_availability', {})
        return bool(availability.get(channel.id, False))


class WhatsAppChannelPublicSerializer(
    _WhatsAppChannelPublicFieldsMixin,
    serializers.ModelSerializer,
):
    phone_number_masked = serializers.SerializerMethodField()
    has_qr_code = serializers.SerializerMethodField()

    class Meta:
        model = WhatsAppChannel
        fields = (
            'id',
            'name',
            'provider',
            'status',
            'phone_number_masked',
            'has_qr_code',
            'connected_at',
            'last_connection_update_at',
            'created_at',
            'updated_at',
        )
        read_only_fields = fields


class WhatsAppChannelStatusSerializer(
    _WhatsAppChannelPublicFieldsMixin,
    serializers.ModelSerializer,
):
    phone_number_masked = serializers.SerializerMethodField()
    has_qr_code = serializers.SerializerMethodField()

    class Meta:
        model = WhatsAppChannel
        fields = (
            'id',
            'status',
            'phone_number_masked',
            'has_qr_code',
            'connected_at',
            'last_connection_update_at',
            'updated_at',
        )
        read_only_fields = fields


class WhatsAppChannelQRCodeSerializer(serializers.Serializer):
    id = serializers.UUIDField(source='channel_id', read_only=True)
    status = serializers.CharField(read_only=True)
    has_qr_code = serializers.BooleanField(read_only=True)
    qr_code = serializers.CharField(read_only=True, allow_null=True)
    format = serializers.CharField(source='qr_format', read_only=True, allow_null=True)
