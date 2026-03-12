from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('api', '0009_increase_document_max_length'),
    ]

    operations = [
        migrations.AlterField(
            model_name='extracted',
            name='file',
            field=models.FileField(blank=True, max_length=255, null=True),
        ),
    ]
