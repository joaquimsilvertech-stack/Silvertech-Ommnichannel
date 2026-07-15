import logging
import uuid
from datetime import timedelta

from django.db import IntegrityError
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import mixins, serializers, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from crm.mixins import WorkspaceScopedQuerysetMixin
from core.sanitization import mask_email
from omnichannel.ai.connection_test import (
    get_connection_test_http_status,
    test_ai_provider_connection,
)
from omnichannel.ai.registry import is_provider_supported
from omnichannel.models import AIObservabilityEvent
from omnichannel.observability import record_ai_observability_event_safe

from .models import Member, Workspace, WorkspaceAIProviderConfig, WorkspaceInvite
from .permissions import IsWorkspaceAdminMember
from .serializers import (
    MemberSerializer,
    WorkspaceAIProviderConnectionTestSerializer,
    WorkspaceAIProviderCredentialReplaceSerializer,
    WorkspaceAIProviderCredentialRevokeSerializer,
    WorkspaceAIProviderConfigSerializer,
    WorkspaceInviteSerializer,
    WorkspaceSerializer,
)
from .services import (
    AIProviderActivationError,
    AIProviderCredentialError,
    activate_ai_provider_config,
    deactivate_ai_provider_config,
    replace_ai_provider_credentials,
    revoke_ai_provider_credentials,
)

logger = logging.getLogger(__name__)
AI_PROVIDER_CREDENTIAL_ERROR_STATUS = {
    'UNSUPPORTED_PROVIDER': 400,
    'MISSING_API_KEY': 400,
    'INVALID_CREDENTIALS': 400,
    'RATE_LIMITED': 429,
    'PROVIDER_TIMEOUT': 504,
    'PROVIDER_UNAVAILABLE': 503,
    'PROVIDER_ERROR': 502,
}


def _admin_workspace_ids_for(user):
    if user.is_superuser:
        return Workspace.objects.values_list('id', flat=True)

    return Member.objects.filter(
        user=user,
        role__in={Member.Role.OWNER, Member.Role.ADMIN},
    ).values_list('workspace_id', flat=True)


def _ensure_workspace_admin(user, workspace: Workspace) -> None:
    if user.is_superuser:
        return
    if not Member.objects.filter(
        user=user,
        workspace=workspace,
        role__in={Member.Role.OWNER, Member.Role.ADMIN},
    ).exists():
        raise PermissionDenied('Sem permissao administrativa para este workspace.')


def send_invite_email(invite: WorkspaceInvite) -> None:
    """Mock de envio — Sprint 4 integrará Resend/SMTP."""
    logger.info(
        'Convite de workspace criado',
        extra={
            'workspace_id': str(invite.workspace_id),
            'invite_id': str(invite.id),
            'email': mask_email(invite.email),
            'role': invite.role,
            'expires_at': invite.expires_at.isoformat(),
        },
    )


class WorkspaceViewSet(WorkspaceScopedQuerysetMixin, viewsets.ModelViewSet):
    queryset = Workspace.objects.all()
    serializer_class = WorkspaceSerializer
    permission_classes = [IsAuthenticated]
    workspace_lookup = 'id'

    @action(detail=True, methods=['get'])
    def members(self, request, pk=None):
        """Lista todos os membros do workspace (Card #009-N)."""
        workspace = self.get_object()
        memberships = (
            Member.objects.filter(workspace=workspace)
            .select_related('user', 'workspace')
            .order_by('user__email')
        )
        serializer = MemberSerializer(memberships, many=True)
        return Response(serializer.data)


class MemberViewSet(viewsets.ModelViewSet):
    queryset = Member.objects.select_related('user', 'workspace').all()
    serializer_class = MemberSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return self.queryset.filter(workspace_id__in=_admin_workspace_ids_for(self.request.user))

    def perform_create(self, serializer):
        workspace = serializer.validated_data['workspace']
        _ensure_workspace_admin(self.request.user, workspace)
        serializer.save()

    def perform_update(self, serializer):
        workspace = serializer.validated_data.get('workspace', serializer.instance.workspace)
        _ensure_workspace_admin(self.request.user, workspace)
        serializer.save()

    def perform_destroy(self, instance):
        _ensure_workspace_admin(self.request.user, instance.workspace)
        instance.delete()


