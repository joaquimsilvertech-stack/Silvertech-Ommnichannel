from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import FlowViewSet

router = DefaultRouter()
router.register('flows', FlowViewSet, basename='flow')

urlpatterns = [
    path('', include(router.urls)),
]
