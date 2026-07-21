from __future__ import annotations

from unittest.mock import patch

import pytest
import requests
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from omnichannel.models import WhatsAppChannel
from workspaces.models import Member, Workspace
from workspaces.registration_service import register_owner_account

User = get_user_model()

REGISTER_URL = '/api/auth/register/'
STRONG_PASSWORD = 'Sv7!kqrZm2wPx4'

VALID_PAYLOAD = {
    'full_name': 'Nome Sobrenome',
    'company_name': 'Empresa Exemplo',
    'email': 'pessoa@empresa.exemplo',
    'password': STRONG_PASSWORD,
}


@pytest.fixture(autouse=True)
def clear_throttle_cache():
    """O escopo auth_register e 5/minute; limpa o contador entre os testes."""
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def client() -> APIClient:
    return APIClient()


def _payload(**overrides) -> dict:
    return {**VALID_PAYLOAD, **overrides}


@pytest.mark.django_db
def test_registration_creates_user_workspace_and_owner_member(client) -> None:
    response = client.post(REGISTER_URL, _payload(), format='json')

    assert response.status_code == status.HTTP_201_CREATED
    user = User.objects.get(email='pessoa@empresa.exemplo')
    workspace = Workspace.objects.get(name='Empresa Exemplo')
    member = Member.objects.get(user=user, workspace=workspace)

    assert user.first_name == 'Nome'
    assert user.last_name == 'Sobrenome'
    assert user.check_password(STRONG_PASSWORD) is True
    assert user.is_active is True
    assert member.role == Member.Role.OWNER


@pytest.mark.django_db
def test_registration_response_contract(client) -> None:
    response = client.post(REGISTER_URL, _payload(), format='json')
    body = response.json()

    assert set(body) == {'user', 'workspace', 'membership', 'tokens'}
    assert body['user']['email'] == 'pessoa@empresa.exemplo'
    assert body['user']['full_name'] == 'Nome Sobrenome'
    assert body['workspace']['name'] == 'Empresa Exemplo'
    assert body['workspace']['slug'] == 'empresa-exemplo'
    assert body['membership']['role'] == Member.Role.OWNER
    assert body['tokens']['access']
    assert body['tokens']['refresh']


@pytest.mark.django_db
def test_workspace_slug_is_generated_from_company_name(client) -> None:
    client.post(REGISTER_URL, _payload(company_name='Acme Serviços LTDA'), format='json')

    workspace = Workspace.objects.get(name='Acme Serviços LTDA')

    assert workspace.slug == 'acme-servicos-ltda'


@pytest.mark.django_db
def test_same_company_name_produces_distinct_slugs(client) -> None:
    client.post(REGISTER_URL, _payload(), format='json')
    client.post(
        REGISTER_URL,
        _payload(email='outra@empresa.exemplo'),
        format='json',
    )

    slugs = list(Workspace.objects.values_list('slug', flat=True))

    assert len(slugs) == 2
    assert len(set(slugs)) == 2
    assert 'empresa-exemplo' in slugs


@pytest.mark.django_db
def test_company_name_without_slugifiable_characters_uses_fallback(client) -> None:
    response = client.post(REGISTER_URL, _payload(company_name='###'), format='json')

    assert response.status_code == status.HTTP_201_CREATED
    workspace = Workspace.objects.get(name='###')
    assert workspace.slug == 'workspace'
    assert workspace.slug != ''


@pytest.mark.django_db
def test_failure_creating_member_rolls_back_everything(client) -> None:
    with patch(
        'workspaces.registration_service.Member.objects.create',
        side_effect=RuntimeError('falha simulada'),
    ):
        with pytest.raises(RuntimeError):
            client.post(REGISTER_URL, _payload(), format='json')

    assert User.objects.filter(email='pessoa@empresa.exemplo').count() == 0
    assert Workspace.objects.count() == 0
    assert Member.objects.count() == 0


@pytest.mark.django_db
def test_failure_creating_workspace_rolls_back_user(client) -> None:
    with patch(
        'workspaces.registration_service.Workspace.objects.create',
        side_effect=RuntimeError('falha simulada'),
    ):
        with pytest.raises(RuntimeError):
            client.post(REGISTER_URL, _payload(), format='json')

    assert User.objects.filter(email='pessoa@empresa.exemplo').count() == 0
    assert Workspace.objects.count() == 0
    assert Member.objects.count() == 0


