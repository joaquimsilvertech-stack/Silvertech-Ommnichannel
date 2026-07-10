from django.urls import include, path
from rest_framework.routers import SimpleRouter

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
    path('', include(router.urls)),
]
