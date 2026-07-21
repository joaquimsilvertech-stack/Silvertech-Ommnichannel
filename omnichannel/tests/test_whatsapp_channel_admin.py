from __future__ import annotations

import pytest
from django.contrib import admin
from django.test import Client
from django.urls import reverse

from omnichannel.admin import WhatsAppChannelAdmin
from omnichannel.factories import WhatsAppChannelFactory
from omnichannel.models import WhatsAppChannel
from workspaces.factories import UserFactory, WorkspaceFactory

CHANGELIST_URL = reverse('admin:omnichannel_whatsappchannel_changelist')

SENSITIVE_TOKEN = 'private-channel-token'
SENSITIVE_SECRET = 'private-webhook-secret'
SENSITIVE_PHONE = '551199998392'
SENSITIVE_API_KEY = 'private-api-key-marker'
SENSITIVE_INSTANCE_ID = 'private-instance-id-marker'


@pytest.fixture
def superuser_client() -> Client:
    user = UserFactory(is_staff=True, is_superuser=True)
    client = Client()
    client.force_login(user)
    return client


@pytest.fixture
def sensitive_channel() -> WhatsAppChannel:
    return WhatsAppChannelFactory(
        name='Canal comercial',
        instance_name='silvertech-canal-comercial',
        instance_id=SENSITIVE_INSTANCE_ID,
        instance_token=SENSITIVE_TOKEN,
        webhook_secret=SENSITIVE_SECRET,
        phone_number=SENSITIVE_PHONE,
        status=WhatsAppChannel.Status.CONNECTED,
    )


def _change_url(channel: WhatsAppChannel) -> str:
    return reverse('admin:omnichannel_whatsappchannel_change', args=[channel.id])


def test_whatsapp_channel_is_registered_in_admin_site() -> None:
    assert WhatsAppChannel in admin.site._registry
    assert isinstance(admin.site._registry[WhatsAppChannel], WhatsAppChannelAdmin)


@pytest.mark.django_db
def test_changelist_is_accessible_for_superuser(superuser_client, sensitive_channel) -> None:
    response = superuser_client.get(CHANGELIST_URL)

    assert response.status_code == 200


@pytest.mark.django_db
def test_change_view_is_accessible_for_superuser(superuser_client, sensitive_channel) -> None:
    response = superuser_client.get(_change_url(sensitive_channel))

    assert response.status_code == 200


@pytest.mark.django_db
def test_changelist_shows_safe_operational_fields(superuser_client, sensitive_channel) -> None:
    content = superuser_client.get(CHANGELIST_URL).content.decode()

    assert sensitive_channel.name in content
    assert sensitive_channel.workspace.name in content
    assert sensitive_channel.provider in content
    assert sensitive_channel.instance_name in content
    assert '********8392' in content


@pytest.mark.django_db
def test_changelist_does_not_expose_full_phone_number(superuser_client, sensitive_channel) -> None:
    content = superuser_client.get(CHANGELIST_URL).content.decode()

    assert SENSITIVE_PHONE not in content
    assert '5511' not in content
    assert '99998392' not in content


@pytest.mark.django_db
def test_change_view_does_not_expose_full_phone_number(superuser_client, sensitive_channel) -> None:
    content = superuser_client.get(_change_url(sensitive_channel)).content.decode()

    assert SENSITIVE_PHONE not in content
    assert '99998392' not in content
    assert '********8392' in content


@pytest.mark.django_db
@pytest.mark.parametrize(
    'sensitive_value',
    [SENSITIVE_TOKEN, SENSITIVE_SECRET, SENSITIVE_API_KEY, SENSITIVE_INSTANCE_ID],
)
def test_changelist_does_not_expose_secrets(
    superuser_client,
    sensitive_channel,
    sensitive_value,
) -> None:
    content = superuser_client.get(CHANGELIST_URL).content.decode()

    assert sensitive_value not in content


@pytest.mark.django_db
@pytest.mark.parametrize(
    'sensitive_value',
    [SENSITIVE_TOKEN, SENSITIVE_SECRET, SENSITIVE_API_KEY, SENSITIVE_INSTANCE_ID],
)
def test_change_view_does_not_expose_secrets(
    superuser_client,
    sensitive_channel,
    sensitive_value,
) -> None:
    content = superuser_client.get(_change_url(sensitive_channel)).content.decode()

    assert sensitive_value not in content


@pytest.mark.django_db
def test_admin_options_never_reference_sensitive_fields() -> None:
    model_admin = admin.site._registry[WhatsAppChannel]
    fieldset_fields = [
        field
        for _, options in model_admin.fieldsets
        for field in options['fields']
    ]
    referenced = {
        *model_admin.list_display,
        *model_admin.list_filter,
        *model_admin.search_fields,
        *model_admin.readonly_fields,
        *fieldset_fields,
        *getattr(model_admin, 'autocomplete_fields', ()),
        *getattr(model_admin, 'raw_id_fields', ()),
    }

    for forbidden in ('instance_token', 'webhook_secret', 'phone_number', 'instance_id'):
        assert forbidden not in referenced


