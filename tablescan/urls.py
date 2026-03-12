"""
urls.py
    URL Configuration for TableScan

    The `urlpatterns` list routes URLs to views. For more information please see:
        https://docs.djangoproject.com/en/3.2/topics/http/urls/
"""

from django.contrib import admin
from django.contrib.auth.views import LogoutView
from django.urls import path
from django.conf.urls.static import static
from django.urls import re_path, include
from django.conf import settings
from django.views.generic import TemplateView

from api.views import (
    HomeView,
    ReportsListView,
    ReportDetailView,
    ReportDeleteView,
    TablePreviewView,
    DownloadAllCSVView,
    UploadAsyncView,
    TaskStatusView,
    BookViewerView,
)


urlpatterns = [
    # Admin
    path("admin/", admin.site.urls),

    # API endpoints (existing)
    re_path(r"^api/", include("api.urls")),

    # Authentication pages (frontend)
    path("auth/login/", TemplateView.as_view(template_name="auth/login.html"), name="auth_login_page"),
    path("auth/register/", TemplateView.as_view(template_name="auth/register.html"), name="auth_register_page"),
    path("auth/logout/", LogoutView.as_view(next_page='/auth/login/'), name="logout_page"),

    # Frontend pages
    path("", HomeView.as_view(), name="home"),
    path("reports/", ReportsListView.as_view(), name="reports_list"),
    path("reports/<int:pk>/", ReportDetailView.as_view(), name="report_detail"),
    path("reports/<int:pk>/delete/", ReportDeleteView.as_view(), name="report_delete"),
    path("reports/<int:pk>/viewer/", BookViewerView.as_view(), name="book_viewer"),

    # AJAX/API endpoints for frontend
    path("upload-async/", UploadAsyncView.as_view(), name="upload_async"),
    path("task-status/<str:task_id>/", TaskStatusView.as_view(), name="task_status"),
    path("table-preview/<int:pk>/", TablePreviewView.as_view(), name="table_preview"),
    path("reports/<int:pk>/download-csv/", DownloadAllCSVView.as_view(), name="download_all_csv"),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATICFILES_DIRS[0] if settings.STATICFILES_DIRS else None)
