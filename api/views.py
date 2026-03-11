"""
views.py
    Written by: Andrew McDonald
    Initial: 03.08.21
    Updated: 02.09.21
    version: 1.5

Logic:
    Handles API http requests

Calls on:
    serializers.py
    models.py
    
Referenced by:
    urls.py
"""

from rest_framework.parsers import MultiPartParser, FormParser
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework import viewsets
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.decorators import action

from django_filters.rest_framework import DjangoFilterBackend

from .permissions import IsReportOwner

from django.http import HttpResponse
from django.conf import settings

from .throttles import UploadRateThrottle, BurstRateThrottle

from .serializers import *
from .models import Extracted, Report
from api.scripts import table_extract
from api.scripts.logging import Logging
import fitz  # PyMuPDF

from pathlib import Path, PurePath
import datetime as date
import os

# processing time
from timeit import default_timer as timer
from humanfriendly import format_timespan

from rest_framework.renderers import JSONRenderer


def validate_pdf_file(document):
    """
    Validate uploaded file is a valid PDF.
    Returns (is_valid, error_message) tuple.
    """
    # Check file size
    max_size = getattr(settings, 'MAX_UPLOAD_SIZE', 50 * 1024 * 1024)  # Default 50MB
    if document.size > max_size:
        max_mb = max_size // (1024 * 1024)
        return False, f'File size exceeds maximum allowed size of {max_mb}MB'

    # Check PDF magic number (first 5 bytes should be %PDF-)
    document.seek(0)
    header = document.read(5)
    document.seek(0)  # Reset file pointer for further processing

    if header != b'%PDF-':
        return False, 'Invalid PDF file: file does not have a valid PDF header'

    return True, None