@pytest.mark.django_db
def test_change_view_does_not_expose_qr_or_payload(superuser_client, sensitive_channel) -> None:
    content = superuser_client.get(_change_url(sensitive_channel)).content.decode().lower()

    assert 'qrcode' not in content
    assert 'base64' not in content
    assert 'payload' not in content


@pytest.mark.django_db
def test_add_view_is_blocked(superuser_client) -> None:
    response = superuser_client.get(reverse('admin:omnichannel_whatsappchannel_add'))

    assert response.status_code == 403


@pytest.mark.django_db
def test_change_post_does_not_modify_channel(superuser_client, sensitive_channel) -> None:
    response = superuser_client.post(
        _change_url(sensitive_channel),
        data={'name': 'Nome alterado', 'status': WhatsAppChannel.Status.DISCONNECTED},
    )
    sensitive_channel.refresh_from_db()

    assert response.status_code in (302, 403)
    assert sensitive_channel.name == 'Canal comercial'
    assert sensitive_channel.status == WhatsAppChannel.Status.CONNECTED


@pytest.mark.django_db
def test_delete_is_blocked(superuser_client, sensitive_channel) -> None:
    response = superuser_client.post(
        reverse('admin:omnichannel_whatsappchannel_delete', args=[sensitive_channel.id]),
        data={'post': 'yes'},
    )

    assert response.status_code == 403
    assert WhatsAppChannel.objects.filter(pk=sensitive_channel.pk).exists()


@pytest.mark.django_db
def test_permissions_are_view_only(rf) -> None:
    request = rf.get('/')
    request.user = UserFactory(is_staff=True, is_superuser=True)
    model_admin = admin.site._registry[WhatsAppChannel]

    assert model_admin.has_view_permission(request) is True
    assert model_admin.has_add_permission(request) is False
    assert model_admin.has_change_permission(request) is False
    assert model_admin.has_delete_permission(request) is False


@pytest.mark.django_db
def test_search_by_name_works(superuser_client, sensitive_channel) -> None:
    WhatsAppChannelFactory(name='Canal suporte', instance_name='silvertech-suporte')

    content = superuser_client.get(CHANGELIST_URL, {'q': 'comercial'}).content.decode()

    assert 'Canal comercial' in content
    assert 'Canal suporte' not in content


@pytest.mark.django_db
def test_search_by_instance_name_works(superuser_client, sensitive_channel) -> None:
    WhatsAppChannelFactory(name='Canal suporte', instance_name='silvertech-suporte')

    content = superuser_client.get(
        CHANGELIST_URL,
        {'q': 'silvertech-canal-comercial'},
    ).content.decode()

    assert 'Canal comercial' in content
    assert 'Canal suporte' not in content


@pytest.mark.django_db
def test_filter_by_workspace_works(superuser_client, sensitive_channel) -> None:
    other_workspace = WorkspaceFactory()
    WhatsAppChannelFactory(workspace=other_workspace, name='Canal de outro tenant')

    response = superuser_client.get(
        CHANGELIST_URL,
        {'workspace__id__exact': str(sensitive_channel.workspace_id)},
    )

    assert response.status_code == 200
    assert list(response.context['cl'].queryset) == [sensitive_channel]


@pytest.mark.django_db
def test_filter_by_status_works(superuser_client, sensitive_channel) -> None:
    WhatsAppChannelFactory(status=WhatsAppChannel.Status.DISCONNECTED)

    response = superuser_client.get(
        CHANGELIST_URL,
        {'status__exact': WhatsAppChannel.Status.CONNECTED},
    )

    assert list(response.context['cl'].queryset) == [sensitive_channel]


@pytest.mark.django_db
@pytest.mark.parametrize(
    'phone_number',
    ['', '123', '+5511999983920', '5511999983920@s.whatsapp.net'],
)
def test_edge_case_phone_numbers_render_safely(superuser_client, phone_number) -> None:
    channel = WhatsAppChannelFactory(name='Canal borda', phone_number=phone_number)
    model_admin = admin.site._registry[WhatsAppChannel]

    changelist = superuser_client.get(CHANGELIST_URL)
    detail = superuser_client.get(_change_url(channel))

    assert changelist.status_code == 200
    assert detail.status_code == 200
    assert model_admin.masked_phone_number(channel) == '—'
    for content in (changelist.content.decode(), detail.content.decode()):
        assert '—' in content
        assert '99998392' not in content
        assert '5511999983920' not in content


@pytest.mark.django_db
def test_changelist_uses_select_related_for_workspace(
    superuser_client,
    sensitive_channel,
    django_assert_num_queries,
) -> None:
    WhatsAppChannelFactory.create_batch(4)

    model_admin = admin.site._registry[WhatsAppChannel]
    assert model_admin.list_select_related == ('workspace',)

    request = superuser_client.get(CHANGELIST_URL).wsgi_request
    changelist = model_admin.get_changelist_instance(request)
    rows = list(changelist.get_queryset(request))

    with django_assert_num_queries(0):
        for row in rows:
            assert row.workspace.name is not None


@pytest.mark.django_db
def test_non_staff_user_cannot_access_admin() -> None:
    user = UserFactory(is_staff=False, is_superuser=False)
    client = Client()
    client.force_login(user)

    response = client.get(CHANGELIST_URL)

    assert response.status_code == 302
    assert '/admin/login/' in response['Location']
