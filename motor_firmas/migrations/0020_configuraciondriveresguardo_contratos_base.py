# Generated migration for adding contratos_base_folder_id field.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('motor_firmas', '0019_configuraciondriveresguardo'),
    ]

    operations = [
        migrations.AddField(
            model_name='configuraciondriveresguardo',
            name='contratos_base_folder_id',
            field=models.CharField(blank=True, max_length=200, null=True),
        ),
    ]
