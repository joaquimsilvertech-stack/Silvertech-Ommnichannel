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
