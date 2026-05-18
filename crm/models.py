"""
Modelos genéricos do CRM: contatos por workspace, extensíveis via JSON; leads 1:1.
"""
import uuid  # noqa: F401

from django.conf import settings
from django.db import models

from core.models import BaseModel


class Contact(BaseModel):
    """Pessoa ou organização dentro de um workspace; atributos flexíveis em JSON."""

    class ContactType(models.TextChoices):
        LEAD = 'LEAD', 'Lead'
        CLIENT = 'CLIENT', 'Cliente'
        PARTNER = 'PARTNER', 'Parceiro'

    workspace = models.ForeignKey(
        'workspaces.Workspace',
        on_delete=models.CASCADE,
        related_name='contacts',
        db_index=True,
    )
    name = models.CharField(max_length=255, db_index=True)
    phone = models.CharField(max_length=64, blank=True)
    email = models.EmailField(blank=True, db_index=True)
    channel_id = models.CharField(
        max_length=255,
        null=True,
        blank=True,
        db_index=True,
        help_text='Identificador do contato no canal (ex.: WhatsApp).',
    )
    starred = models.BooleanField(default=False, db_index=True)
    contact_type = models.CharField(
        max_length=16,
        choices=ContactType.choices,
        default=ContactType.LEAD,
        db_index=True,
    )
    custom_attributes = models.JSONField(
        default=dict,
        blank=True,
        help_text='Campos específicos do cliente (CNPJ, idade, etc.) sem alterar o schema.',
    )

    class Meta:
        ordering = ('name',)
        verbose_name = 'contato'
        verbose_name_plural = 'contatos'
        indexes = [
            models.Index(fields=['workspace']),
            models.Index(fields=('workspace', 'name')),
        ]

    def __str__(self) -> str:
        return self.name


class Organization(BaseModel):
    """Empresa ou grupo dentro de um workspace, com vários contatos vinculados."""

    workspace = models.ForeignKey(
        'workspaces.Workspace',
        on_delete=models.CASCADE,
        related_name='organizations',
        db_index=True,
    )
    name = models.CharField(max_length=255, db_index=True)
    contacts = models.ManyToManyField(
        Contact,
        blank=True,
        related_name='organizations',
    )

    class Meta:
        ordering = ('name',)
        verbose_name = 'organização'
        verbose_name_plural = 'organizações'
        indexes = [
            models.Index(fields=['workspace']),
            models.Index(fields=('workspace', 'name')),
        ]

    def __str__(self) -> str:
        return self.name


class Lead(BaseModel):
    """Oportunidade comercial ligada a um único contato (1:1)."""

    class Status(models.TextChoices):
        NEW = 'new', 'Novo'
        CONTACTING = 'contacting', 'Em Contato'
        QUALIFIED = 'qualified', 'Qualificado'
        WON = 'won', 'Ganho'
        LOST = 'lost', 'Perdido'

    contact = models.OneToOneField(
        Contact,
        on_delete=models.CASCADE,
        related_name='lead',
        db_index=True,
    )
    status = models.CharField(
        max_length=32,
        choices=Status.choices,
        default=Status.NEW,
        db_index=True,
    )
    score = models.IntegerField(default=0, db_index=True)
    source = models.CharField(max_length=128, default='Manual', db_index=True)
    assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='assigned_leads',
        db_index=True,
    )
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ('-score', 'id')
        verbose_name = 'lead'
        verbose_name_plural = 'leads'
        indexes = [
            models.Index(fields=['contact']),
            models.Index(fields=['status']),
        ]

    def __str__(self) -> str:
        return f'Lead {self.pk} — {self.contact.name} ({self.status})'
