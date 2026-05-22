from django.urls import include, path
from rest_framework.routers import SimpleRouter

from .views import ContactViewSet, LeadViewSet, OrganizationViewSet

router = SimpleRouter()
router.register('contacts', ContactViewSet, basename='contact')
router.register('leads', LeadViewSet, basename='lead')
router.register('organizations', OrganizationViewSet, basename='organization')

urlpatterns = [
    path('', include(router.urls)),
]
