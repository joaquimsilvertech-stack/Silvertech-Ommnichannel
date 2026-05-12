from rest_framework import serializers

from .models import Contact, Lead


class ContactSerializer(serializers.ModelSerializer):
    class Meta:
        model = Contact
        fields = (
            'id',
            'name',
            'phone',
            'email',
            'contact_type',
            'custom_attributes',
        )


class LeadSerializer(serializers.ModelSerializer):
    """
    Leitura: `contact` completo (nested).
    Escrita: enviar `contact_id` (PK do contato já existente).
    """

    contact = ContactSerializer(read_only=True)
    contact_id = serializers.PrimaryKeyRelatedField(
        queryset=Contact.objects.all(),
        source='contact',
        write_only=True,
        required=False,
    )

    class Meta:
        model = Lead
        fields = (
            'id',
            'contact_id',
            'contact',
            'status',
            'score',
            'source',
        )
        read_only_fields = ('id', 'contact')

    def validate(self, attrs):
        if self.instance is None and 'contact' not in attrs:
            raise serializers.ValidationError(
                {'contact_id': 'Obrigatório ao criar um lead.'},
            )
        return attrs
