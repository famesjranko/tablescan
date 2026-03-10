"""
admin.py
    Written by: Andrew McDonald
    Initial: 03.08.21
    Updated: 02.09.21
    version: 1.0

Logic:
    Registers database models with admin web portal

Calls on:
    models.py
"""

from django.contrib import admin

# Register your models here for access in /admin

# register Report
from .models import Report

admin.site.register(Report)

# register Extracted
from .models import Extracted

admin.site.register(Extracted)
