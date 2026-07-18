from __future__ import annotations

from uuid import UUID

from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from omnichannel.models import WhatsAppChannel
from omnichannel.whatsapp_channel_provisioning import (
    SAFE_PROVISIONING_ERROR_MESSAGE,
    WhatsAppChannelProvisioningError,
    provision_whatsapp_channel,
)
from omnichannel.whatsapp_channel_serializers import (
    WhatsAppChannelCreateSerializer,
    WhatsAppChannelSafeSerializer,
)
from workspaces.models import Member, Workspace
from workspaces.permissions import IsWorkspaceAdminMember


class WorkspaceWhatsAppChannelProvisioningView(APIView):
    permission_classes = [IsAuthenticated, IsWorkspaceAdminMember]
    throttle_scope = 'whatsapp_channel_provisioning'
    http_method_names = ['post', 'head', 'options']

    def post(self, request: Request, workspace_id: str) -> Response:
        workspace = self._get_workspace(workspace_id)
        input_serializer = WhatsAppChannelCreateSerializer(data=request.data)
        input_serializer.is_valid(raise_exception=True)

        try:
            result = provision_whatsapp_channel(
                workspace=workspace,
                channel_name=input_serializer.validated_data['name'],
            )
        except WhatsAppChannelProvisioningError as exc:
            payload: dict[str, object] = {
                'detail': SAFE_PROVISIONING_ERROR_MESSAGE,
                'error_code': exc.error_code,
            }
            channel = self._safe_error_channel(
                workspace=workspace,
                channel_id=exc.channel_id,
            )
            if channel is not None:
                payload['channel'] = WhatsAppChannelSafeSerializer(channel).data
            return Response(payload, status=exc.http_status)

        output_serializer = WhatsAppChannelSafeSerializer(result.channel)
        return Response(
            output_serializer.data,
            status=(
                status.HTTP_201_CREATED
                if result.created
                else status.HTTP_200_OK
            ),
        )

    def head(self, request: Request, workspace_id: str) -> Response:
        self._get_workspace(workspace_id)
        return Response(status=status.HTTP_200_OK)

    def _get_workspace(self, workspace_id: str) -> Workspace:
        if self.request.user.is_superuser:
            return get_object_or_404(Workspace, id=workspace_id)
        return get_object_or_404(
            Workspace,
            id=workspace_id,
            memberships__user=self.request.user,
            memberships__role__in={Member.Role.OWNER, Member.Role.ADMIN},
        )

    @staticmethod
    def _safe_error_channel(
        *,
        workspace: Workspace,
        channel_id: UUID | None,
    ) -> WhatsAppChannel | None:
        if channel_id is None:
            return None
        return WhatsAppChannel.objects.filter(
            id=channel_id,
            workspace=workspace,
        ).first()
