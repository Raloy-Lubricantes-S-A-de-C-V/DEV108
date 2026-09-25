# Generated manually for editable Drive archive folders.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('motor_firmas', '0018_etiquetas_destacadas_documentos'),
    ]

    operations = [
        migrations.CreateModel(
            name='ConfiguracionDriveResguardo',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('root_folder_id', models.CharField(max_length=200)),
                ('formatos_folder_id', models.CharField(max_length=200)),
                ('pdfs_folder_id', models.CharField(max_length=200)),
                ('api_pdfs_folder_id', models.CharField(max_length=200)),
                ('updated_at', models.DateTimeField(auto_now=True)),
            ],
        ),
    ]
