from django.contrib.auth import get_user_model
from rest_framework import serializers

from workspaces.models import Member, Workspace

from .models import Contact, Lead, Organization

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


class ContactSerializer(serializers.ModelSerializer):
    workspace = _WorkspaceNestedSerializer(read_only=True)
    workspace_id = serializers.PrimaryKeyRelatedField(
        queryset=Workspace.objects.all(),
        source='workspace',
        write_only=True,
        required=False,
    )

    class Meta:
        model = Contact
        fields = (
            'id',
            'workspace_id',
            'workspace',
            'name',
            'phone',
            'email',
            'channel_id',
            'starred',
            'contact_type',
            'custom_attributes',
            'created_at',
            'updated_at',
        )
        read_only_fields = ('id', 'workspace', 'created_at', 'updated_at')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        workspace_ids = _user_workspace_ids(self.context)
        self.fields['workspace_id'].queryset = Workspace.objects.filter(id__in=workspace_ids)

    def validate_workspace_id(self, workspace):
        workspace_ids = _user_workspace_ids(self.context)
        if workspace.id not in workspace_ids:
            raise serializers.ValidationError('Sem acesso a este workspace.')
        return workspace

    def validate(self, attrs):
        if self.instance is None and 'workspace' not in attrs:
            raise serializers.ValidationError(
                {'workspace_id': 'O workspace é obrigatório na criação.'},
            )
        return attrs


class _AssignedToNestedSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ('id', 'email')
        read_only_fields = fields


class LeadSerializer(serializers.ModelSerializer):
    contact_id = serializers.PrimaryKeyRelatedField(
        queryset=Contact.objects.all(),
        source='contact',
        write_only=True,
        required=False,
    )
    contact = serializers.PrimaryKeyRelatedField(read_only=True)
    contact_name = serializers.CharField(source='contact.name', read_only=True)
    assigned_to = _AssignedToNestedSerializer(read_only=True)
    assigned_to_id = serializers.PrimaryKeyRelatedField(
        queryset=User.objects.all(),
        source='assigned_to',
        write_only=True,
        required=False,
        allow_null=True,
    )

    class Meta:
        model = Lead
        fields = (
            'id',
            'contact_id',
            'contact',
            'contact_name',
            'status',
            'score',
            'source',
            'assigned_to_id',
            'assigned_to',
            'notes',
            'created_at',
            'updated_at',
        )
        read_only_fields = ('id', 'contact', 'contact_name', 'assigned_to', 'created_at', 'updated_at')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        workspace_ids = _user_workspace_ids(self.context)
        self.fields['contact_id'].queryset = Contact.objects.filter(workspace_id__in=workspace_ids)

    def validate_contact_id(self, contact):
        workspace_ids = _user_workspace_ids(self.context)
        if contact.workspace_id not in workspace_ids:
            raise serializers.ValidationError('Contato fora dos seus workspaces.')
        return contact

    def validate(self, attrs):
        if self.instance is None and 'contact' not in attrs:
            raise serializers.ValidationError(
                {'contact_id': 'O contato é obrigatório na criação.'},
            )
        return attrs


class _ContactSummarySerializer(serializers.ModelSerializer):
    class Meta:
        model = Contact
        fields = ('id', 'name', 'email', 'phone')
        read_only_fields = fields


class OrganizationSerializer(serializers.ModelSerializer):
    workspace = _WorkspaceNestedSerializer(read_only=True)
    workspace_id = serializers.PrimaryKeyRelatedField(
        queryset=Workspace.objects.all(),
        source='workspace',
        write_only=True,
        required=False,
    )
    contacts = _ContactSummarySerializer(many=True, read_only=True)
    contact_ids = serializers.PrimaryKeyRelatedField(
        queryset=Contact.objects.all(),
        source='contacts',
        many=True,
        write_only=True,
        required=False,
    )

    class Meta:
        model = Organization
        fields = (
            'id',
            'workspace_id',
            'workspace',
            'name',
            'contact_ids',
            'contacts',
            'created_at',
            'updated_at',
        )
        read_only_fields = ('id', 'workspace', 'contacts', 'created_at', 'updated_at')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        workspace_ids = _user_workspace_ids(self.context)
        scoped_contacts = Contact.objects.filter(workspace_id__in=workspace_ids)
        self.fields['workspace_id'].queryset = Workspace.objects.filter(id__in=workspace_ids)
        self.fields['contact_ids'].queryset = scoped_contacts

    def validate_workspace_id(self, workspace):
        workspace_ids = _user_workspace_ids(self.context)
        if workspace.id not in workspace_ids:
            raise serializers.ValidationError('Sem acesso a este workspace.')
        return workspace

    def validate(self, attrs):
        if self.instance is None and 'workspace' not in attrs:
            raise serializers.ValidationError(
                {'workspace_id': 'O workspace é obrigatório na criação.'},
            )
        contacts = attrs.get('contacts')
        workspace = attrs.get('workspace') or (self.instance.workspace if self.instance else None)
        if contacts and workspace:
            invalid = [c for c in contacts if c.workspace_id != workspace.id]
            if invalid:
                raise serializers.ValidationError(
                    {'contact_ids': 'Todos os contatos devem pertencer ao mesmo workspace.'},
                )
        return attrs
