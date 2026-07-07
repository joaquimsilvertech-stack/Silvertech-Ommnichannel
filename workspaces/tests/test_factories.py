from __future__ import annotations

import pytest

from workspaces.factories import WorkspaceAIProviderConfigFactory, WorkspaceFactory


@pytest.mark.django_db
def test_workspace_factory_does_not_populate_legacy_ai_system_prompt() -> None:
    workspace = WorkspaceFactory()

    assert workspace.ai_system_prompt is None


@pytest.mark.django_db
def test_workspace_ai_provider_config_factory_populates_modern_system_prompt() -> None:
    provider_config = WorkspaceAIProviderConfigFactory()

    assert provider_config.system_prompt
