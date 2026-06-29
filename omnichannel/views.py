import logging

import requests
from django.http import HttpResponse
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.filters import SearchFilter
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from crm.mixins import WorkspaceScopedQuerysetMixin
from crm.pagination import CRMCursorPagination

from .models import Conversation, Message
from .serializers import (
    ConversationSerializer,
    MessageCreateSerializer,
    MessageSerializer,
)
from .services import send_whatsapp_message
from .tasks import process_whatsapp_webhook_task

logger = logging.getLogger(__name__)


class WebhookAPIView(APIView):
    """
    Webhook publico para provedores externos (Evolution API).

    GET: health-check simples.
    POST: enfileira upsert WhatsApp no Celery e responde 200 OK imediato (Card #027).
    """

    permission_classes = [AllowAny]

    def get(self, request: Request, channel_name: str) -> HttpResponse:
        """Health-check usado pela Evolution API."""
        return HttpResponse(status=200)

    def post(self, request: Request, channel_name: str) -> Response:
        """Ack imediato 200 OK."""
        logger.info('Webhook [%s] payload: %s', channel_name, request.data)

        workspace_id = request.query_params.get('workspace')
        if workspace_id and channel_name == 'whatsapp':
            try:
                process_whatsapp_webhook_task.delay(request.data, workspace_id)
            except Exception as exc:
                logger.error(
                    'Erro ao enfileirar webhook WhatsApp (workspace=%s): %s',
                    workspace_id,
                    exc,
                    exc_info=True,
                )

        return Response({'status': 'received'}, status=status.HTTP_200_OK)


class ConversationViewSet(WorkspaceScopedQuerysetMixin, viewsets.ModelViewSet):
    queryset = Conversation.objects.all()
    serializer_class = ConversationSerializer
    permission_classes = [IsAuthenticated]
    pagination_class = CRMCursorPagination
    filter_backends = [DjangoFilterBackend, SearchFilter]
    filterset_fields = ['status', 'channel', 'workspace']
    search_fields = ['contact__name', 'contact__phone']
    workspace_lookup = 'workspace'

    def get_queryset(self):
        queryset = super().get_queryset()
        return queryset.select_related('contact', 'workspace')

    @action(detail=True, methods=['get'])
    def messages(self, request: Request, pk: str | None = None) -> Response:
        conversation = self.get_object()
        queryset = conversation.messages.select_related(
            'conversation',
            'conversation__contact',
            'conversation__workspace',
        ).order_by('-created_at')

        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = MessageSerializer(page, many=True, context={'request': request})
            return self.get_paginated_response(serializer.data)

        serializer = MessageSerializer(queryset, many=True, context={'request': request})
        return Response(serializer.data)

    @action(detail=True, methods=['post'])
    def reply(self, request: Request, pk: str | None = None) -> Response:
        """Envia mensagem outbound (agente -> cliente) via Evolution API."""
        input_serializer = MessageCreateSerializer(data=request.data)
        input_serializer.is_valid(raise_exception=True)
        body = input_serializer.validated_data['body']

        conversation = self.get_object()
        phone = conversation.contact.phone
        if not phone:
            return Response(
                {'detail': 'Contato sem telefone cadastrado.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            evolution_response = send_whatsapp_message(phone, body)
        except requests.exceptions.RequestException:
            return Response(
                {'detail': 'Falha ao enviar mensagem via WhatsApp.'},
                status=status.HTTP_502_BAD_GATEWAY,
            )

        key = evolution_response.get('key', {})
        external_id = key.get('id') if isinstance(key, dict) else None

        message = Message.objects.create(
            conversation=conversation,
            body=body,
            direction=Message.Direction.OUTBOUND,
            status=Message.Status.SENT,
            external_id=external_id,
        )
        output_serializer = MessageSerializer(message, context={'request': request})
        return Response(output_serializer.data, status=status.HTTP_201_CREATED)
