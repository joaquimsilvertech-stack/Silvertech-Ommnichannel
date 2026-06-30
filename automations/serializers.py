from __future__ import annotations

from rest_framework import serializers

from workspaces.models import Member, Workspace

from .models import Flow


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


class FlowSerializer(serializers.ModelSerializer):
    workspace = _WorkspaceNestedSerializer(read_only=True)
    workspace_id = serializers.PrimaryKeyRelatedField(
        queryset=Workspace.objects.all(),
        source='workspace',
        write_only=True,
        required=False,
    )

    class Meta:
        model = Flow
        fields = (
            'id',
            'workspace_id',
            'workspace',
            'name',
            'trigger',
            'nodes',
            'is_active',
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

    def validate_trigger(self, value):
        if not isinstance(value, dict):
            raise serializers.ValidationError('O gatilho deve ser um objeto JSON.')
        trigger_type = value.get('type')
        if trigger_type is not None and not isinstance(trigger_type, str):
            raise serializers.ValidationError('trigger.type deve ser uma string.')
        return value

    def validate_nodes(self, value):
        if not isinstance(value, list):
            raise serializers.ValidationError('Os nos do flow devem ser uma lista JSON.')
        for index, node in enumerate(value):
            if not isinstance(node, dict):
                raise serializers.ValidationError(
                    f'O node na posicao {index} deve ser um objeto JSON.',
                )
        return value

    def validate(self, attrs):
        if self.instance is None and 'workspace' not in attrs:
            raise serializers.ValidationError(
                {'workspace_id': 'O workspace e obrigatorio na criacao.'},
            )
        return attrs
