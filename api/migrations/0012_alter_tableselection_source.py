from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('api', '0011_add_enabled_libraries_to_report'),
    ]

    operations = [
        migrations.AlterField(
            model_name='tableselection',
            name='source',
            field=models.CharField(choices=[('yolo', 'YOLO Detection'), ('manual', 'Manual Selection'), ('auto', 'Automatic Extraction')], default='manual', max_length=10),
        ),
    ]
