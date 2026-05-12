"""
Modelos centrais da plataforma.

CustomUser concentra identidade e autorização base do CRM omnichannel.
Login por e-mail evita duplicidade de identificadores e alinha com fluxos B2B.
"""
from django.contrib.auth.models import AbstractUser, BaseUserManager
from django.db import models


class CustomUserManager(BaseUserManager):
    """Gerenciador de usuários onde o e-mail é o identificador único."""

    def create_user(self, email, password=None, **extra_fields):
        if not email:
            raise ValueError('O e-mail é obrigatório')
        email = self.normalize_email(email)
        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, email, password=None, **extra_fields):
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)
        extra_fields.setdefault('is_active', True)
        extra_fields.setdefault('role', 'admin')

        if extra_fields.get('is_staff') is not True:
            raise ValueError('Superuser precisa ter is_staff=True.')
        if extra_fields.get('is_superuser') is not True:
            raise ValueError('Superuser precisa ter is_superuser=True.')

        return self.create_user(email, password, **extra_fields)


class CustomUser(AbstractUser):
    """
    Usuário da plataforma: autenticação por e-mail + perfil operacional (role).
    """

    username = None
    email = models.EmailField('e-mail', unique=True, db_index=True)

    class Role(models.TextChoices):
        ADMIN = 'admin', 'Admin'
        AGENT = 'agent', 'Agent'
        VIEWER = 'viewer', 'Viewer'

    role = models.CharField(
        max_length=16,
        choices=Role.choices,
        default=Role.VIEWER,
        help_text='Papel genérico para RBAC e políticas de API.',
    )

    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = []

    objects = CustomUserManager() # <--- Isso liga o novo Manager ao Usuário

    class Meta:
        verbose_name = 'usuário'
        verbose_name_plural = 'usuários'

    def __str__(self) -> str:
        return self.email
