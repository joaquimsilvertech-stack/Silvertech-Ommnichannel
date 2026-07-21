from __future__ import annotations

import pytest

from workspaces.models import Workspace
from workspaces.slug_service import (
    FALLBACK_SLUG_BASE,
    MAX_SLUG_LENGTH,
    build_workspace_slug_base,
    generate_unique_workspace_slug,
)


@pytest.mark.parametrize(
    ('name', 'expected'),
    [
        ('Empresa Exemplo', 'empresa-exemplo'),
        ('Acme Serviços LTDA', 'acme-servicos-ltda'),
        ('  Espacos  Extras  ', 'espacos-extras'),
        ('CAIXA ALTA', 'caixa-alta'),
    ],
)
def test_slug_base_is_derived_from_name(name, expected) -> None:
    assert build_workspace_slug_base(name) == expected


@pytest.mark.parametrize('name', ['', '   ', '###', '!!!', '---', None])
def test_unslugifiable_names_use_deterministic_fallback(name) -> None:
    assert build_workspace_slug_base(name) == FALLBACK_SLUG_BASE


def test_slug_base_reserves_room_for_the_collision_suffix() -> None:
    base = build_workspace_slug_base('a' * 400)

    assert len(base) <= MAX_SLUG_LENGTH - 9


@pytest.mark.django_db
def test_slug_is_clean_when_there_is_no_collision() -> None:
    assert generate_unique_workspace_slug('Empresa Exemplo') == 'empresa-exemplo'


@pytest.mark.django_db
def test_slug_gets_suffix_on_collision() -> None:
    Workspace.objects.create(name='Empresa Exemplo', slug='empresa-exemplo')

    slug = generate_unique_workspace_slug('Empresa Exemplo')

    assert slug != 'empresa-exemplo'
    assert slug.startswith('empresa-exemplo-')
    assert len(slug) <= MAX_SLUG_LENGTH


@pytest.mark.django_db
def test_force_suffix_skips_the_clean_attempt() -> None:
    slug = generate_unique_workspace_slug('Empresa Exemplo', force_suffix=True)

    assert slug.startswith('empresa-exemplo-')
    assert slug != 'empresa-exemplo'


@pytest.mark.django_db
def test_forced_suffixes_do_not_repeat() -> None:
    slugs = {
        generate_unique_workspace_slug('Empresa Exemplo', force_suffix=True)
        for _ in range(50)
    }

    assert len(slugs) == 50


@pytest.mark.django_db
def test_long_name_with_collision_still_fits_the_field() -> None:
    # 248 caracteres: cabe em Workspace.name (255) e estoura o slug (128).
    long_name = 'Empresa ' * 31
    base = build_workspace_slug_base(long_name)
    Workspace.objects.create(name=long_name, slug=base)

    slug = generate_unique_workspace_slug(long_name)

    assert len(slug) <= MAX_SLUG_LENGTH
    assert Workspace._meta.get_field('slug').max_length == MAX_SLUG_LENGTH
