from __future__ import annotations

from unittest.mock import patch

import pytest
from django.core.cache import cache
from django.test import override_settings
from rest_framework.test import APIClient

from crm.cache import get_dashboard_metrics_cache_key
from omnichannel.factories import ContactFactory
from workspaces.models import Workspace


TEST_CACHES = {
    'default': {
        'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
        'LOCATION': 'dashboard-cache-tests',
    },
}


@pytest.mark.django_db
@override_settings(CACHES=TEST_CACHES)
def test_dashboard_metrics_uses_workspace_cache_on_second_request(
    api_client: APIClient,
    tenant_workspace: Workspace,
) -> None:
    cache.clear()
    cached_payload = {
        'workspace_id': str(tenant_workspace.id),
        'contacts_count': 1,
        'leads_count': 0,
        'converted_leads_count': 0,
        'messages_count': 0,
    }

    with patch(
        'crm.views.DashboardAnalyticsView._compute_metrics',
        autospec=True,
        return_value=cached_payload,
    ) as mock_compute_metrics:
        first_response = api_client.get(f'/api/crm/dashboard/{tenant_workspace.id}/')
        second_response = api_client.get(f'/api/crm/dashboard/{tenant_workspace.id}/')

    assert first_response.status_code == 200
    assert second_response.status_code == 200
    assert first_response.json() == cached_payload
    assert second_response.json() == cached_payload
    mock_compute_metrics.assert_called_once()


@pytest.mark.django_db
@override_settings(CACHES=TEST_CACHES)
def test_dashboard_cache_is_invalidated_when_contact_changes(
    tenant_workspace: Workspace,
) -> None:
    cache.clear()
    cache_key = get_dashboard_metrics_cache_key(tenant_workspace.id)
    cache.set(cache_key, {'contacts_count': 0}, timeout=60 * 15)

    ContactFactory(workspace=tenant_workspace)

    assert cache.get(cache_key) is None
