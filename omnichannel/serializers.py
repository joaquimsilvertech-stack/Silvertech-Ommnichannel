from rest_framework import serializers

from .models import Conversation, Message


class _ContactInboxSerializer(serializers.Serializer):
    id = serializers.UUIDField(read_only=True)
    name = serializers.CharField(read_only=True)
    phone = serializers.CharField(read_only=True)
    channel_id = serializers.CharField(read_only=True, allow_null=True)


class MessageCreateSerializer(serializers.Serializer):
    body = serializers.CharField()


class MessageSerializer(serializers.ModelSerializer):
    class Meta:
        model = Message
        fields = (
            'id',
            'conversation',
            'body',
            'direction',
            'status',
            'external_id',
            'created_at',
            'updated_at',
        )
        read_only_fields = ('id', 'created_at', 'updated_at')


class ConversationSerializer(serializers.ModelSerializer):
    contact = serializers.PrimaryKeyRelatedField(read_only=True)
    contact_data = _ContactInboxSerializer(source='contact', read_only=True)

    class Meta:
        model = Conversation
        fields = (
            'id',
            'workspace',
            'contact',
            'contact_data',
            'channel',
            'status',
            'created_at',
            'updated_at',
        )
        read_only_fields = ('id', 'created_at', 'updated_at')
