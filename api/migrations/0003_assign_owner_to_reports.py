# Phase 3A: Data migration to assign owner to existing reports

from django.db import migrations


def assign_owner_to_reports(apps, schema_editor):
    """
    Assign all existing reports to a default user.
    Uses superuser if exists, otherwise first user, or creates a default user.
    """
    Report = apps.get_model('api', 'Report')
    User = apps.get_model('auth', 'User')

    # Get reports without an owner
    orphaned_reports = Report.objects.filter(owner__isnull=True)

    if not orphaned_reports.exists():
        return  # No orphaned reports to process

    # Try to get a superuser first
    default_user = User.objects.filter(is_superuser=True).first()

    # If no superuser, try to get the first user
    if default_user is None:
        default_user = User.objects.first()

    # If no users exist, create a default system user
    if default_user is None:
        default_user = User.objects.create(
            username='system',
            email='system@tablescan.local',
            password='',  # No usable password
            is_active=False  # Disabled account
        )

    # Assign all orphaned reports to the default user
    orphaned_reports.update(owner=default_user)


def reverse_assign_owner(apps, schema_editor):
    """
    Reverse migration: set owner to null for all reports.
    """
    Report = apps.get_model('api', 'Report')
    Report.objects.all().update(owner=None)


class Migration(migrations.Migration):

    dependencies = [
        ('api', '0002_add_owner_and_timestamps'),
    ]

    operations = [
        migrations.RunPython(assign_owner_to_reports, reverse_assign_owner),
    ]
