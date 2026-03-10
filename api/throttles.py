"""
throttles.py
    Rate limiting classes for the API

Logic:
    Custom throttle classes for controlling API request rates

Referenced by:
    views.py
"""

from rest_framework.throttling import UserRateThrottle


class UploadRateThrottle(UserRateThrottle):
    """
    Throttle for PDF upload endpoints.
    Limits uploads to prevent abuse and manage server resources.
    """
    scope = 'upload'
    rate = '10/hour'


class BurstRateThrottle(UserRateThrottle):
    """
    Throttle for short burst protection.
    Prevents rapid-fire requests within a short time window.
    """
    scope = 'burst'
    rate = '5/minute'
