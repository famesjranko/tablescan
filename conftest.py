"""
Pytest configuration for Django tests.

This file is automatically loaded by pytest and configures
Django settings before any tests run.
"""

import os
import django
from django.conf import settings


def pytest_configure():
    """Configure Django settings before tests run."""
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'tablescan.settings')
    django.setup()
