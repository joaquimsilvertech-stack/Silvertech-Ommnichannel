"""
Modelos genéricos do CRM: contatos extensíveis via JSON e leads vinculados 1:1.
"""
from django.db import models


class Contact(models.Model):
    """Pessoa ou organização; atributos flexíveis por nicho em `custom_attributes`."""

    class ContactType(models.TextChoices):
        LEAD = 'LEAD', 'Lead'
        CLIENT = 'CLIENT', 'Cliente'
        PARTNER = 'PARTNER', 'Parceiro'

    name = models.CharField(max_length=255)
    phone = models.CharField(max_length=64, blank=True)
    email = models.EmailField(blank=True)
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

    def __str__(self) -> str:
        return self.name


class Lead(models.Model):
    """Oportunidade comercial ligada a um único contato (1:1)."""

    class Status(models.TextChoices):
        NEW = 'NEW', 'Novo'
        CONTACTED = 'CONTACTED', 'Contatado'
        QUALIFIED = 'QUALIFIED', 'Qualificado'
        CONVERTED = 'CONVERTED', 'Convertido'
        LOST = 'LOST', 'Perdido'

    contact = models.OneToOneField(
        Contact,
        on_delete=models.CASCADE,
        related_name='lead',
    )
    status = models.CharField(
        max_length=32,
        choices=Status.choices,
        default=Status.NEW,
        db_index=True,
    )
    score = models.IntegerField(default=0)
    source = models.CharField(max_length=128, default='Manual')

    class Meta:
        ordering = ('-score', 'id')
        verbose_name = 'lead'
        verbose_name_plural = 'leads'

    def __str__(self) -> str:
        return f'Lead #{self.pk} — {self.contact.name} ({self.status})'
