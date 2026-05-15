import uuid
from datetime import timedelta

from django.utils import timezone
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .models import Member, Workspace, WorkspaceInvite
from .serializers import (
    MemberSerializer,
    WorkspaceInviteSerializer,
    WorkspaceSerializer,
)


def send_invite_email(invite: WorkspaceInvite) -> None:
    """Mock de envio — Sprint 4 integrará Resend/SMTP."""
    print(
        f'[MOCK EMAIL] Convite para {invite.email} | '
        f'workspace={invite.workspace.name} | '
        f'token={invite.token} | '
        f'expira em {invite.expires_at.isoformat()}',
    )


class WorkspaceViewSet(viewsets.ModelViewSet):
    queryset = Workspace.objects.all()
    serializer_class = WorkspaceSerializer
    permission_classes = [IsAuthenticated]

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
