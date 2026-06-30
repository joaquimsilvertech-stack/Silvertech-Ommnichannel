from __future__ import annotations

from django.contrib.auth import get_user_model
from rest_framework import serializers

from crm.models import Contact
from omnichannel.models import Conversation
from workspaces.models import Member, Workspace

from .models import Ticket

User = get_user_model()


def _user_workspace_ids(context):
    request = context.get('request')
    if not request or not request.user.is_authenticated:
        return Workspace.objects.none().values_list('id', flat=True)
    return Member.objects.filter(user=request.user).values_list('workspace_id', flat=True)


class _WorkspaceNestedSerializer(serializers.ModelSerializer):
    class Meta:
        model = Workspace
        fields = ('id', 'name')
        read_only_fields = fields


class _ContactNestedSerializer(serializers.ModelSerializer):
    class Meta:
        model = Contact
        fields = ('id', 'name', 'phone', 'email')
        read_only_fields = fields


class _ConversationNestedSerializer(serializers.ModelSerializer):
    class Meta:
        model = Conversation
        fields = ('id', 'channel', 'status', 'is_human_handoff')
        read_only_fields = fields


class _AssignedToNestedSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ('id', 'email')
        read_only_fields = fields


class TicketSerializer(serializers.ModelSerializer):
    workspace = _WorkspaceNestedSerializer(read_only=True)
    workspace_id = serializers.PrimaryKeyRelatedField(
        queryset=Workspace.objects.all(),
        source='workspace',
        write_only=True,
        required=False,
    )
    contact = _ContactNestedSerializer(read_only=True)
    contact_id = serializers.PrimaryKeyRelatedField(
        queryset=Contact.objects.all(),
        source='contact',
        write_only=True,
        required=False,
    )
    conversation = _ConversationNestedSerializer(read_only=True)
    conversation_id = serializers.PrimaryKeyRelatedField(
        queryset=Conversation.objects.all(),
        source='conversation',
        write_only=True,
        required=False,
        allow_null=True,
    )
    assigned_to = _AssignedToNestedSerializer(read_only=True)
    assigned_to_id = serializers.PrimaryKeyRelatedField(
        queryset=User.objects.all(),
        source='assigned_to',
        write_only=True,
        required=False,
        allow_null=True,
    )

    class Meta:
        model = Ticket
        fields = (
            'id',
            'workspace_id',
            'workspace',
            'contact_id',
            'contact',
            'conversation_id',
            'conversation',
            'title',
            'status',
            'assigned_to_id',
            'assigned_to',
            'due_at',
            'created_at',
            'updated_at',
        )
        read_only_fields = (
            'id',
            'workspace',
            'contact',
            'conversation',
            'assigned_to',
            'created_at',
            'updated_at',
        )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        workspace_ids = _user_workspace_ids(self.context)
        self.fields['workspace_id'].queryset = Workspace.objects.filter(id__in=workspace_ids)
        self.fields['contact_id'].queryset = Contact.objects.filter(workspace_id__in=workspace_ids)
        self.fields['conversation_id'].queryset = Conversation.objects.filter(
            workspace_id__in=workspace_ids,
        )
        self.fields['assigned_to_id'].queryset = User.objects.filter(
            memberships__workspace_id__in=workspace_ids,
        ).distinct()

    def validate_workspace_id(self, workspace):
        workspace_ids = _user_workspace_ids(self.context)
        if workspace.id not in workspace_ids:
            raise serializers.ValidationError('Sem acesso a este workspace.')
        return workspace

    def validate_contact_id(self, contact):
        workspace_ids = _user_workspace_ids(self.context)
        if contact.workspace_id not in workspace_ids:
            raise serializers.ValidationError('Contato fora dos seus workspaces.')
        return contact

    def validate_conversation_id(self, conversation):
        if conversation is None:
            return conversation
        workspace_ids = _user_workspace_ids(self.context)
        if conversation.workspace_id not in workspace_ids:
            raise serializers.ValidationError('Conversa fora dos seus workspaces.')
        return conversation

    def validate_assigned_to_id(self, assigned_to):
        if assigned_to is None:
            return assigned_to
        workspace_ids = _user_workspace_ids(self.context)
        if not Member.objects.filter(user=assigned_to, workspace_id__in=workspace_ids).exists():
            raise serializers.ValidationError('Agente fora dos seus workspaces.')
        return assigned_to

    def validate(self, attrs):
        workspace = attrs.get('workspace') or (self.instance.workspace if self.instance else None)
        contact = attrs.get('contact') or (self.instance.contact if self.instance else None)
        conversation = attrs.get('conversation') or (
            self.instance.conversation if self.instance else None
        )

        if self.instance is None:
            errors = {}
            if workspace is None:
                errors['workspace_id'] = 'O workspace e obrigatorio na criacao.'
            if contact is None:
                errors['contact_id'] = 'O contato e obrigatorio na criacao.'
            if errors:
                raise serializers.ValidationError(errors)

        if workspace and contact and contact.workspace_id != workspace.id:
            raise serializers.ValidationError(
                {'contact_id': 'O contato deve pertencer ao workspace do ticket.'},
            )

        if workspace and conversation and conversation.workspace_id != workspace.id:
            raise serializers.ValidationError(
                {'conversation_id': 'A conversa deve pertencer ao workspace do ticket.'},
            )

        if contact and conversation and conversation.contact_id != contact.id:
            raise serializers.ValidationError(
                {'conversation_id': 'A conversa deve pertencer ao contato do ticket.'},
            )

        return attrs
