from django.db import migrations, models
from django.db.models import F


def backfill_channel_id_snapshot(apps, schema_editor):
    event_model = apps.get_model('omnichannel', 'AIObservabilityEvent')
    queryset = event_model.objects.filter(
        whatsapp_channel__isnull=False,
        whatsapp_channel__workspace_id=F('workspace_id'),
        whatsapp_channel_id_snapshot__isnull=True,
    ).only('id', 'whatsapp_channel_id', 'whatsapp_channel_id_snapshot')

    batch = []
    for event in queryset.iterator(chunk_size=1000):
        event.whatsapp_channel_id_snapshot = event.whatsapp_channel_id
        batch.append(event)
        if len(batch) == 1000:
            event_model.objects.bulk_update(batch, ['whatsapp_channel_id_snapshot'])
            batch = []
    if batch:
        event_model.objects.bulk_update(batch, ['whatsapp_channel_id_snapshot'])


class Migration(migrations.Migration):
    dependencies = [
        ('omnichannel', '0010_aiobservabilityevent_whatsapp_channel_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='aiobservabilityevent',
            name='whatsapp_channel_id_snapshot',
            field=models.UUIDField(
                blank=True,
                db_index=True,
                editable=False,
                help_text='UUID imutavel do canal, preservado apos sua remocao.',
                null=True,
            ),
        ),
        migrations.RunPython(backfill_channel_id_snapshot, migrations.RunPython.noop),
    ]
