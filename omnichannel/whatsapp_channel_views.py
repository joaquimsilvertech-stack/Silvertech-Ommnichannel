from __future__ import annotations

from uuid import UUID

from django.conf import settings
from django.shortcuts import get_object_or_404
from django.utils.cache import patch_vary_headers
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.renderers import JSONRenderer
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.throttling import SimpleRateThrottle
from rest_framework.views import APIView

from omnichannel.models import WhatsAppChannel
from omnichannel.whatsapp_channel_provisioning import (
    SAFE_PROVISIONING_ERROR_MESSAGE,
    WhatsAppChannelProvisioningError,
    provision_whatsapp_channel,
)
from omnichannel.whatsapp_channel_qr_service import (
    WhatsAppChannelQRCodeError,
    get_whatsapp_channel_qr_code,
)
from omnichannel.whatsapp_channel_read_service import (
    get_channel_qr_availability,
    get_channels_qr_availability,
)
from omnichannel.whatsapp_channel_serializers import (
    WhatsAppChannelCreateSerializer,
    WhatsAppChannelPublicSerializer,
    WhatsAppChannelQRCodeSerializer,
    WhatsAppChannelSafeSerializer,
    WhatsAppChannelStatusSerializer,
)
from workspaces.models import Member, Workspace
from workspaces.permissions import IsWorkspaceAdminMember


class _WhatsAppChannelUserScopeThrottle(SimpleRateThrottle):
    def get_rate(self) -> str | None:
        rates = settings.REST_FRAMEWORK.get('DEFAULT_THROTTLE_RATES', {})
        return rates.get(self.scope)

    def get_cache_key(self, request: Request, view: APIView) -> str | None:
        if not request.user or not request.user.is_authenticated:
            return None
        return self.cache_format % {
            'scope': self.scope,
            'ident': str(request.user.pk),
        }


class WhatsAppChannelReadThrottle(_WhatsAppChannelUserScopeThrottle):
    scope = 'whatsapp_channel_read'


class WhatsAppChannelProvisioningThrottle(_WhatsAppChannelUserScopeThrottle):
    scope = 'whatsapp_channel_provisioning'


class WhatsAppChannelQRCodeThrottle(_WhatsAppChannelUserScopeThrottle):
    scope = 'whatsapp_channel_qr'

    def get_cache_key(self, request: Request, view: APIView) -> str | None:
        if not request.user or not request.user.is_authenticated:
            return None
        workspace_id = str(view.kwargs.get('workspace_id', ''))
        channel_id = str(view.kwargs.get('channel_id', ''))
        ident = f'{request.user.pk}:{workspace_id}:{channel_id}'
        return self.cache_format % {'scope': self.scope, 'ident': ident}


class _WorkspaceWhatsAppChannelAccessMixin:
    permission_classes = [IsAuthenticated, IsWorkspaceAdminMember]

    def finalize_response(self, request, response, *args, **kwargs):
        finalized = super().finalize_response(request, response, *args, **kwargs)
        return _with_private_no_store(finalized)

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
    def _get_channel(*, workspace: Workspace, channel_id: UUID) -> WhatsAppChannel:
        return get_object_or_404(
            WhatsAppChannel.objects.select_related('workspace'),
            id=channel_id,
            workspace=workspace,
        )


