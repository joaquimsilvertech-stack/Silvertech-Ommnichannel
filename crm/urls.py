from django.urls import include, path
from rest_framework.routers import SimpleRouter

from .views import ContactViewSet, LeadViewSet

router = SimpleRouter()
router.register('contacts', ContactViewSet, basename='contact')
router.register('leads', LeadViewSet, basename='lead')

urlpatterns = [
    path('', include(router.urls)),
]
