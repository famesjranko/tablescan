"""
urls.py
    Written by: Andrew McDonald
    Initial: 03.08.21
    Updated: 02.09.21
    version: 1.3

Logic:
    Handles http request addressing
"""

from django.urls import include, path
from rest_framework import routers
from . import views
from .views import *
from .views import UploadView
from .views_auth import RegisterView, LoginView, LogoutView

from rest_framework_simplejwt.views import TokenRefreshView

from django.urls import re_path
from django.conf.urls.static import static
from django.conf import settings


# setup api router and register models, has automatic URL routing.
router = routers.DefaultRouter()
router.register(r"reports", views.ReportViewSet, basename='api-reports')
router.register(r"extracted", views.ExtractedViewSet, basename='api-extracted')

# Nested router for table selections under reports
selections_list = views.TableSelectionViewSet.as_view({
    'get': 'list',
    'post': 'create'
})
selections_detail = views.TableSelectionViewSet.as_view({
    'get': 'retrieve',
    'patch': 'partial_update',
    'delete': 'destroy'
})

# Authentication URL patterns
auth_urlpatterns = [
    path('register/', RegisterView.as_view(), name='auth_register'),
    path('login/', LoginView.as_view(), name='auth_login'),
    path('logout/', LogoutView.as_view(), name='auth_logout'),
    path('refresh/', TokenRefreshView.as_view(), name='auth_refresh'),
]

# API url paths
api_urlpatterns = [
    path("", include(router.urls)),
    path("auth/", include(auth_urlpatterns)),
    re_path(r"^upload/$", UploadView.as_view(), name="api_upload"),
    # Nested table selections endpoints
    path("reports/<int:report_pk>/selections/", selections_list, name="report-selections-list"),
    path("reports/<int:report_pk>/selections/<int:pk>/", selections_detail, name="report-selections-detail"),
]

# For backwards compatibility, also export as urlpatterns
urlpatterns = api_urlpatterns + static(
    settings.MEDIA_URL, document_root=settings.MEDIA_ROOT
)  # attach media storage for file access
