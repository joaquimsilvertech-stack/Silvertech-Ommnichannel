import django_eventstream
from django.urls import include, path
from rest_framework.routers import SimpleRouter

from .evolution_webhook_views import EvolutionChannelWebhookView
from .views import ConversationViewSet, WebhookAPIView

router = SimpleRouter()
router.register('conversations', ConversationViewSet, basename='conversation')

urlpatterns = [
    path(
        'events/<uuid:workspace_id>/',
        include(django_eventstream.urls),
        {'format-channels': ['workspace-{workspace_id}']},
    ),
    path(
        'webhooks/evolution/<uuid:webhook_public_id>/',
        EvolutionChannelWebhookView.as_view(),
        name='evolution-channel-webhook',
    ),
    path('webhooks/<str:channel_name>/', WebhookAPIView.as_view(), name='webhook'),
    path('', include(router.urls)),
]
