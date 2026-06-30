from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import viewsets
from rest_framework.filters import OrderingFilter
from rest_framework.permissions import IsAuthenticated

from workspaces.models import Member

from .models import Flow
from .serializers import FlowSerializer


class FlowViewSet(viewsets.ModelViewSet):
    serializer_class = FlowSerializer
    permission_classes = [IsAuthenticated]
    filter_backends = [DjangoFilterBackend, OrderingFilter]
    filterset_fields = ['is_active']
    ordering_fields = ['created_at', 'updated_at', 'name']
    ordering = ['-created_at']

    def get_queryset(self):
        user = self.request.user
        user_workspace = getattr(user, 'workspace', None)
        queryset = Flow.objects.select_related('workspace')

        if user_workspace is not None:
            return queryset.filter(workspace=user_workspace)

        workspace_ids = Member.objects.filter(user=user).values_list('workspace_id', flat=True)
        return queryset.filter(workspace_id__in=workspace_ids)