class WorkspaceInviteViewSet(viewsets.ModelViewSet):
    """POST /api/workspaces/invites/ — cria convite com token e expiração."""

    queryset = WorkspaceInvite.objects.select_related('workspace', 'invited_by').all()
    serializer_class = WorkspaceInviteSerializer
    permission_classes = [IsAuthenticated]
    http_method_names = ['get', 'post', 'head', 'options']

    def get_queryset(self):
        return self.queryset.filter(workspace_id__in=_admin_workspace_ids_for(self.request.user))

    def perform_create(self, serializer):
        workspace = serializer.validated_data['workspace']
        _ensure_workspace_admin(self.request.user, workspace)
        invite = serializer.save(
            invited_by=self.request.user,
            token=uuid.uuid4(),
            expires_at=timezone.now() + timedelta(days=7),
        )
        send_invite_email(invite)


class WorkspaceAIProviderConfigViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    mixins.UpdateModelMixin,
    viewsets.GenericViewSet,
):
    serializer_class = WorkspaceAIProviderConfigSerializer
    permission_classes = [IsAuthenticated, IsWorkspaceAdminMember]
    http_method_names = ['get', 'post', 'put', 'patch', 'head', 'options']
    test_connection_throttle_scope = 'ai_provider_test_connection'
    activation_throttle_scope = 'ai_provider_activation'

    def get_throttles(self):
        if getattr(self, 'action', None) == 'test_connection':
            self.throttle_scope = self.test_connection_throttle_scope
        elif getattr(self, 'action', None) == 'activate_provider':
            self.throttle_scope = self.activation_throttle_scope
        return super().get_throttles()

    def get_workspace(self) -> Workspace:
        if not hasattr(self, '_workspace'):
            workspace_id = self.kwargs.get('workspace_id')
            if self.request.user.is_superuser:
                self._workspace = get_object_or_404(Workspace, id=workspace_id)
            else:
                self._workspace = get_object_or_404(
                    Workspace,
                    id=workspace_id,
                    memberships__user=self.request.user,
                    memberships__role__in={Member.Role.OWNER, Member.Role.ADMIN},
                )
        return self._workspace

    def get_queryset(self):
        workspace = self.get_workspace()
        return WorkspaceAIProviderConfig.objects.select_related('workspace').filter(
            workspace=workspace,
        )

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context['workspace'] = self.get_workspace()
        return context

    def perform_create(self, serializer):
        try:
            serializer.save()
        except IntegrityError as exc:
            raise serializers.ValidationError(
                'Configuracao de provider invalida para este workspace.',
            ) from exc

    def perform_update(self, serializer):
        try:
            serializer.save()
        except IntegrityError as exc:
            raise serializers.ValidationError(
                'Configuracao de provider invalida para este workspace.',
            ) from exc

    def test_connection(self, request, *args, **kwargs):
        provider_config = self.get_object()
        input_serializer = WorkspaceAIProviderConnectionTestSerializer(data=request.data)
        input_serializer.is_valid(raise_exception=True)

        result = test_ai_provider_connection(
            provider_config=provider_config,
            api_key_override=input_serializer.validated_data.get('api_key'),
        )
        self._record_ai_admin_observability_event(
            provider_config=provider_config,
            event_type=(
                AIObservabilityEvent.EventType.PROVIDER_TEST_SUCCESS
                if result.success
                else AIObservabilityEvent.EventType.PROVIDER_TEST_FAILED
            ),
            status=(
                AIObservabilityEvent.Status.SUCCESS
                if result.success
                else AIObservabilityEvent.Status.FAILED
            ),
            error_code=result.error_code or '',
            metadata={'action': 'test_connection'},
        )
        payload = {
            'success': result.success,
            'provider': result.provider,
            'model_name': result.model_name,
            'message': result.message,
        }
        if result.error_code:
            payload['error_code'] = result.error_code

        return Response(
            payload,
            status=get_connection_test_http_status(result),
        )

    def activate_provider(self, request, *args, **kwargs):
        provider_config = self.get_object()
        workspace = self.get_workspace()

        if 'api_key' in request.data:
            return Response(
                {
                    'success': False,
                    'provider': provider_config.provider,
                    'model_name': provider_config.model_name,
                    'message': 'Use a credencial salva para ativar o provider.',
                    'error_code': 'TEMPORARY_API_KEY_NOT_ALLOWED',
                },
                status=400,
            )

        if provider_config.is_active:
            return Response(self._activation_payload(provider_config, is_active=True))

        if not is_provider_supported(provider_config.provider):
            return Response(
                {
                    'success': False,
                    'provider': provider_config.provider,
                    'model_name': provider_config.model_name,
                    'message': 'Este provedor ainda nao possui adapter ativo.',
                    'error_code': 'UNSUPPORTED_PROVIDER',
                },
                status=400,
            )

        if not provider_config.api_key:
            return Response(
                {
                    'success': False,
                    'provider': provider_config.provider,
                    'model_name': provider_config.model_name,
                    'message': 'Credencial salva obrigatoria para ativar provider.',
                    'error_code': 'MISSING_API_KEY',
                },
                status=400,
            )

        result = test_ai_provider_connection(provider_config=provider_config)
        self._record_ai_admin_observability_event(
            provider_config=provider_config,
            event_type=(
                AIObservabilityEvent.EventType.PROVIDER_TEST_SUCCESS
                if result.success
                else AIObservabilityEvent.EventType.PROVIDER_TEST_FAILED
            ),
            status=(
                AIObservabilityEvent.Status.SUCCESS
                if result.success
                else AIObservabilityEvent.Status.FAILED
            ),
            error_code=result.error_code or '',
            metadata={'action': 'activate_provider'},
        )
        if not result.success:
            payload = {
                'success': False,
                'provider': result.provider,
                'model_name': result.model_name,
                'message': result.message,
            }
            if result.error_code:
                payload['error_code'] = result.error_code
            return Response(payload, status=get_connection_test_http_status(result))

        try:
            provider_config = activate_ai_provider_config(
                workspace=workspace,
                provider_config=provider_config,
            )
        except AIProviderActivationError as exc:
            raise serializers.ValidationError(str(exc)) from exc

        self._record_ai_admin_observability_event(
            provider_config=provider_config,
            event_type=AIObservabilityEvent.EventType.PROVIDER_ACTIVATED,
            status=AIObservabilityEvent.Status.SUCCESS,
            metadata={'action': 'activate_provider'},
        )
        return Response(self._activation_payload(provider_config, is_active=True))

    def deactivate_provider(self, request, *args, **kwargs):
        provider_config = self.get_object()
        workspace = self.get_workspace()

        try:
            provider_config = deactivate_ai_provider_config(
                workspace=workspace,
                provider_config=provider_config,
            )
        except AIProviderActivationError as exc:
            raise serializers.ValidationError(str(exc)) from exc

        self._record_ai_admin_observability_event(
            provider_config=provider_config,
            event_type=AIObservabilityEvent.EventType.PROVIDER_DEACTIVATED,
            status=AIObservabilityEvent.Status.SUCCESS,
            metadata={'action': 'deactivate_provider'},
        )
        return Response(self._activation_payload(provider_config, is_active=False))

    def replace_credentials(self, request, *args, **kwargs):
        provider_config = self.get_object()
        workspace = self.get_workspace()
        input_serializer = WorkspaceAIProviderCredentialReplaceSerializer(data=request.data)
        if not input_serializer.is_valid():
            error_payload = self._replace_validation_error_payload(provider_config, request.data)
            self._record_ai_admin_observability_event(
                provider_config=provider_config,
                event_type=AIObservabilityEvent.EventType.CREDENTIAL_REPLACE_FAILED,
                status=AIObservabilityEvent.Status.FAILED,
                error_code=error_payload['error_code'],
                metadata={'action': 'replace_credentials'},
            )
            return Response(
                error_payload,
                status=400,
            )

        try:
            provider_config = replace_ai_provider_credentials(
                workspace=workspace,
                provider_config=provider_config,
                api_key=input_serializer.validated_data['api_key'],
            )
        except AIProviderCredentialError as exc:
            self._record_ai_admin_observability_event(
                provider_config=provider_config,
                event_type=AIObservabilityEvent.EventType.CREDENTIAL_REPLACE_FAILED,
                status=AIObservabilityEvent.Status.FAILED,
                error_code=self._credential_error_code(exc),
                metadata={'action': 'replace_credentials'},
            )
            return Response(
                self._credential_error_payload(provider_config, exc),
                status=self._credential_error_status(exc),
            )

        self._record_ai_admin_observability_event(
            provider_config=provider_config,
            event_type=AIObservabilityEvent.EventType.CREDENTIAL_REPLACED,
            status=AIObservabilityEvent.Status.SUCCESS,
            metadata={'action': 'replace_credentials'},
        )
        serializer = self.get_serializer(provider_config)
        return Response(serializer.data)

    def revoke_credentials(self, request, *args, **kwargs):
        provider_config = self.get_object()
        workspace = self.get_workspace()
        input_serializer = WorkspaceAIProviderCredentialRevokeSerializer(data=request.data)
        input_serializer.is_valid(raise_exception=True)

        try:
            provider_config = revoke_ai_provider_credentials(
                workspace=workspace,
                provider_config=provider_config,
            )
        except AIProviderCredentialError as exc:
            return Response(
                self._credential_error_payload(provider_config, exc),
                status=self._credential_error_status(exc),
            )

        self._record_ai_admin_observability_event(
            provider_config=provider_config,
            event_type=AIObservabilityEvent.EventType.CREDENTIAL_REVOKED,
            status=AIObservabilityEvent.Status.SUCCESS,
            metadata={'action': 'revoke_credentials'},
        )
        serializer = self.get_serializer(provider_config)
        return Response(serializer.data)

    def _record_ai_admin_observability_event(
        self,
        *,
        provider_config: WorkspaceAIProviderConfig,
        event_type: str,
        status: str,
        error_code: str = '',
        metadata: dict | None = None,
    ) -> None:
        record_ai_observability_event_safe(
            workspace=provider_config.workspace,
            provider_config=provider_config,
            event_type=event_type,
            status=status,
            provider=provider_config.provider,
            model_name=provider_config.model_name,
            error_code=error_code,
            metadata={'source': 'ai_provider_admin', **(metadata or {})},
        )

    def _activation_payload(
        self,
        provider_config: WorkspaceAIProviderConfig,
        *,
        is_active: bool,
    ) -> dict:
        return {
            'success': True,
            'id': str(provider_config.id),
            'provider': provider_config.provider,
            'model_name': provider_config.model_name,
            'is_active': is_active,
            'message': (
                'Provider ativado com sucesso.'
                if is_active
                else 'Provider desativado com sucesso.'
            ),
        }

    def _credential_error_status(self, exc: AIProviderCredentialError) -> int:
        error_code = self._credential_error_code(exc)
        return AI_PROVIDER_CREDENTIAL_ERROR_STATUS[error_code]

    def _credential_error_code(self, exc: AIProviderCredentialError) -> str:
        error_code = getattr(exc, 'error_code', None)
        if error_code in AI_PROVIDER_CREDENTIAL_ERROR_STATUS:
            return error_code
        return 'PROVIDER_ERROR'

    def _credential_error_payload(
        self,
        provider_config: WorkspaceAIProviderConfig,
        exc: AIProviderCredentialError,
    ) -> dict:
        return {
            'success': False,
            'provider': provider_config.provider,
            'model_name': provider_config.model_name,
            'message': str(exc),
            'error_code': self._credential_error_code(exc),
        }

    def _replace_validation_error_payload(
        self,
        provider_config: WorkspaceAIProviderConfig,
        payload: dict,
    ) -> dict:
        raw_api_key = payload.get('api_key') if isinstance(payload, dict) else None
        if not isinstance(raw_api_key, str) or not raw_api_key.strip():
            return {
                'success': False,
                'provider': provider_config.provider,
                'model_name': provider_config.model_name,
                'message': 'Informe uma chave antes de continuar.',
                'error_code': 'MISSING_API_KEY',
            }

        return {
            'success': False,
            'provider': provider_config.provider,
            'model_name': provider_config.model_name,
            'message': 'Credencial invalida. Verifique a chave informada.',
            'error_code': 'INVALID_CREDENTIALS',
        }
