from django_eventstream.channelmanager import DefaultChannelManager

from workspaces.models import Member


class WorkspaceChannelManager(DefaultChannelManager):
    """Autorização SSE alinhada ao escopo multi-tenant (Memberships)."""

    def can_read_channel(self, user, channel: str) -> bool:
        if not channel.startswith('workspace-'):
            return False
        if user is None or not getattr(user, 'is_authenticated', False):
            return False
        workspace_id = channel.removeprefix('workspace-')
        return Member.objects.filter(user=user, workspace_id=workspace_id).exists()
