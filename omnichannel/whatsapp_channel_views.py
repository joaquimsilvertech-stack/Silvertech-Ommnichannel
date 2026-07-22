from __future__ import annotations

from uuid import UUID

from django.conf import settings
from django.shortcuts import get_object_or_404
from django.utils.cache import patch_vary_headers
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.renderers import JSONRenderer
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.throttling import SimpleRateThrottle
from rest_framework.views import APIView

from omnichannel.channel_authorization import (
    ChannelCapability,
    HasChannelCapability,
    resolve_workspace_for_capability,
)
from omnichannel.models import WhatsAppChannel
from omnichannel.whatsapp_channel_management import (
    SAFE_MANAGEMENT_ERROR_MESSAGE,
    WhatsAppChannelManagementError,
    disconnect_whatsapp_channel,
    remove_whatsapp_channel,
    restart_whatsapp_channel,
)
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
from workspaces.models import Workspace


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


class _WhatsAppChannelScopedResourceThrottle(_WhatsAppChannelUserScopeThrottle):
    """Throttle por usuario + workspace + canal (para acoes sobre um canal)."""

    def get_cache_key(self, request: Request, view: APIView) -> str | None:
        if not request.user or not request.user.is_authenticated:
            return None
        workspace_id = str(view.kwargs.get('workspace_id', ''))
        channel_id = str(view.kwargs.get('channel_id', ''))
        ident = f'{request.user.pk}:{workspace_id}:{channel_id}'
        return self.cache_format % {'scope': self.scope, 'ident': ident}


class WhatsAppChannelQRCodeThrottle(_WhatsAppChannelScopedResourceThrottle):
    scope = 'whatsapp_channel_qr'


class WhatsAppChannelManagementThrottle(_WhatsAppChannelScopedResourceThrottle):
    scope = 'whatsapp_channel_management'


class _WorkspaceWhatsAppChannelAccessMixin:
    permission_classes = [IsAuthenticated, HasChannelCapability]
    required_channel_capability = ChannelCapability.VIEW

    def get_required_channel_capability(self, request: Request) -> ChannelCapability:
        return self.required_channel_capability

    def finalize_response(self, request, response, *args, **kwargs):
        finalized = super().finalize_response(request, response, *args, **kwargs)
        return _with_private_no_store(finalized)

    def _get_workspace(
        self,
        workspace_id: str,
        capability: ChannelCapability = ChannelCapability.VIEW,
    ) -> Workspace:
        return resolve_workspace_for_capability(self.request, workspace_id, capability)

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

    def get_required_channel_capability(self, request: Request) -> ChannelCapability:
        # POST provisiona (CONNECT); demais metodos apenas leem (VIEW). Ambos
        # exigem {OWNER, ADMIN}, entao o comportamento e identico ao anterior.
        if request.method == 'POST':
            return ChannelCapability.CONNECT
        return ChannelCapability.VIEW

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
    http_method_names = ['get', 'delete', 'head', 'options']

    def get_required_channel_capability(self, request: Request) -> ChannelCapability:
        # GET le (VIEW={OWNER,ADMIN}); DELETE remove (REMOVE=OWNER-only).
        if request.method == 'DELETE':
            return ChannelCapability.REMOVE
        return ChannelCapability.VIEW

    def get_throttles(self):
        if self.request.method == 'DELETE':
            return [WhatsAppChannelManagementThrottle()]
        return [WhatsAppChannelReadThrottle()]

    def get(self, request: Request, workspace_id: str, channel_id: UUID) -> Response:
        workspace = self._get_workspace(workspace_id)
        channel = self._get_channel(workspace=workspace, channel_id=channel_id)
        availability = {channel.id: get_channel_qr_availability(channel)}
        serializer = WhatsAppChannelPublicSerializer(
            channel,
            context={'qr_availability': availability},
        )
        return _with_private_no_store(Response(serializer.data))

    @extend_schema(
        summary='Remover canal WhatsApp (OWNER-only)',
        request=None,
        responses={
            204: OpenApiResponse(description='Canal removido; conversas viram legado.'),
            403: OpenApiResponse(description='Sem capability REMOVE (OWNER-only).'),
            404: OpenApiResponse(description='Canal inexistente ou de outro tenant.'),
        },
    )
    def delete(self, request: Request, workspace_id: str, channel_id: UUID) -> Response:
        # remove_whatsapp_channel e best-effort: a limpeza remota falha de forma
        # logada e a remocao local sempre prossegue, entao nao ha erro seguro a
        # tratar aqui — o retorno e sempre 204.
        workspace = self._get_workspace(workspace_id, ChannelCapability.REMOVE)
        channel = self._get_channel(workspace=workspace, channel_id=channel_id)
        remove_whatsapp_channel(channel=channel)
        return _with_private_no_store(Response(status=status.HTTP_204_NO_CONTENT))


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


