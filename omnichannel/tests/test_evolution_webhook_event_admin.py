from __future__ import annotations

import pytest
from django.contrib import admin
from django.test import Client
from django.urls import reverse

from omnichannel.admin import EvolutionWebhookEventAdmin
from omnichannel.factories import EvolutionWebhookEventFactory, WhatsAppChannelFactory
from omnichannel.models import EvolutionWebhookEvent, WhatsAppChannel
from workspaces.factories import UserFactory

CHANGELIST_URL = reverse('admin:omnichannel_evolutionwebhookevent_changelist')

SENSITIVE_TOKEN = 'private-channel-token'
SENSITIVE_SECRET = 'private-webhook-secret'
SENSITIVE_PHONE = '551199998392'
SENSITIVE_DEDUPLICATION_KEY = 'a' * 64


@pytest.fixture
def superuser_client() -> Client:
    user = UserFactory(is_staff=True, is_superuser=True)
    client = Client()
    client.force_login(user)
    return client


@pytest.fixture
def channel() -> WhatsAppChannel:
    return WhatsAppChannelFactory(
        name='Canal diagnostico',
        instance_name='silvertech-diagnostico',
        instance_token=SENSITIVE_TOKEN,
        webhook_secret=SENSITIVE_SECRET,
        phone_number=SENSITIVE_PHONE,
    )


@pytest.fixture
def event(channel) -> EvolutionWebhookEvent:
    return EvolutionWebhookEventFactory(
        whatsapp_channel=channel,
        event_type='MESSAGES_UPSERT',
        status=EvolutionWebhookEvent.Status.FAILED,
        deduplication_key=SENSITIVE_DEDUPLICATION_KEY,
        attempt_count=3,
        error_code='evolution_timeout',
    )


def _change_url(event: EvolutionWebhookEvent) -> str:
    return reverse('admin:omnichannel_evolutionwebhookevent_change', args=[event.id])


def test_evolution_webhook_event_is_registered_in_admin_site() -> None:
    assert EvolutionWebhookEvent in admin.site._registry
    assert isinstance(
        admin.site._registry[EvolutionWebhookEvent],
        EvolutionWebhookEventAdmin,
    )


@pytest.mark.django_db
def test_changelist_and_detail_are_accessible_for_superuser(superuser_client, event) -> None:
    assert superuser_client.get(CHANGELIST_URL).status_code == 200
    assert superuser_client.get(_change_url(event)).status_code == 200


@pytest.mark.django_db
def test_changelist_shows_diagnostic_fields(superuser_client, event) -> None:
    content = superuser_client.get(CHANGELIST_URL).content.decode()

    assert event.whatsapp_channel.workspace.name in content
    assert 'Canal diagnostico' in content
    assert 'MESSAGES_UPSERT' in content
    assert 'evolution_timeout' in content
    assert '>3<' in content


@pytest.mark.django_db
@pytest.mark.parametrize(
    'sensitive_value',
    [SENSITIVE_TOKEN, SENSITIVE_SECRET, SENSITIVE_PHONE, SENSITIVE_DEDUPLICATION_KEY],
)
def test_admin_pages_do_not_expose_sensitive_values(
    superuser_client,
    event,
    sensitive_value,
) -> None:
    changelist = superuser_client.get(CHANGELIST_URL).content.decode()
    detail = superuser_client.get(_change_url(event)).content.decode()

    assert sensitive_value not in changelist
    assert sensitive_value not in detail


@pytest.mark.django_db
def test_admin_pages_do_not_expose_payload_or_instance_name(superuser_client, event) -> None:
    changelist = superuser_client.get(CHANGELIST_URL).content.decode()
    detail = superuser_client.get(_change_url(event)).content.decode()

    for content in (changelist, detail):
        assert 'silvertech-diagnostico' not in content
        assert 'payload' not in content.lower()


@pytest.mark.django_db
def test_admin_options_never_reference_sensitive_fields() -> None:
    model_admin = admin.site._registry[EvolutionWebhookEvent]
    referenced = {
        *model_admin.list_display,
        *model_admin.list_filter,
        *model_admin.search_fields,
        *model_admin.readonly_fields,
        *model_admin.fields,
        *getattr(model_admin, 'autocomplete_fields', ()),
        *getattr(model_admin, 'raw_id_fields', ()),
    }

    for forbidden in ('deduplication_key', 'external_id', 'payload', 'raw_payload', 'headers'):
        assert forbidden not in referenced


@pytest.mark.django_db
def test_permissions_are_view_only(rf) -> None:
    request = rf.get('/')
    request.user = UserFactory(is_staff=True, is_superuser=True)
    model_admin = admin.site._registry[EvolutionWebhookEvent]

    assert model_admin.has_view_permission(request) is True
    assert model_admin.has_add_permission(request) is False
    assert model_admin.has_change_permission(request) is False
    assert model_admin.has_delete_permission(request) is False


@pytest.mark.django_db
def test_add_and_delete_views_are_blocked(superuser_client, event) -> None:
    add_response = superuser_client.get(
        reverse('admin:omnichannel_evolutionwebhookevent_add'),
    )
    delete_response = superuser_client.post(
        reverse('admin:omnichannel_evolutionwebhookevent_delete', args=[event.id]),
        data={'post': 'yes'},
    )

    assert add_response.status_code == 403
    assert delete_response.status_code == 403
    assert EvolutionWebhookEvent.objects.filter(pk=event.pk).exists()


@pytest.mark.django_db
def test_change_post_does_not_modify_event(superuser_client, event) -> None:
    response = superuser_client.post(
        _change_url(event),
        data={'status': EvolutionWebhookEvent.Status.PROCESSED, 'attempt_count': 99},
    )
    event.refresh_from_db()

    assert response.status_code in (302, 403)
    assert event.status == EvolutionWebhookEvent.Status.FAILED
    assert event.attempt_count == 3


@pytest.mark.django_db
def test_filter_by_status_and_channel_works(superuser_client, event) -> None:
    EvolutionWebhookEventFactory(status=EvolutionWebhookEvent.Status.PROCESSED)

    by_status = superuser_client.get(
        CHANGELIST_URL,
        {'status__exact': EvolutionWebhookEvent.Status.FAILED},
    )
    by_channel = superuser_client.get(
        CHANGELIST_URL,
        {'whatsapp_channel__id__exact': str(event.whatsapp_channel_id)},
    )

    assert list(by_status.context['cl'].queryset) == [event]
    assert list(by_channel.context['cl'].queryset) == [event]


@pytest.mark.django_db
def test_list_select_related_avoids_extra_queries(
    superuser_client,
    event,
    django_assert_num_queries,
) -> None:
    EvolutionWebhookEventFactory.create_batch(4)
    model_admin = admin.site._registry[EvolutionWebhookEvent]

    assert model_admin.list_select_related == (
        'whatsapp_channel',
        'whatsapp_channel__workspace',
    )

    request = superuser_client.get(CHANGELIST_URL).wsgi_request
    changelist = model_admin.get_changelist_instance(request)
    rows = list(changelist.get_queryset(request))

    with django_assert_num_queries(0):
        for row in rows:
            assert model_admin.workspace(row) is not None
