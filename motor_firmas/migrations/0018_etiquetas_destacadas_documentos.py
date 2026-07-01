# Generated manually for featured document labels in the portal dashboard.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('motor_firmas', '0017_etiquetas_documentos'),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[],
            state_operations=[
                migrations.AddField(
                    model_name='directoriofirmas',
                    name='etiquetas_destacadas_documentos',
                    field=models.JSONField(blank=True, default=list),
                ),
            ],
        ),
    ]
