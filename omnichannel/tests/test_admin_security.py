from __future__ import annotations

import pytest
from django.contrib import admin

from omnichannel.admin import AIObservabilityEventAdmin, AIProcessingRunAdmin
from omnichannel.models import AIObservabilityEvent, AIProcessingRun
from workspaces.factories import UserFactory


@pytest.mark.django_db
@pytest.mark.parametrize(
    ('model', 'admin_class'),
    [
        (AIProcessingRun, AIProcessingRunAdmin),
        (AIObservabilityEvent, AIObservabilityEventAdmin),
    ],
)
def test_diagnostic_omnichannel_admin_models_are_registered_read_only(rf, model, admin_class) -> None:
    request = rf.get('/')
    request.user = UserFactory(is_staff=True, is_superuser=True)
    model_admin = admin.site._registry[model]

    assert isinstance(model_admin, admin_class)
    assert model_admin.has_view_permission(request) is True
    assert model_admin.has_add_permission(request) is False
    assert model_admin.has_change_permission(request) is False
    assert model_admin.has_delete_permission(request) is False


@pytest.mark.django_db
@pytest.mark.parametrize('model', [AIProcessingRun, AIObservabilityEvent])
def test_diagnostic_omnichannel_admin_list_display_excludes_sensitive_fields(model) -> None:
    model_admin = admin.site._registry[model]
    list_display = set(model_admin.list_display)

    assert 'body' not in list_display
    assert 'api_key' not in list_display
    assert 'payload' not in list_display
    assert 'raw_payload' not in list_display
    assert 'prompt' not in list_display
    assert 'response' not in list_display
    assert 'headers' not in list_display
