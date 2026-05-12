from rest_framework import viewsets

from .models import Contact, Lead
from .serializers import ContactSerializer, LeadSerializer


class ContactViewSet(viewsets.ModelViewSet):
    queryset = Contact.objects.all()
    serializer_class = ContactSerializer


class LeadViewSet(viewsets.ModelViewSet):
    queryset = Lead.objects.select_related('contact').all()
    serializer_class = LeadSerializer
