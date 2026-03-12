# Squashed migration representing the pre-existing database state.
# This replaces migrations 0001 through 0021 that were lost.
# Marked as initial=True so Django can fake-apply it on existing databases.

import api.models
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    initial = True

    # This migration replaces all prior migrations (0001-0021) for the api app
    replaces = [
        ('api', '0001_initial'),
        ('api', '0002_auto_20210814_0405'),
        ('api', '0003_auto_20210814_0406'),
        ('api', '0004_alter_extracted_report'),
        ('api', '0005_auto_20210814_0412'),
        ('api', '0006_auto_20210814_1941'),
        ('api', '0007_report_f_type'),
        ('api', '0008_auto_20210823_2236'),
        ('api', '0009_auto_20210823_2252'),
        ('api', '0010_auto_20210824_2113'),
        ('api', '0011_auto_20210824_2116'),
        ('api', '0012_auto_20210824_2120'),
        ('api', '0013_alter_extracted_document'),
        ('api', '0014_alter_extracted_document'),
        ('api', '0015_alter_extracted_document'),
        ('api', '0016_auto_20210824_2133'),
        ('api', '0017_auto_20210825_0058'),
        ('api', '0018_alter_extracted_report'),
        ('api', '0019_alter_report_id'),
        ('api', '0020_alter_report_id'),
        ('api', '0021_report_zip_csv'),
    ]

    dependencies = []

    operations = [
        migrations.CreateModel(
            name='Report',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=100, null=True)),
                ('document', models.FileField(upload_to=api.models.upload_path)),
                ('zip_csv', models.FileField(null=True, upload_to='')),
                ('f_type', models.CharField(max_length=5, null=True)),
                ('total_pages', models.PositiveIntegerField(blank=True, null=True)),
                ('start_page', models.IntegerField(default=1)),
                ('end_page', models.IntegerField(default=-1)),
            ],
        ),
        migrations.CreateModel(
            name='Extracted',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('page_num', models.PositiveIntegerField(blank=True, null=True)),
                ('table_num', models.PositiveIntegerField(blank=True, null=True)),
                ('file', models.FileField(blank=True, null=True, upload_to='')),
                ('f_type', models.CharField(blank=True, choices=[('.csv', 'CSV'), ('.json', 'JSON'), ('.xlsx', 'XLSX')], max_length=5, null=True)),
                ('report', models.ForeignKey(blank=True, db_column='document', null=True, on_delete=django.db.models.deletion.CASCADE, related_name='extracted', to='api.report')),
            ],
            options={
                'ordering': ['page_num', 'table_num', 'f_type'],
            },
        ),
    ]
