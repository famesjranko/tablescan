"""
permissions.py
    Phase 3C: Permission Enforcement

Logic:
    Custom permission classes for enforcing ownership-based access control

Referenced by:
    views.py
"""

from rest_framework import permissions


class IsReportOwner(permissions.BasePermission):
    """
    Custom permission to only allow owners of a report to access it.
    """

    def has_object_permission(self, request, view, obj):
        # Allow all methods for the owner
        return obj.owner == request.user
