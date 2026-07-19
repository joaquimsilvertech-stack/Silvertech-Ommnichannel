from django.db import migrations, models
from django.db.models import Count


def clear_duplicate_contact_channel_ids(apps, schema_editor) -> None:
    Contact = apps.get_model('crm', 'Contact')
    database_alias = schema_editor.connection.alias
    contacts = Contact.objects.using(database_alias)
    duplicate_identities = (
        contacts.exclude(channel_id__isnull=True)
        .exclude(channel_id='')
        .values('workspace_id', 'channel_id')
        .annotate(duplicate_count=Count('id'))
        .filter(duplicate_count__gt=1)
        .order_by('workspace_id', 'channel_id')
    )

    for identity in duplicate_identities.iterator():
        canonical_id = (
            contacts.filter(
                workspace_id=identity['workspace_id'],
                channel_id=identity['channel_id'],
            )
            .order_by('created_at', 'id')
            .values_list('id', flat=True)
            .first()
        )
        if canonical_id is None:
            continue
        contacts.filter(
            workspace_id=identity['workspace_id'],
            channel_id=identity['channel_id'],
        ).exclude(id=canonical_id).update(channel_id=None)


class Migration(migrations.Migration):
    dependencies = [
        ('crm', '0003_contact_channel_id_contact_starred_lead_assigned_to_and_more'),
    ]

    operations = [
        migrations.RunPython(
            clear_duplicate_contact_channel_ids,
            migrations.RunPython.noop,
        ),
        migrations.AddConstraint(
            model_name='contact',
            constraint=models.UniqueConstraint(
                fields=('workspace', 'channel_id'),
                condition=(
                    models.Q(channel_id__isnull=False)
                    & ~models.Q(channel_id='')
                ),
                name='crm_contact_unique_ws_channel_id',
            ),
        ),
    ]
