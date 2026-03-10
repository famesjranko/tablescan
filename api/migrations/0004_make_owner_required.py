# Phase 3A: Make owner field required after data migration

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('api', '0003_assign_owner_to_reports'),
    ]

    operations = [
        # Make owner field non-nullable (data migration already assigned owners)
        migrations.AlterField(
            model_name='report',
            name='owner',
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name='reports',
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        # Make created_at non-nullable
        migrations.AlterField(
            model_name='report',
            name='created_at',
            field=models.DateTimeField(auto_now_add=True),
        ),
        # Make updated_at non-nullable
        migrations.AlterField(
            model_name='report',
            name='updated_at',
            field=models.DateTimeField(auto_now=True),
        ),
    ]
