from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import filters, viewsets
from rest_framework.permissions import IsAuthenticated

from crm.mixins import WorkspaceScopedQuerysetMixin
from crm.pagination import CRMCursorPagination

from .models import Ticket
from .serializers import TicketSerializer


class TicketViewSet(WorkspaceScopedQuerysetMixin, viewsets.ModelViewSet):
    serializer_class = TicketSerializer
    permission_classes = [IsAuthenticated]
    pagination_class = CRMCursorPagination
    filter_backends = [DjangoFilterBackend, filters.OrderingFilter]
    filterset_fields = ['status', 'assigned_to', 'due_at']
    ordering_fields = ['created_at', 'updated_at', 'due_at']
    ordering = ['-created_at']
    workspace_lookup = 'workspace'

    def get_queryset(self):
        queryset = Ticket.objects.select_related(
            'workspace',
            'contact',
            'conversation',
            'assigned_to',
        )
        return queryset.filter(workspace__in=self.get_user_workspace_ids())