class WorkspaceWhatsAppChannelCollectionView(
    _WorkspaceWhatsAppChannelAccessMixin,
    APIView,
):
    throttle_scope = 'whatsapp_channel_provisioning'
    provisioning_throttle_scope = 'whatsapp_channel_provisioning'
    read_throttle_scope = 'whatsapp_channel_read'
    http_method_names = ['get', 'post', 'head', 'options']

    def get_throttles(self):
        self.throttle_scope = (
            self.provisioning_throttle_scope
            if self.request.method == 'POST'
            else self.read_throttle_scope
        )
        throttle_class = (
            WhatsAppChannelProvisioningThrottle
            if self.request.method == 'POST'
            else WhatsAppChannelReadThrottle
        )
        return [throttle_class()]

    def get(self, request: Request, workspace_id: str) -> Response:
        workspace = self._get_workspace(workspace_id)
        channels = list(
            WhatsAppChannel.objects.filter(workspace=workspace).order_by('name', 'id'),
        )
        availability = get_channels_qr_availability(channels)
        serializer = WhatsAppChannelPublicSerializer(
            channels,
            many=True,
            context={'qr_availability': availability},
        )
        return _with_private_no_store(Response(serializer.data))

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
            return _with_private_no_store(Response(payload, status=exc.http_status))

        output_serializer = WhatsAppChannelSafeSerializer(result.channel)
        return _with_private_no_store(
            Response(
                output_serializer.data,
                status=(
                    status.HTTP_201_CREATED
                    if result.created
                    else status.HTTP_200_OK
                ),
            ),
        )

    def head(self, request: Request, workspace_id: str) -> Response:
        self._get_workspace(workspace_id)
        return _with_private_no_store(Response(status=status.HTTP_200_OK))

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


class WorkspaceWhatsAppChannelDetailView(
    _WorkspaceWhatsAppChannelAccessMixin,
    APIView,
):
    throttle_scope = 'whatsapp_channel_read'
    throttle_classes = [WhatsAppChannelReadThrottle]
    http_method_names = ['get', 'head', 'options']

    def get(self, request: Request, workspace_id: str, channel_id: UUID) -> Response:
        workspace = self._get_workspace(workspace_id)
        channel = self._get_channel(workspace=workspace, channel_id=channel_id)
        availability = {channel.id: get_channel_qr_availability(channel)}
        serializer = WhatsAppChannelPublicSerializer(
            channel,
            context={'qr_availability': availability},
        )
        return _with_private_no_store(Response(serializer.data))


class WorkspaceWhatsAppChannelStatusView(
    _WorkspaceWhatsAppChannelAccessMixin,
    APIView,
):
    throttle_scope = 'whatsapp_channel_read'
    throttle_classes = [WhatsAppChannelReadThrottle]
    http_method_names = ['get', 'head', 'options']

    def get(self, request: Request, workspace_id: str, channel_id: UUID) -> Response:
        workspace = self._get_workspace(workspace_id)
        channel = self._get_channel(workspace=workspace, channel_id=channel_id)
        availability = {channel.id: get_channel_qr_availability(channel)}
        serializer = WhatsAppChannelStatusSerializer(
            channel,
            context={'qr_availability': availability},
        )
        return _with_private_no_store(Response(serializer.data))


class WorkspaceWhatsAppChannelQRCodeView(
    _WorkspaceWhatsAppChannelAccessMixin,
    APIView,
):
    renderer_classes = [JSONRenderer]
    throttle_classes = [WhatsAppChannelQRCodeThrottle]
    http_method_names = ['get', 'options']

    def finalize_response(self, request, response, *args, **kwargs):
        finalized = super().finalize_response(request, response, *args, **kwargs)
        return _with_qr_no_store(finalized)

    def get(self, request: Request, workspace_id: str, channel_id: UUID) -> Response:
        workspace = self._get_workspace(workspace_id)
        channel = self._get_channel(workspace=workspace, channel_id=channel_id)
        try:
            result = get_whatsapp_channel_qr_code(channel=channel)
        except WhatsAppChannelQRCodeError as exc:
            return _with_qr_no_store(
                Response(
                    {'detail': exc.detail, 'error_code': exc.error_code},
                    status=exc.http_status,
                ),
            )
        serializer = WhatsAppChannelQRCodeSerializer(result)
        return _with_qr_no_store(Response(serializer.data))


def _with_private_no_store(response: Response) -> Response:
    response['Cache-Control'] = 'private, no-store'
    patch_vary_headers(response, ('Authorization',))
    return response


def _with_qr_no_store(response: Response) -> Response:
    response['Cache-Control'] = 'no-store, private, max-age=0'
    response['Pragma'] = 'no-cache'
    response['Expires'] = '0'
    response['X-Content-Type-Options'] = 'nosniff'
    patch_vary_headers(response, ('Authorization',))
    return response


# Compatibilidade com imports e testes da Parte 20.
WorkspaceWhatsAppChannelProvisioningView = WorkspaceWhatsAppChannelCollectionView
