from typing import Any

from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.filters import SearchFilter
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from crm.mixins import WorkspaceScopedQuerysetMixin
from crm.pagination import CRMCursorPagination

from .models import Conversation, Message
from .serializers import ConversationSerializer, MessageSerializer


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
        queryset = conversation.messages.order_by('-created_at')

        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = MessageSerializer(page, many=True, context={'request': request})
            return self.get_paginated_response(serializer.data)

        serializer = MessageSerializer(queryset, many=True, context={'request': request})
        return Response(serializer.data)
