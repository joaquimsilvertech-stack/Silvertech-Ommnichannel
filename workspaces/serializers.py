from django.contrib.auth import get_user_model
from rest_framework import serializers

from .models import Member, Workspace, WorkspaceInvite

User = get_user_model()


class WorkspaceSerializer(serializers.ModelSerializer):
    class Meta:
        model = Workspace
        fields = (
            'id',
            'name',
            'slug',
            'created_at',
            'updated_at',
        )
        read_only_fields = ('id', 'created_at', 'updated_at')


class _UserNestedSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ('id', 'email')
        read_only_fields = fields


class _WorkspaceNestedSerializer(serializers.ModelSerializer):
    class Meta:
        model = Workspace
        fields = ('id', 'name')
        read_only_fields = fields


class MemberSerializer(serializers.ModelSerializer):
    """
    Leitura: usuário (e-mail) e workspace (nome) aninhados.
    Escrita: apenas `user_id` e `workspace_id`.
    """

    user = _UserNestedSerializer(read_only=True)
    workspace = _WorkspaceNestedSerializer(read_only=True)
    user_id = serializers.PrimaryKeyRelatedField(
        queryset=User.objects.all(),
        source='user',
        write_only=True,
        required=False,
    )
    workspace_id = serializers.PrimaryKeyRelatedField(
        queryset=Workspace.objects.all(),
        source='workspace',
        write_only=True,
        required=False,
    )

    class Meta:
        model = Member
        fields = (
            'id',
            'user_id',
            'workspace_id',
            'user',
            'workspace',
            'role',
            'created_at',
            'updated_at',
        )
        read_only_fields = ('id', 'user', 'workspace', 'created_at', 'updated_at')

    def validate(self, attrs):
        if self.instance is None:
            errors = {}
            if 'user' not in attrs:
                errors['user_id'] = 'Obrigatório ao criar um membro.'
            if 'workspace' not in attrs:
                errors['workspace_id'] = 'Obrigatório ao criar um membro.'
            if errors:
                raise serializers.ValidationError(errors)
        return attrs


class WorkspaceInviteSerializer(serializers.ModelSerializer):
    workspace = _WorkspaceNestedSerializer(read_only=True)
    workspace_id = serializers.PrimaryKeyRelatedField(
        queryset=Workspace.objects.all(),
        source='workspace',
        write_only=True,
    )
    invited_by = _UserNestedSerializer(read_only=True)

    class Meta:
        model = WorkspaceInvite
        fields = (
            'id',
            'email',
            'workspace_id',
            'workspace',
            'invited_by',
            'role',
            'token',
            'accepted',
            'expires_at',
            'created_at',
            'updated_at',
        )
        read_only_fields = (
            'id',
            'workspace',
            'invited_by',
            'token',
            'accepted',
            'expires_at',
            'created_at',
            'updated_at',
        )

    def validate_email(self, value):
        return User.objects.normalize_email(value)

    def validate(self, attrs):
        workspace = attrs.get('workspace')
        email = attrs.get('email')
        if workspace and email:
            if Member.objects.filter(
                workspace=workspace,
                user__email__iexact=email,
            ).exists():
                raise serializers.ValidationError(
                    {'email': 'Este e-mail já é membro ativo deste workspace.'},
                )
        return attrs
