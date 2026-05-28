import django_eventstream
from django.urls import include, path
from rest_framework.routers import SimpleRouter

from .views import ConversationViewSet

router = SimpleRouter()
router.register('conversations', ConversationViewSet, basename='conversation')

urlpatterns = [
    path(
        'events/<uuid:workspace_id>/',
        include(django_eventstream.urls),
        {'format-channels': ['workspace-{workspace_id}']},
    ),
    path('', include(router.urls)),
]
