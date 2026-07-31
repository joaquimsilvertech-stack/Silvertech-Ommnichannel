from django.urls import include, path
from rest_framework.routers import SimpleRouter

from omnichannel.views import (
    AIObservabilityEventsView,
    AIObservabilitySummaryView,
    AIObservabilityTimeseriesView,
    ChannelObservabilitySummaryView,
    ChannelObservabilityTimeseriesView,
)
from omnichannel.whatsapp_channel_views import (
    WorkspaceWhatsAppChannelCollectionView,
    WorkspaceWhatsAppChannelDetailView,
    WorkspaceWhatsAppChannelDisconnectView,
    WorkspaceWhatsAppChannelQRCodeView,
    WorkspaceWhatsAppChannelReconnectView,
    WorkspaceWhatsAppChannelRestartView,
    WorkspaceWhatsAppChannelStatusView,
)

from .views import (
    MemberViewSet,
    WorkspaceAIProviderConfigViewSet,
    WorkspaceInviteViewSet,
    WorkspaceViewSet,
)

router = SimpleRouter()
router.register('workspaces', WorkspaceViewSet, basename='workspace')
router.register('members', MemberViewSet, basename='member')
router.register('invites', WorkspaceInviteViewSet, basename='workspace-invite')

urlpatterns = [
    path(
        '<uuid:workspace_id>/whatsapp-channels/',
        WorkspaceWhatsAppChannelCollectionView.as_view(),
        name='workspace-whatsapp-channel-provisioning',
    ),
    path(
        '<uuid:workspace_id>/whatsapp-channels/<uuid:channel_id>/',
        WorkspaceWhatsAppChannelDetailView.as_view(),
        name='workspace-whatsapp-channel-detail',
    ),
    path(
        '<uuid:workspace_id>/whatsapp-channels/<uuid:channel_id>/status/',
        WorkspaceWhatsAppChannelStatusView.as_view(),
        name='workspace-whatsapp-channel-status',
    ),
    path(
        '<uuid:workspace_id>/whatsapp-channels/<uuid:channel_id>/restart/',
        WorkspaceWhatsAppChannelRestartView.as_view(),
        name='workspace-whatsapp-channel-restart',
    ),
    path(
        '<uuid:workspace_id>/whatsapp-channels/<uuid:channel_id>/reconnect/',
        WorkspaceWhatsAppChannelReconnectView.as_view(),
        name='workspace-whatsapp-channel-reconnect',
    ),
    path(
        '<uuid:workspace_id>/whatsapp-channels/<uuid:channel_id>/disconnect/',
        WorkspaceWhatsAppChannelDisconnectView.as_view(),
        name='workspace-whatsapp-channel-disconnect',
    ),
    path(
        '<uuid:workspace_id>/whatsapp-channels/<uuid:channel_id>/qr/',
        WorkspaceWhatsAppChannelQRCodeView.as_view(),
        name='workspace-whatsapp-channel-qr',
    ),
    path(
        '<uuid:workspace_id>/ai-observability/summary/',
        AIObservabilitySummaryView.as_view(),
        name='workspace-ai-observability-summary',
    ),
    path(
        '<uuid:workspace_id>/ai-observability/timeseries/',
        AIObservabilityTimeseriesView.as_view(),
        name='workspace-ai-observability-timeseries',
    ),
    path(
        '<uuid:workspace_id>/ai-observability/events/',
        AIObservabilityEventsView.as_view(),
        name='workspace-ai-observability-events',
    ),
    path(
        '<uuid:workspace_id>/channel-observability/summary/',
        ChannelObservabilitySummaryView.as_view(),
        name='workspace-channel-observability-summary',
    ),
    path(
        '<uuid:workspace_id>/channel-observability/timeseries/',
        ChannelObservabilityTimeseriesView.as_view(),
        name='workspace-channel-observability-timeseries',
    ),
    path(
        '<uuid:workspace_id>/ai-providers/',
        WorkspaceAIProviderConfigViewSet.as_view(
            {
                'get': 'list',
                'post': 'create',
            },
        ),
        name='workspace-ai-provider-list',
    ),
    path(
        '<uuid:workspace_id>/ai-providers/<uuid:pk>/',
        WorkspaceAIProviderConfigViewSet.as_view(
            {
                'get': 'retrieve',
                'put': 'update',
                'patch': 'partial_update',
            },
        ),
        name='workspace-ai-provider-detail',
    ),
    path(
        '<uuid:workspace_id>/ai-providers/<uuid:pk>/test/',
        WorkspaceAIProviderConfigViewSet.as_view(
            {
                'post': 'test_connection',
            },
        ),
        name='workspace-ai-provider-test',
    ),
    path(
        '<uuid:workspace_id>/ai-providers/<uuid:pk>/activate/',
        WorkspaceAIProviderConfigViewSet.as_view(
            {
                'post': 'activate_provider',
            },
        ),
        name='workspace-ai-provider-activate',
    ),
    path(
        '<uuid:workspace_id>/ai-providers/<uuid:pk>/deactivate/',
        WorkspaceAIProviderConfigViewSet.as_view(
            {
                'post': 'deactivate_provider',
            },
        ),
        name='workspace-ai-provider-deactivate',
    ),
    path(
        '<uuid:workspace_id>/ai-providers/<uuid:pk>/credentials/replace/',
        WorkspaceAIProviderConfigViewSet.as_view(
            {
                'post': 'replace_credentials',
            },
        ),
        name='workspace-ai-provider-credentials-replace',
    ),
    path(
        '<uuid:workspace_id>/ai-providers/<uuid:pk>/credentials/revoke/',
        WorkspaceAIProviderConfigViewSet.as_view(
            {
                'post': 'revoke_credentials',
            },
        ),
        name='workspace-ai-provider-credentials-revoke',
    ),
    path('', include(router.urls)),
]
