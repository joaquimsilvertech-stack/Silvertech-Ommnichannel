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
    path('', include(router.urls)),
]
