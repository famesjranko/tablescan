"""
urls.py
    URL Configuration for TableScan

    The `urlpatterns` list routes URLs to views. For more information please see:
        https://docs.djangoproject.com/en/3.2/topics/http/urls/
"""

from django.contrib import admin
from django.urls import path
from django.conf.urls.static import static
from django.conf.urls import url, include
from django.conf import settings

from api.views import (
    HomeView,
    ReportsListView,
    ReportDetailView,
    ReportDeleteView,
    TablePreviewView,
    DownloadAllCSVView,
    UploadAsyncView,
    TaskStatusView,
)


urlpatterns = [
    # Admin
    path("admin/", admin.site.urls),

    # API endpoints (existing)
    url(r"^api/", include("api.urls")),

    # Frontend pages
    path("", HomeView.as_view(), name="home"),
    path("reports/", ReportsListView.as_view(), name="reports_list"),
    path("reports/<int:pk>/", ReportDetailView.as_view(), name="report_detail"),
    path("reports/<int:pk>/delete/", ReportDeleteView.as_view(), name="report_delete"),

    # AJAX/API endpoints for frontend
    path("upload-async/", UploadAsyncView.as_view(), name="upload_async"),
    path("task-status/<str:task_id>/", TaskStatusView.as_view(), name="task_status"),
    path("table-preview/<int:pk>/", TablePreviewView.as_view(), name="table_preview"),
    path("reports/<int:pk>/download-csv/", DownloadAllCSVView.as_view(), name="download_all_csv"),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATICFILES_DIRS[0] if settings.STATICFILES_DIRS else None)