class ReportViewSet(viewsets.ModelViewSet):
    """
    serializer based viewset for Report model [WORKING]

    Upload and Extract a report:    POST    api/upload/
    List all reports:               GET     api/reports/
    Retrieve report by id:          GET     api/reports/{id}/
    Retrieve report by name:        GET     api/reports/?name=
    Update existing report:         PUT     api/reports/{id}/
    Update part of report:          PATCH   api/reports/{id}/
    Remove report by id:            DELETE  api/reports/{id}/
    Remove report by name:          DELETE  api/reports/?name=
    Get PDF metadata:               GET     api/reports/{id}/metadata/
    """

    queryset = Report.objects.all()
    serializer_class = ReportSerializer
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ["id", "name"]  # test set attributes to filter by
    permission_classes = [IsAuthenticated, IsReportOwner]

    def get_queryset(self):
        return Report.objects.filter(owner=self.request.user)

    @action(detail=True, methods=['get'])
    def metadata(self, request, pk=None):
        """
        Get PDF page count and dimensions for viewer initialization.
        Returns {total_pages, pages: [{page_num, width, height, rotation}, ...]}
        """
        report = self.get_object()

        if not report.document:
            return Response(
                {'error': 'No document attached to this report'},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            doc = fitz.open(report.document.path)
        except Exception as e:
            return Response(
                {'error': f'Failed to open PDF: {str(e)}'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

        try:
            pages = []
            for page_num in range(len(doc)):
                page = doc[page_num]
                rotation = page.rotation

                # Get dimensions from media box
                width = page.rect.width
                height = page.rect.height

                # Swap width/height for 90 or 270 degree rotation
                if rotation in (90, 270):
                    width, height = height, width

                pages.append({
                    'page_num': page_num + 1,  # 1-indexed for user-facing API
                    'width': round(width, 2),
                    'height': round(height, 2),
                    'rotation': rotation
                })

            return Response({
                'total_pages': len(doc),
                'pages': pages
            })
        finally:
            doc.close()


class ExtractedViewSet(viewsets.ModelViewSet):
    """
    serializer based viewset for Extracted model [WORKING]

    List all extractions:           GET     api/extracted/
    Retrieve extraction by id:      GET     api/extracted/{id}/
    Update existing extraction:     PUT     api/extracted/{id}/
    Update part of extraction:      PATCH   api/extracted/{id}/
    Remove extraction by id:        DELETE  api/extracted/{id}/
    Remove extraction by name:      DELETE  api/extracted/?name=
    """

    queryset = Extracted.objects.all()
    serializer_class = ExtractedSerializer
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ["id", "f_type"]  # test set attributes to filter by
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return Extracted.objects.filter(report__owner=self.request.user)


class UploadView(APIView):
    """
    url based upload view with extraction function [WORKING]
    Add a new report and extract: POST api/upload/
    """

    parser_classes = (MultiPartParser, FormParser)
    throttle_classes = [UploadRateThrottle, BurstRateThrottle]
    permission_classes = [IsAuthenticated]

    def post(self, request, *args, **kwargs):
        # Validate file exists
        if 'document' not in request.FILES:
            return Response(
                {'error': 'No file uploaded'},
                status=status.HTTP_400_BAD_REQUEST
            )

        document = request.FILES['document']

        # Validate PDF file (size and magic number)
        is_valid, error_message = validate_pdf_file(document)
        if not is_valid:
            return Response(
                {'error': error_message},
                status=status.HTTP_400_BAD_REQUEST
            )

        report_serializer = ReportSerializer(
            data=request.data, context={"request": request}
        )

        # check for valid request
        if not report_serializer.is_valid():
            return Response(report_serializer, status=status.HTTP_400_BAD_REQUEST)

        # create log object
        log = Logging()

        # create Report database model instance with owner
        report = report_serializer.save(owner=request.user)

        # uploaded file url location
        file_url = report_serializer.data["document"]

        # get pages info
        start_page = report_serializer.data["start_page"]
        end_page = report_serializer.data["end_page"]

        # django upload root dir
        media_root_dir = settings.MEDIA_ROOT

        # build file path name and path location
        full_path = Path(file_url)
        base_dir = full_path.parts[3]
        file_name = full_path.name
        file_path = PurePath(media_root_dir, base_dir, file_name)

        # update report name and file_type fields
        report.name = base_dir
        report.f_type = file_name.split(".")[1]
        report.save()

        # clean media root of any empty folders
        log.output("INFO", "cleaning /documents of empty directories")

        walk = list(os.walk(media_root_dir))
        for path, _, _ in walk[::-1]:
            if len(os.listdir(path)) == 0:
                Path.rmdir(Path(path))

        # log output
        log.output("INFO", "/documents cleaned")
        log.output("INFO", "sending file for extraction...")

        # start stopwatch
        start = timer()

        try:
            # run extraction script, set output_type: ['json','csv','xlsx', 'all']
            # 'all' currently only set to json, csv
            # returns dictionary
            extracted = table_extract.extract(file_path, start_page, end_page, report_id=report.id)

        except Exception as e:
            error_output = "".join(["Extraction script: ", str(e)])
            log.output("ERROR", error_output)
            return HttpResponse(error_output, status=500)  # 500 Internal Server Error

        # end stopwatch and log time
        end = timer()
        log.output("INFO", f'extraction completed in" {format_timespan(end - start)}')

        return Response(extracted, status=status.HTTP_201_CREATED)


# =============================================================================
# Frontend Views
# =============================================================================

from django.shortcuts import render, redirect, get_object_or_404
from django.views.generic import ListView, DetailView, View
from django.http import JsonResponse, FileResponse
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from collections import defaultdict
import csv
import json
import zipfile
import io

from celery.result import AsyncResult


class HomeView(LoginRequiredMixin, View):
    """Upload page - main entry point for the frontend"""

    def get(self, request):
        recent_reports = Report.objects.filter(owner=request.user).order_by('-id')[:5]
        return render(request, 'upload.html', {
            'recent_reports': recent_reports
        })


class ReportsListView(LoginRequiredMixin, ListView):
    """List all reports with search and pagination"""
    model = Report
    template_name = 'reports/list.html'
    context_object_name = 'reports'
    paginate_by = 12

    def get_queryset(self):
        queryset = Report.objects.filter(owner=self.request.user).order_by('-id')
        search = self.request.GET.get('search', '')
        if search:
            queryset = queryset.filter(name__icontains=search)
        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['search_query'] = self.request.GET.get('search', '')
        # Add table count to each report
        for report in context['reports']:
            report.table_count = report.extracted.filter(f_type='csv').count()
        return context


class ReportDetailView(LoginRequiredMixin, DetailView):
    """Report detail page with table previews"""
    model = Report
    template_name = 'reports/detail.html'
    context_object_name = 'report'

    def get_queryset(self):
        return Report.objects.filter(owner=self.request.user)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        report = self.object

        # Get all extracted tables grouped by page
        csv_extracts = report.extracted.filter(f_type='csv').order_by('page_num', 'table_num')
        json_extracts = report.extracted.filter(f_type='json')

        # Create a combined table list with both CSV and JSON references
        tables = []
        tables_by_page = defaultdict(list)

        for csv_ext in csv_extracts:
            # Find matching JSON file
            json_ext = json_extracts.filter(
                page_num=csv_ext.page_num,
                table_num=csv_ext.table_num
            ).first()

            table_data = {
                'id': csv_ext.id,
                'page_num': csv_ext.page_num,
                'table_num': csv_ext.table_num,
                'csv_file': csv_ext.file,
                'json_file': json_ext.file if json_ext else None,
            }
            tables.append(table_data)
            tables_by_page[csv_ext.page_num].append(table_data)

        context['tables'] = tables
        context['tables_by_page'] = dict(tables_by_page)
        context['csv_files'] = csv_extracts

        return context


class ReportDeleteView(View):
    """Delete a report and its extracted files"""

    def post(self, request, pk):
        report = get_object_or_404(Report, pk=pk)
        report_name = report.name
        report.delete()
        messages.success(request, f'Report "{report_name}" deleted successfully.')
        return redirect('reports_list')


class TablePreviewView(View):
    """AJAX endpoint to preview CSV table contents"""

    def get(self, request, pk):
        extracted = get_object_or_404(Extracted, pk=pk)

        if not extracted.file or extracted.f_type != 'csv':
            return JsonResponse({'error': 'No CSV file available'}, status=404)

        try:
            with open(extracted.file.path, 'r', encoding='utf-8') as f:
                reader = csv.reader(f)
                rows = list(reader)

            # Limit to first 20 rows for preview
            max_rows = 20
            truncated = len(rows) > max_rows + 1  # +1 for header

            headers = rows[0] if rows else []
            data_rows = rows[1:max_rows + 1] if len(rows) > 1 else []

            return JsonResponse({
                'headers': headers,
                'rows': data_rows,
                'truncated': truncated,
                'total_rows': len(rows) - 1
            })
        except Exception as e:
            return JsonResponse({'error': str(e)}, status=500)


class DownloadAllCSVView(View):
    """Download all CSV files for a report as a ZIP"""

    def get(self, request, pk):
        report = get_object_or_404(Report, pk=pk)
        csv_files = report.extracted.filter(f_type='csv')

        if not csv_files.exists():
            messages.error(request, 'No CSV files available for download.')
            return redirect('report_detail', pk=pk)

        # Create ZIP file in memory
        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:
            for ext in csv_files:
                if ext.file:
                    try:
                        file_name = f"page{ext.page_num}_table{ext.table_num}.csv"
                        zip_file.write(ext.file.path, file_name)
                    except Exception:
                        pass

        zip_buffer.seek(0)
        response = FileResponse(
            zip_buffer,
            as_attachment=True,
            filename=f'{report.name}_tables.zip'
        )
        return response


class UploadAsyncView(LoginRequiredMixin, View):
    """Async upload endpoint that queues extraction via Celery"""

    def post(self, request):
        from api.tasks import extract_tables_task

        # Apply rate limiting
        upload_throttle = UploadRateThrottle()
        burst_throttle = BurstRateThrottle()

        # Check upload rate limit
        if not upload_throttle.allow_request(request, self):
            wait_time = upload_throttle.wait()
            return JsonResponse({
                'error': f'Upload rate limit exceeded. Try again in {int(wait_time)} seconds.'
            }, status=429)

        # Check burst rate limit
        if not burst_throttle.allow_request(request, self):
            wait_time = burst_throttle.wait()
            return JsonResponse({
                'error': f'Too many requests. Try again in {int(wait_time)} seconds.'
            }, status=429)

        # Validate file exists
        if 'document' not in request.FILES:
            return JsonResponse({'error': 'No file uploaded'}, status=400)

        document = request.FILES['document']

        # Validate file extension
        if not document.name.lower().endswith('.pdf'):
            return JsonResponse({'error': 'Only PDF files are supported'}, status=400)

        # Validate PDF file (size and magic number)
        is_valid, error_message = validate_pdf_file(document)
        if not is_valid:
            return JsonResponse({'error': error_message}, status=400)

        # Get page range
        start_page = int(request.POST.get('start_page', 1))
        end_page = int(request.POST.get('end_page', -1))

        # Get extraction options
        flavor = request.POST.get('camelot_flavor', 'auto')
        row_tol = int(request.POST.get('row_tol', 2))
        strip_text = request.POST.get('strip_text', '\n')
        merge_headers = request.POST.get('merge_headers', 'on') == 'on'

        # Create report using serializer
        report_serializer = ReportSerializer(
            data={
                'document': document,
                'start_page': start_page,
                'end_page': end_page
            },
            context={'request': request}
        )

        if not report_serializer.is_valid():
            return JsonResponse({'error': 'Invalid data'}, status=400)

        report = report_serializer.save(owner=request.user)

        # Get file path from saved report
        file_url = report_serializer.data['document']
        full_path = Path(file_url)
        base_dir = full_path.parts[3]
        file_name = full_path.name
        file_path = str(PurePath(settings.MEDIA_ROOT, base_dir, file_name))

        # Update report with name and type
        report.name = base_dir
        report.f_type = file_name.split('.')[1]
        report.save()

        # Clean empty directories
        media_root_dir = settings.MEDIA_ROOT
        walk = list(os.walk(media_root_dir))
        for path, _, _ in walk[::-1]:
            if len(os.listdir(path)) == 0:
                Path.rmdir(Path(path))

        # Queue extraction task with options
        task = extract_tables_task.delay(
            report.id,
            file_path,
            start_page,
            end_page,
            flavor=flavor,
            row_tol=row_tol,
            strip_text=strip_text,
            merge_headers=merge_headers
        )

        return JsonResponse({
            'task_id': task.id,
            'report_id': report.id,
            'status': 'queued'
        })


class TaskStatusView(View):
    """Check status of a Celery task"""

    def get(self, request, task_id):
        result = AsyncResult(task_id)

        response_data = {
            'task_id': task_id,
            'state': result.state,
        }

        if result.state == 'PROGRESS':
            response_data['progress'] = result.info
        elif result.state == 'SUCCESS':
            response_data['result'] = result.result
        elif result.state == 'FAILURE':
            response_data['error'] = str(result.result)

        return JsonResponse(response_data)
