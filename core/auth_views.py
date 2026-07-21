"""Endpoint publico de cadastro self-service."""
from __future__ import annotations

from drf_spectacular.utils import OpenApiExample, extend_schema
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken

from .serializers import RegistrationResponseSerializer, RegistrationSerializer

REGISTER_THROTTLE_SCOPE = 'auth_register'


class RegisterView(APIView):
    """
    POST /api/auth/register/ — cria User + Workspace + Member(OWNER) atomicamente.

    Endpoint publico: nao exige JWT. `authentication_classes` vazio remove a
    SessionAuthentication padrao e, com ela, a exigencia de CSRF.
    Nenhuma instancia Evolution e provisionada aqui.
    """

    authentication_classes = []
    permission_classes = [AllowAny]
    throttle_scope = REGISTER_THROTTLE_SCOPE

    @extend_schema(
        request=RegistrationSerializer,
        responses={201: RegistrationResponseSerializer},
        summary='Cadastro self-service',
        description=(
            'Cria a conta inicial do cliente. O slug do workspace e derivado do '
            'nome da empresa; nao e enviado pelo cliente. Nenhum canal WhatsApp '
            'e provisionado no cadastro.'
        ),
        examples=[
            OpenApiExample(
                'Cadastro',
                value={
                    'full_name': 'Nome Sobrenome',
                    'company_name': 'Empresa Exemplo',
                    'email': 'pessoa@empresa.exemplo',
                    'password': '<senha forte>',
                },
                request_only=True,
            ),
        ],
    )
    def post(self, request: Request) -> Response:
        serializer = RegistrationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        account = serializer.save()

        # Emitido apos o commit da transacao de escrita, fora de `atomic`.
        refresh = RefreshToken.for_user(account.user)
        payload = RegistrationResponseSerializer(
            {
                'user': account.user,
                'workspace': account.workspace,
                'membership': account.member,
                'tokens': {
                    'access': str(refresh.access_token),
                    'refresh': str(refresh),
                },
            },
        ).data
        return Response(payload, status=status.HTTP_201_CREATED)
