"""Serializers de autenticacao publica (cadastro self-service)."""
from __future__ import annotations

from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers

from workspaces.registration_service import (
    EmailAlreadyRegisteredError,
    register_owner_account,
    split_full_name,
)

User = get_user_model()


class RegisteredUserSerializer(serializers.Serializer):
    """Representacao segura do usuario criado (nunca inclui senha ou hash)."""

    id = serializers.UUIDField(read_only=True)
    email = serializers.EmailField(read_only=True)
    first_name = serializers.CharField(read_only=True)
    last_name = serializers.CharField(read_only=True)
    full_name = serializers.SerializerMethodField()

    def get_full_name(self, obj) -> str:
        return f'{obj.first_name} {obj.last_name}'.strip()


class RegisteredWorkspaceSerializer(serializers.Serializer):
    id = serializers.UUIDField(read_only=True)
    name = serializers.CharField(read_only=True)
    slug = serializers.SlugField(read_only=True)


class RegisteredMembershipSerializer(serializers.Serializer):
    id = serializers.UUIDField(read_only=True)
    role = serializers.CharField(read_only=True)


class RegistrationTokensSerializer(serializers.Serializer):
    access = serializers.CharField(read_only=True)
    refresh = serializers.CharField(read_only=True)


class RegistrationResponseSerializer(serializers.Serializer):
    """Contrato de resposta 201 do cadastro."""

    user = RegisteredUserSerializer(read_only=True)
    workspace = RegisteredWorkspaceSerializer(read_only=True)
    membership = RegisteredMembershipSerializer(read_only=True)
    tokens = RegistrationTokensSerializer(read_only=True)


class RegistrationSerializer(serializers.Serializer):
    """
    Entrada do cadastro publico.

    `slug` e `role` nao sao aceitos: o slug e derivado do nome da empresa e o
    papel no tenant e sempre OWNER.
    """

    full_name = serializers.CharField(max_length=300, trim_whitespace=True)
    company_name = serializers.CharField(max_length=255, trim_whitespace=True)
    email = serializers.EmailField(max_length=254)
    password = serializers.CharField(
        write_only=True,
        max_length=128,
        trim_whitespace=False,
        style={'input_type': 'password'},
    )

    def validate_email(self, value: str) -> str:
        # Caixa baixa completa, identica ao que o servico grava, para que a
        # checagem e o valor propagado batam com o e-mail persistido.
        normalized = User.objects.normalize_email(value.strip()).lower()
        if User.objects.filter(email__iexact=normalized).exists():
            raise serializers.ValidationError('Ja existe uma conta com este e-mail.')
        return normalized

    def validate(self, attrs: dict) -> dict:
        # Roda os validadores do Django com o usuario ainda nao persistido, para
        # que UserAttributeSimilarityValidator compare senha, e-mail e nome.
        first_name, last_name = split_full_name(attrs.get('full_name', ''))
        candidate = User(
            email=attrs.get('email', ''),
            first_name=first_name,
            last_name=last_name,
        )
        try:
            validate_password(attrs['password'], user=candidate)
        except DjangoValidationError as exc:
            raise serializers.ValidationError({'password': list(exc.messages)}) from exc
        return attrs

    def create(self, validated_data: dict):
        try:
            return register_owner_account(
                full_name=validated_data['full_name'],
                company_name=validated_data['company_name'],
                email=validated_data['email'],
                password=validated_data['password'],
            )
        except EmailAlreadyRegisteredError as exc:
            # Corrida entre duas requisicoes com o mesmo e-mail: 400, nunca 500.
            raise serializers.ValidationError(
                {'email': ['Ja existe uma conta com este e-mail.']},
            ) from exc
