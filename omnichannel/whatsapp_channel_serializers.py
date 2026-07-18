from __future__ import annotations

import unicodedata
from collections.abc import Mapping
from typing import Any

from rest_framework import serializers

from omnichannel.models import WhatsAppChannel


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

