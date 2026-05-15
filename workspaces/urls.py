from django.urls import include, path
from rest_framework.routers import SimpleRouter

from .views import MemberViewSet, WorkspaceInviteViewSet, WorkspaceViewSet

router = SimpleRouter()
router.register('workspaces', WorkspaceViewSet, basename='workspace')
router.register('members', MemberViewSet, basename='member')
router.register('invites', WorkspaceInviteViewSet, basename='workspace-invite')

urlpatterns = [
    path('', include(router.urls)),
]
