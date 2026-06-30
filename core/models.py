"""
Modelos centrais da plataforma.

CustomUser concentra identidade e autorização base do CRM omnichannel.
Login por e-mail evita duplicidade de identificadores e alinha com fluxos B2B.
"""
import uuid

from django.conf import settings
from django.contrib.auth.models import AbstractUser, BaseUserManager
from django.db import models


class BaseModel(models.Model):
    """Campos comuns a entidades de domínio (UUID + auditoria temporal)."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


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
    Chave primária UUID para APIs públicas e particionamento futuro.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

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
        db_index=True,
        help_text='Papel genérico para RBAC e políticas de API.',
    )

    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = []

    objects = CustomUserManager()  # <--- Isso liga o novo Manager ao Usuário

    class Meta:
        verbose_name = 'usuário'
        verbose_name_plural = 'usuários'

    def __str__(self) -> str:
        return self.email


class AuditLog(BaseModel):
    """Trilha de auditoria multi-tenant para alteracoes sensiveis."""

    class Action(models.TextChoices):
        CREATE = 'CREATE', 'Create'
        UPDATE = 'UPDATE', 'Update'
        DELETE = 'DELETE', 'Delete'

    workspace = models.ForeignKey(
        'workspaces.Workspace',
        on_delete=models.CASCADE,
        related_name='audit_logs',
        db_index=True,
    )
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='audit_logs',
        db_index=True,
    )
    action = models.CharField(
        max_length=16,
        choices=Action.choices,
        db_index=True,
    )
    model_name = models.CharField(max_length=128, db_index=True)
    object_id = models.CharField(max_length=64, db_index=True)
    object_repr = models.CharField(max_length=255, blank=True)
    before = models.JSONField(null=True, blank=True)
    after = models.JSONField(null=True, blank=True)
    changes = models.JSONField(null=True, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.TextField(blank=True)
    request_id = models.CharField(max_length=128, blank=True, db_index=True)

    class Meta:
        ordering = ('-created_at',)
        indexes = [
            models.Index(fields=['workspace', '-created_at']),
            models.Index(fields=['workspace', 'action']),
            models.Index(fields=['workspace', 'model_name']),
        ]
        verbose_name = 'audit log'
        verbose_name_plural = 'audit logs'

    def __str__(self) -> str:
        return f'{self.action} {self.model_name} {self.object_id}'
