from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('api', '0011_alter_extracted_bounding_box'),
    ]

    operations = [
        migrations.AddField(
            model_name='report',
            name='enabled_libraries',
            field=models.JSONField(blank=True, help_text='Per-report extraction library toggles (camelot, pdfplumber, pymupdf, vision, docling); null means defaults', null=True),
        ),
    ]
