from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('api', '0010_increase_extracted_file_max_length'),
    ]

    operations = [
        migrations.AddField(
            model_name='report',
            name='enabled_libraries',
            field=models.JSONField(blank=True, help_text='Per-report extraction library toggles (camelot, pdfplumber, pymupdf, vision, docling); null means defaults', null=True),
        ),
    ]
