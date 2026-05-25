from datetime import timedelta

from django.utils import timezone
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.filters import SearchFilter
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .mixins import WorkspaceScopedQuerysetMixin
from .models import Contact, Lead, Organization
from .pagination import CRMCursorPagination
from .serializers import ContactSerializer, LeadSerializer, OrganizationSerializer


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
    queryset = Lead.objects.select_related('contact', 'assigned_to').all()
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
