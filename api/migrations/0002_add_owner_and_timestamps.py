# Phase 3A: Add owner and timestamps to Report model

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('api', '0001_initial_squashed'),
    ]

    operations = [
        # Add owner field as nullable initially
        migrations.AddField(
            model_name='report',
            name='owner',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name='reports',
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        # Add created_at timestamp (nullable for existing data)
        migrations.AddField(
            model_name='report',
            name='created_at',
            field=models.DateTimeField(auto_now_add=True, null=True),
        ),
        # Add updated_at timestamp (nullable for existing data)
        migrations.AddField(
            model_name='report',
            name='updated_at',
            field=models.DateTimeField(auto_now=True, null=True),
        ),
    ]
