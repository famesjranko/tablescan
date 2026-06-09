from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('api', '0010_increase_extracted_file_max_length'),
    ]

    operations = [
        migrations.AlterField(
            model_name='extracted',
            name='bounding_box',
            field=models.JSONField(blank=True, help_text='Table location as {x1, y1, x2, y2} coordinates', null=True),
        ),
    ]