@pytest.mark.django_db
def test_duplicate_email_returns_400_with_field_error(client) -> None:
    client.post(REGISTER_URL, _payload(), format='json')

    response = client.post(
        REGISTER_URL,
        _payload(company_name='Outra Empresa'),
        format='json',
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert 'email' in response.json()
    assert User.objects.filter(email='pessoa@empresa.exemplo').count() == 1
    assert Workspace.objects.count() == 1


@pytest.mark.django_db
def test_duplicate_email_is_case_insensitive(client) -> None:
    client.post(REGISTER_URL, _payload(), format='json')

    response = client.post(
        REGISTER_URL,
        _payload(email='PESSOA@empresa.exemplo'),
        format='json',
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert 'email' in response.json()


@pytest.mark.django_db
def test_race_on_duplicate_email_returns_400_not_500(client) -> None:
    """Se a unicidade escapar da validacao, o IntegrityError vira 400."""
    User.objects.create_user(email='pessoa@empresa.exemplo', password=STRONG_PASSWORD)

    with patch('core.serializers.User.objects.filter') as filter_mock:
        filter_mock.return_value.exists.return_value = False
        response = client.post(REGISTER_URL, _payload(), format='json')

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert 'email' in response.json()
    assert Workspace.objects.count() == 0
    assert Member.objects.count() == 0


@pytest.mark.django_db
@pytest.mark.parametrize('weak_password', ['123456', 'senha', 'password', '12345678'])
def test_weak_password_returns_400(client, weak_password) -> None:
    response = client.post(REGISTER_URL, _payload(password=weak_password), format='json')

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert 'password' in response.json()
    assert User.objects.count() == 0
    assert Workspace.objects.count() == 0


@pytest.mark.django_db
@pytest.mark.parametrize('field', ['full_name', 'company_name', 'email', 'password'])
def test_required_fields_are_enforced(client, field) -> None:
    payload = _payload()
    payload.pop(field)

    response = client.post(REGISTER_URL, payload, format='json')

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert field in response.json()


@pytest.mark.django_db
@pytest.mark.parametrize('field', ['full_name', 'company_name'])
def test_blank_after_trim_is_rejected(client, field) -> None:
    response = client.post(REGISTER_URL, _payload(**{field: '   '}), format='json')

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert field in response.json()


@pytest.mark.django_db
def test_password_is_never_exposed_in_response(client) -> None:
    response = client.post(REGISTER_URL, _payload(), format='json')
    raw_body = response.content.decode()

    assert 'password' not in response.json()
    assert STRONG_PASSWORD not in raw_body
    assert User.objects.get(email='pessoa@empresa.exemplo').password not in raw_body


@pytest.mark.django_db
def test_password_is_never_written_to_logs(client, caplog) -> None:
    with caplog.at_level('DEBUG'):
        client.post(REGISTER_URL, _payload(), format='json')

    assert STRONG_PASSWORD not in caplog.text


@pytest.mark.django_db
def test_slug_and_role_in_payload_are_ignored(client) -> None:
    response = client.post(
        REGISTER_URL,
        _payload(slug='slug-do-cliente', role='admin'),
        format='json',
    )

    assert response.status_code == status.HTTP_201_CREATED
    workspace = Workspace.objects.get()
    user = User.objects.get(email='pessoa@empresa.exemplo')

    assert workspace.slug == 'empresa-exemplo'
    assert user.role == User.Role.VIEWER


@pytest.mark.django_db
def test_platform_role_stays_at_default(client) -> None:
    client.post(REGISTER_URL, _payload(), format='json')
    user = User.objects.get(email='pessoa@empresa.exemplo')

    assert user.role == User.Role.VIEWER
    assert user.is_staff is False
    assert user.is_superuser is False


@pytest.mark.django_db
def test_endpoint_is_public_without_authorization_header(client) -> None:
    assert 'HTTP_AUTHORIZATION' not in client._credentials

    response = client.post(REGISTER_URL, _payload(), format='json')

    assert response.status_code == status.HTTP_201_CREATED


@pytest.mark.django_db
def test_registration_is_throttled(client) -> None:
    response = None
    for index in range(6):
        response = client.post(
            REGISTER_URL,
            _payload(email=f'pessoa{index}@empresa.exemplo'),
            format='json',
            REMOTE_ADDR='198.51.100.30',
        )

    assert response is not None
    assert response.status_code == status.HTTP_429_TOO_MANY_REQUESTS


@pytest.mark.django_db
def test_registration_does_not_provision_evolution_or_channel(client) -> None:
    with patch.object(
        requests.Session,
        'request',
        side_effect=AssertionError('O cadastro nao pode fazer chamada HTTP externa.'),
    ), patch(
        'omnichannel.whatsapp_channel_provisioning.provision_whatsapp_channel',
        side_effect=AssertionError('O cadastro nao pode provisionar canal.'),
    ):
        response = client.post(REGISTER_URL, _payload(), format='json')

    assert response.status_code == status.HTTP_201_CREATED
    assert WhatsAppChannel.objects.count() == 0


@pytest.mark.django_db
def test_new_owner_only_sees_own_workspace(client) -> None:
    other_workspace = Workspace.objects.create(name='Outro Tenant', slug='outro-tenant')
    response = client.post(REGISTER_URL, _payload(), format='json')
    access = response.json()['tokens']['access']

    authenticated = APIClient()
    authenticated.credentials(HTTP_AUTHORIZATION=f'Bearer {access}')
    listing = authenticated.get('/api/workspaces/workspaces/')

    assert listing.status_code == status.HTTP_200_OK
    returned = listing.json()
    results = returned['results'] if isinstance(returned, dict) else returned
    slugs = {item['slug'] for item in results}
    assert slugs == {'empresa-exemplo'}
    assert str(other_workspace.id) not in {item['id'] for item in results}


@pytest.mark.django_db
def test_returned_tokens_authenticate_the_new_owner(client) -> None:
    response = client.post(REGISTER_URL, _payload(), format='json')
    tokens = response.json()['tokens']

    authenticated = APIClient()
    authenticated.credentials(HTTP_AUTHORIZATION=f'Bearer {tokens["access"]}')
    listing = authenticated.get('/api/workspaces/workspaces/')

    assert listing.status_code == status.HTTP_200_OK

    refreshed = APIClient().post(
        '/api/auth/token/refresh/',
        {'refresh': tokens['refresh']},
        format='json',
        REMOTE_ADDR='198.51.100.31',
    )

    assert refreshed.status_code == status.HTTP_200_OK
    assert refreshed.json()['access']


@pytest.mark.django_db
def test_registered_credentials_work_on_token_endpoint(client) -> None:
    client.post(REGISTER_URL, _payload(), format='json')

    response = APIClient().post(
        '/api/auth/token/',
        {'email': 'pessoa@empresa.exemplo', 'password': STRONG_PASSWORD},
        format='json',
        REMOTE_ADDR='198.51.100.32',
    )

    assert response.status_code == status.HTTP_200_OK
    assert response.json()['access']


@pytest.mark.django_db
def test_service_is_reusable_outside_the_endpoint() -> None:
    account = register_owner_account(
        full_name='Alguem Da Silva Souza',
        company_name='Servico Direto',
        email='Direto@Empresa.Exemplo',
        password=STRONG_PASSWORD,
    )

    assert account.user.email == 'Direto@empresa.exemplo'
    assert account.user.first_name == 'Alguem'
    assert account.user.last_name == 'Da Silva Souza'
    assert account.workspace.slug == 'servico-direto'
    assert account.member.role == Member.Role.OWNER


@pytest.mark.django_db
def test_superuser_can_still_create_workspace_and_owner_manually() -> None:
    """Regressao: o caminho manual de suporte continua funcionando."""
    superuser = User.objects.create_superuser(
        email='suporte@silvertech.exemplo',
        password=STRONG_PASSWORD,
    )
    admin_client = APIClient()
    admin_client.force_login(superuser)

    workspace = Workspace.objects.create(name='Tenant Suporte', slug='tenant-suporte')
    member = Member.objects.create(
        workspace=workspace,
        user=superuser,
        role=Member.Role.OWNER,
    )

    assert member.role == Member.Role.OWNER
    assert Workspace.objects.filter(slug='tenant-suporte').exists()

    changelist = admin_client.get(reverse('admin:workspaces_workspace_changelist'))
    assert changelist.status_code == status.HTTP_200_OK


@pytest.mark.django_db
def test_workspace_without_owner_is_still_allowed_for_support() -> None:
    """A invariante e escopada ao cadastro, nao e constraint global do model."""
    workspace = Workspace.objects.create(name='Sem Owner', slug='sem-owner')

    assert workspace.memberships.count() == 0


@pytest.mark.django_db
def test_get_method_is_not_allowed(client) -> None:
    response = client.get(REGISTER_URL)

    assert response.status_code == status.HTTP_405_METHOD_NOT_ALLOWED
