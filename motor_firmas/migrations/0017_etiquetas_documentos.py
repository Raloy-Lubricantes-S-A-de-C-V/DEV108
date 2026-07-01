# Generated manually for document labels in the portal dashboard.

import django.utils.timezone
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('motor_firmas', '0016_carpetadominio_branding'),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[],
            state_operations=[
                migrations.AddField(
                    model_name='procesofirma',
                    name='etiqueta',
                    field=models.CharField(blank=True, default='', max_length=80),
                ),
                migrations.AddField(
                    model_name='directoriofirmas',
                    name='etiquetas_documentos',
                    field=models.JSONField(blank=True, default=list),
                ),
                migrations.CreateModel(
                    name='EtiquetaDocumento',
                    fields=[
                        ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                        ('owner_email', models.CharField(max_length=200)),
                        ('nombre', models.CharField(max_length=80)),
                        ('created_at', models.DateTimeField(default=django.utils.timezone.now)),
                    ],
                    options={
                        'unique_together': {('owner_email', 'nombre')},
                    },
                ),
            ],
        ),
    ]
