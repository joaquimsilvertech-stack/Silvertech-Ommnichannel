import logging
import uuid
from datetime import timedelta

from django.db import IntegrityError
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import mixins, serializers, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from crm.mixins import WorkspaceScopedQuerysetMixin
from core.sanitization import mask_email

from .models import Member, Workspace, WorkspaceAIProviderConfig, WorkspaceInvite
from .permissions import IsWorkspaceAdminMember
from .serializers import (
    MemberSerializer,
    WorkspaceAIProviderConfigSerializer,
    WorkspaceInviteSerializer,
    WorkspaceSerializer,
)

logger = logging.getLogger(__name__)


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


class WorkspaceInviteViewSet(viewsets.ModelViewSet):
    """POST /api/workspaces/invites/ — cria convite com token e expiração."""

    queryset = WorkspaceInvite.objects.select_related('workspace', 'invited_by').all()
    serializer_class = WorkspaceInviteSerializer
    permission_classes = [IsAuthenticated]
    http_method_names = ['get', 'post', 'head', 'options']

    def perform_create(self, serializer):
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
