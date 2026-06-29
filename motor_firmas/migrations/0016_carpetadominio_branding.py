# Generated manually for domain branding settings.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('motor_firmas', '0015_configuracionfirmex'),
    ]

    operations = [
        migrations.AddField(
            model_name='carpetadominio',
            name='brand_color',
            field=models.CharField(default='#162839', max_length=7),
        ),
        migrations.AddField(
            model_name='carpetadominio',
            name='logo_url',
            field=models.CharField(blank=True, max_length=500, null=True),
        ),
        migrations.AddField(
            model_name='carpetadominio',
            name='logo_path',
            field=models.CharField(blank=True, max_length=500, null=True),
        ),
        migrations.AddField(
            model_name='carpetadominio',
            name='updated_at',
            field=models.DateTimeField(auto_now=True),
        ),
    ]
