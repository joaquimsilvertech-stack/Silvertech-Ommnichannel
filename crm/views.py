from datetime import timedelta
import logging

from django.core.cache import cache
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.filters import SearchFilter
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from omnichannel.models import Message
from workspaces.models import Workspace

from .cache import DASHBOARD_METRICS_CACHE_TIMEOUT, get_dashboard_metrics_cache_key
from .mixins import WorkspaceScopedQuerysetMixin
from .models import Contact, Lead, Organization
from .pagination import CRMCursorPagination
from .serializers import ContactSerializer, LeadSerializer, OrganizationSerializer

logger = logging.getLogger(__name__)


class ContactViewSet(WorkspaceScopedQuerysetMixin, viewsets.ModelViewSet):
    queryset = Contact.objects.select_related('workspace').all()
    serializer_class = ContactSerializer
    permission_classes = [IsAuthenticated]
    pagination_class = CRMCursorPagination
    filter_backends = [DjangoFilterBackend, SearchFilter]
    filterset_fields = ['contact_type', 'starred', 'workspace']
    search_fields = ['name', 'phone', 'email']
    workspace_lookup = 'workspace'

    @action(detail=True, methods=['get'])
    def timeline(self, request, pk=None):
        """
        Mock preparatório para a Sprint 3 (Omnichannel).

        Retorna eventos fictícios em ordem cronológica até o app omnichannel
        persistir mensagens, mudanças de status e notas reais.
        """
        contact = self.get_object()
        now = timezone.now()
        mock_data = [
            {
                'type': 'message_received',
                'content': 'Olá, gostaria de um orçamento',
                'date': now.isoformat(),
                'contact_id': str(contact.pk),
            },
            {
                'type': 'status_change',
                'content': 'Lead movido para Em Contato',
                'date': (now - timedelta(days=1)).isoformat(),
                'contact_id': str(contact.pk),
            },
            {
                'type': 'note',
                'content': 'Cliente prefere contato na parte da manhã',
                'date': (now - timedelta(days=2)).isoformat(),
                'contact_id': str(contact.pk),
            },
        ]
        return Response(mock_data)


class LeadViewSet(WorkspaceScopedQuerysetMixin, viewsets.ModelViewSet):
    queryset = Lead.objects.select_related('contact', 'contact__workspace', 'assigned_to').all()
    serializer_class = LeadSerializer
    permission_classes = [IsAuthenticated]
    pagination_class = CRMCursorPagination
    filter_backends = [DjangoFilterBackend, SearchFilter]
    filterset_fields = ['status', 'assigned_to']
    search_fields = ['contact__name', 'contact__email', 'notes']
    workspace_lookup = 'contact__workspace'


class OrganizationViewSet(WorkspaceScopedQuerysetMixin, viewsets.ModelViewSet):
    queryset = Organization.objects.select_related('workspace').prefetch_related('contacts').all()
    serializer_class = OrganizationSerializer
    permission_classes = [IsAuthenticated]
    pagination_class = CRMCursorPagination
    filter_backends = [DjangoFilterBackend, SearchFilter]
    filterset_fields = ['workspace']
    search_fields = ['name']
    workspace_lookup = 'workspace'

    @action(detail=True, methods=['get'])
    def contacts(self, request, pk=None):
        """Lista os contatos vinculados à organização (Card #016)."""
        organization = self.get_object()
        contacts = organization.contacts.select_related('workspace').order_by('name')
        serializer = ContactSerializer(contacts, many=True, context={'request': request})
        return Response(serializer.data)


class DashboardAnalyticsView(APIView):
    """Metricas agregadas do dashboard com cache isolado por workspace."""

    permission_classes = [IsAuthenticated]

    def get(self, request, workspace_id):
        workspace = get_object_or_404(
            Workspace,
            id=workspace_id,
            memberships__user=request.user,
        )
        cache_key = get_dashboard_metrics_cache_key(workspace.id)
        try:
            data = cache.get(cache_key)
        except Exception as exc:
            logger.warning(
                'Falha ao ler cache de dashboard (workspace_id=%s): %s',
                workspace.id,
                exc,
                exc_info=True,
            )
            data = None

        if data is None:
            data = self._compute_metrics(workspace)
            try:
                cache.set(cache_key, data, timeout=DASHBOARD_METRICS_CACHE_TIMEOUT)
            except Exception as exc:
                logger.warning(
                    'Falha ao gravar cache de dashboard (workspace_id=%s): %s',
                    workspace.id,
                    exc,
                    exc_info=True,
                )

        return Response(data)

    def _compute_metrics(self, workspace: Workspace) -> dict[str, int | str]:
        """Executa agregacoes do dashboard para um workspace."""
        return {
            'workspace_id': str(workspace.id),
            'contacts_count': Contact.objects.filter(workspace=workspace).count(),
            'leads_count': Lead.objects.filter(contact__workspace=workspace).count(),
            'converted_leads_count': Lead.objects.filter(
                contact__workspace=workspace,
                status=Lead.Status.WON,
            ).count(),
            'messages_count': Message.objects.filter(
                conversation__workspace=workspace,
            ).count(),
        }
