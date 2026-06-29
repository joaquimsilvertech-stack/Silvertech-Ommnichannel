from django.urls import include, path
from rest_framework.routers import SimpleRouter

from .views import ContactViewSet, DashboardAnalyticsView, LeadViewSet, OrganizationViewSet

router = SimpleRouter()
router.register('contacts', ContactViewSet, basename='contact')
router.register('leads', LeadViewSet, basename='lead')
router.register('organizations', OrganizationViewSet, basename='organization')

urlpatterns = [
    path(
        'dashboard/<uuid:workspace_id>/',
        DashboardAnalyticsView.as_view(),
        name='dashboard-analytics',
    ),
    path('', include(router.urls)),
]
