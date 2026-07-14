from django.contrib.auth import get_user_model
from rest_framework import serializers

from omnichannel.ai.exceptions import AIProviderInvalidRequestError
from omnichannel.ai.providers.openai_settings import validate_no_sensitive_settings, validate_openai_settings
from omnichannel.ai.registry import is_provider_supported

from .models import AIProvider, Member, Workspace, WorkspaceAIProviderConfig, WorkspaceInvite

User = get_user_model()
MAX_SYSTEM_PROMPT_LENGTH = 12000


def validate_provider_api_key_value(value: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or not value.strip()
        or value != value.strip()
        or '\n' in value
        or '\r' in value
        or len(value) < 8
    ):
        raise serializers.ValidationError('Credencial invalida.')
    return value


class WorkspaceSerializer(serializers.ModelSerializer):
    class Meta:
        model = Workspace
        fields = (
            'id',
            'name',
            'slug',
            'ai_system_prompt',
            'created_at',
            'updated_at',
        )
        read_only_fields = ('id', 'ai_system_prompt', 'created_at', 'updated_at')


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


class WorkspaceAIProviderConfigSerializer(serializers.ModelSerializer):
    api_key = serializers.CharField(
        write_only=True,
        required=False,
        allow_blank=True,
        trim_whitespace=False,
        style={'input_type': 'password'},
    )
    model_name = serializers.CharField(max_length=128, trim_whitespace=False)
    system_prompt = serializers.CharField(
        required=False,
        allow_blank=True,
        trim_whitespace=False,
    )
    settings = serializers.JSONField(required=False, allow_null=True)
    has_api_key = serializers.SerializerMethodField()
    is_supported = serializers.SerializerMethodField()

    class Meta:
        model = WorkspaceAIProviderConfig
        fields = (
            'id',
            'provider',
            'model_name',
            'system_prompt',
            'settings',
            'is_active',
            'has_api_key',
            'is_supported',
            'created_at',
            'updated_at',
            'api_key',
        )
        read_only_fields = (
            'id',
            'has_api_key',
            'is_supported',
            'created_at',
            'updated_at',
        )

    def get_has_api_key(self, obj: WorkspaceAIProviderConfig) -> bool:
        return bool(obj.api_key)

    def get_is_supported(self, obj: WorkspaceAIProviderConfig) -> bool:
        return is_provider_supported(obj.provider)

    def validate_model_name(self, value: str) -> str:
        if not value or not value.strip():
            raise serializers.ValidationError('Modelo obrigatorio.')
        if value != value.strip() or '\n' in value or '\r' in value:
            raise serializers.ValidationError('Modelo invalido.')
        return value

    def validate_system_prompt(self, value: str) -> str:
        if len(value) > MAX_SYSTEM_PROMPT_LENGTH:
            raise serializers.ValidationError('Prompt excede o tamanho maximo permitido.')
        return value

    def validate_settings(self, value):
        return {} if value is None else value

    def validate(self, attrs):
        self._reject_payload_workspace()
        self._reject_payload_is_active()
        workspace = self._get_workspace()

        provider = attrs.get('provider', self.instance.provider if self.instance else None)
        if self.instance is None:
            self._validate_supported_provider(provider)
            self._validate_unique_provider(workspace, provider)
        else:
            self._validate_instance_workspace(workspace)
            self._validate_immutable_provider(provider)

        if self.instance is not None and 'api_key' in attrs:
            raise serializers.ValidationError(
                'Use o endpoint de substituicao de credencial para alterar a chave.',
            )

        if 'api_key' in attrs:
            attrs['api_key'] = self._validate_api_key_value(attrs['api_key'])

        if self.instance is None and not attrs.get('api_key'):
            raise serializers.ValidationError('Credencial obrigatoria para criar provider.')

        if 'settings' not in attrs and self.instance is None:
            attrs['settings'] = {}
        elif attrs.get('settings') is None:
            attrs['settings'] = {}

        if 'settings' in attrs:
            attrs['settings'] = self._validate_provider_settings(provider, attrs['settings'])

        return attrs

    def create(self, validated_data):
        workspace = self._get_workspace()
        api_key = validated_data.pop('api_key', None)
        if not api_key:
            raise serializers.ValidationError('Credencial obrigatoria para criar provider.')

        return WorkspaceAIProviderConfig.objects.create(
            workspace=workspace,
            api_key=api_key,
            **validated_data,
        )

    def update(self, instance, validated_data):
        workspace = self._get_workspace()
        if instance.workspace_id != workspace.id:
            raise serializers.ValidationError('Workspace invalido para esta configuracao.')

        api_key = validated_data.pop('api_key', serializers.empty)
        if api_key is not serializers.empty:
            instance.api_key = api_key

        for field, value in validated_data.items():
            setattr(instance, field, value)

        instance.save()
        return instance

    def _get_workspace(self) -> Workspace:
        workspace = self.context.get('workspace')
        if workspace is None:
            raise serializers.ValidationError('Workspace context is required.')
        return workspace

    def _reject_payload_workspace(self) -> None:
        initial_data = getattr(self, 'initial_data', {}) or {}
        if 'workspace' in initial_data or 'workspace_id' in initial_data:
            raise serializers.ValidationError('Workspace deve ser definido pelo contexto.')

    def _reject_payload_is_active(self) -> None:
        initial_data = getattr(self, 'initial_data', {}) or {}
        if 'is_active' in initial_data:
            raise serializers.ValidationError(
                'Use os endpoints de ativacao/desativacao para alterar is_active.',
            )

    def _validate_instance_workspace(self, workspace: Workspace) -> None:
        if self.instance.workspace_id != workspace.id:
            raise serializers.ValidationError('Workspace invalido para esta configuracao.')

    def _validate_immutable_provider(self, provider: str) -> None:
        if provider != self.instance.provider:
            raise serializers.ValidationError('Provider nao pode ser alterado.')

    def _validate_supported_provider(self, provider: str) -> None:
        if not is_provider_supported(provider):
            raise serializers.ValidationError('Provider nao suportado para self-service.')

    def _validate_api_key_value(self, value: str) -> str:
        return validate_provider_api_key_value(value)

    def _validate_single_active_provider(self, workspace: Workspace) -> None:
        queryset = WorkspaceAIProviderConfig.objects.filter(
            workspace=workspace,
            is_active=True,
        )
        if self.instance is not None:
            queryset = queryset.exclude(id=self.instance.id)
        if queryset.exists():
            raise serializers.ValidationError('Ja existe um provider ativo para este workspace.')

    def _validate_unique_provider(self, workspace: Workspace, provider: str) -> None:
        if WorkspaceAIProviderConfig.objects.filter(workspace=workspace, provider=provider).exists():
            raise serializers.ValidationError('Provider ja configurado para este workspace.')

    def _validate_provider_settings(self, provider: str, settings: dict) -> dict:
        try:
            validate_no_sensitive_settings(settings)
            if provider == AIProvider.OPENAI:
                return validate_openai_settings(settings)
        except AIProviderInvalidRequestError as exc:
            raise serializers.ValidationError(str(exc)) from exc

        return settings


class WorkspaceAIProviderConnectionTestSerializer(serializers.Serializer):
    api_key = serializers.CharField(
        write_only=True,
        required=False,
        allow_blank=True,
        trim_whitespace=False,
        style={'input_type': 'password'},
    )

    def validate(self, attrs):
        if 'api_key' in attrs:
            attrs['api_key'] = validate_provider_api_key_value(attrs['api_key'])
        return attrs


class WorkspaceAIProviderCredentialReplaceSerializer(serializers.Serializer):
    api_key = serializers.CharField(
        write_only=True,
        required=True,
        allow_blank=False,
        trim_whitespace=False,
        min_length=8,
        style={'input_type': 'password'},
    )

    def validate_api_key(self, value: str) -> str:
        return validate_provider_api_key_value(value)


class WorkspaceAIProviderCredentialRevokeSerializer(serializers.Serializer):
    pass