class WorkspaceWhatsAppChannelRestartView(
    _WorkspaceWhatsAppChannelAccessMixin,
    APIView,
):
    required_channel_capability = ChannelCapability.RESTART
    throttle_classes = [WhatsAppChannelManagementThrottle]
    http_method_names = ['post', 'options']

    @extend_schema(
        summary='Reiniciar canal WhatsApp',
        request=None,
        responses={
            200: WhatsAppChannelStatusSerializer,
            403: OpenApiResponse(description='Sem capability RESTART.'),
            404: OpenApiResponse(description='Canal inexistente ou de outro tenant.'),
            409: OpenApiResponse(description='Estado incompativel (provisioning/deleting).'),
            502: OpenApiResponse(description='Falha segura na Evolution (error_code sanitizado).'),
        },
    )
    def post(self, request: Request, workspace_id: str, channel_id: UUID) -> Response:
        workspace = self._get_workspace(workspace_id, ChannelCapability.RESTART)
        channel = self._get_channel(workspace=workspace, channel_id=channel_id)
        try:
            channel = restart_whatsapp_channel(channel=channel)
        except WhatsAppChannelManagementError as exc:
            return _with_private_no_store(_safe_management_error_response(exc))
        return _with_private_no_store(_channel_status_response(channel))


class WorkspaceWhatsAppChannelDisconnectView(
    _WorkspaceWhatsAppChannelAccessMixin,
    APIView,
):
    required_channel_capability = ChannelCapability.DISCONNECT
    throttle_classes = [WhatsAppChannelManagementThrottle]
    http_method_names = ['post', 'options']

    @extend_schema(
        summary='Desconectar canal WhatsApp (idempotente)',
        request=None,
        responses={
            200: WhatsAppChannelStatusSerializer,
            403: OpenApiResponse(description='Sem capability DISCONNECT.'),
            404: OpenApiResponse(description='Canal inexistente ou de outro tenant.'),
            409: OpenApiResponse(description='Estado incompativel (provisioning/deleting).'),
            502: OpenApiResponse(description='Falha segura na Evolution (error_code sanitizado).'),
        },
    )
    def post(self, request: Request, workspace_id: str, channel_id: UUID) -> Response:
        workspace = self._get_workspace(workspace_id, ChannelCapability.DISCONNECT)
        channel = self._get_channel(workspace=workspace, channel_id=channel_id)
        try:
            channel = disconnect_whatsapp_channel(channel=channel)
        except WhatsAppChannelManagementError as exc:
            return _with_private_no_store(_safe_management_error_response(exc))
        return _with_private_no_store(_channel_status_response(channel))


def _channel_status_response(channel: WhatsAppChannel) -> Response:
    availability = {channel.id: get_channel_qr_availability(channel)}
    serializer = WhatsAppChannelStatusSerializer(
        channel,
        context={'qr_availability': availability},
    )
    return Response(serializer.data)


def _safe_management_error_response(exc: WhatsAppChannelManagementError) -> Response:
    return Response(
        {'detail': SAFE_MANAGEMENT_ERROR_MESSAGE, 'error_code': exc.error_code},
        status=exc.http_status,
    )


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
