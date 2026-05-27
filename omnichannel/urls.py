from django.urls import include, path
from rest_framework.routers import SimpleRouter

from .views import ConversationViewSet

router = SimpleRouter()
router.register('conversations', ConversationViewSet, basename='conversation')

urlpatterns = [
    path('', include(router.urls)),
]
