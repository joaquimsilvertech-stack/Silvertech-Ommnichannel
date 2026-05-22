from workspaces.models import Member


class WorkspaceScopedQuerysetMixin:
    """Restringe o queryset aos workspaces em que o usuário é membro."""

    workspace_lookup = 'workspace'

    def get_user_workspace_ids(self):
        return Member.objects.filter(user=self.request.user).values_list(
            'workspace_id',
            flat=True,
        )

    def get_queryset(self):
        queryset = super().get_queryset()
        return queryset.filter(
            **{f'{self.workspace_lookup}__in': self.get_user_workspace_ids()},
        )
