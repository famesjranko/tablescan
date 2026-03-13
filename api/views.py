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
from django.db.models import Count, Q
from django.db import transaction

from .permissions import IsReportOwner

from django.http import HttpResponse
from django.conf import settings

from .serializers import *
from .models import Extracted, Report, TableSelection
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

    @action(detail=True, methods=['post'], url_path='extract-selections')
    def extract_selections(self, request, pk=None):
        """
        Trigger extraction from approved TableSelection regions.

        POST /api/reports/{id}/extract-selections/
        Returns {task_id, status} for polling via /task-status/<task_id>/
        """
        from api.tasks import extract_from_selections

        report = self.get_object()

        # Check if there are any approved selections
        approved_count = report.selections.filter(status='approved').count()
        if approved_count == 0:
            return Response(
                {'error': 'No approved selections to extract'},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Queue extraction task
        task = extract_from_selections.delay(report.id)

        return Response({
            'task_id': task.id,
            'status': 'queued',
            'approved_selections': approved_count
        })

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
    Get extraction variants:        GET     api/extracted/{id}/variants/
    Switch extraction method:       POST    api/extracted/{id}/switch-method/
    """

    queryset = Extracted.objects.all()
    serializer_class = ExtractedSerializer
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ["id", "f_type"]  # test set attributes to filter by
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return Extracted.objects.filter(report__owner=self.request.user)

    @action(detail=True, methods=['get'])
    def variants(self, request, pk=None):
        """
        Get all extraction variants for this table.

        Returns cached extraction variants from all methods so the user
        can compare and switch to a different extraction result.

        GET /api/extracted/{id}/variants/
        """
        from django.core.cache import cache
        from api.tasks import _cache_key_for_selection, _deserialize_variants_from_cache

        extracted = self.get_object()

        # Check if this extraction has a linked selection
        if not extracted.selection_id:
            return Response({
                'variants': [],
                'current_method': extracted.extraction_method,
                'message': 'No variants available - extraction not from selection'
            })

        # Get cached variants
        cache_key = _cache_key_for_selection(extracted.report_id, extracted.selection_id)
        cached_data = cache.get(cache_key)

        if not cached_data:
            return Response({
                'variants': [],
                'current_method': extracted.extraction_method,
                'cache_expired': True,
                'message': 'Variants cache expired. Re-extract to see alternatives.'
            })

        # Deserialize and return variants (without dataframes)
        variants = _deserialize_variants_from_cache(cached_data)

        return Response({
            'variants': [{
                'method': v['method'],
                'score': v.get('score', 0),
                'confidence': v.get('confidence', 0),
                'rows': v.get('rows', 0),
                'cols': v.get('cols', 0),
                'warnings': v.get('warnings', []),
                'has_data': v.get('dataframe') is not None,
                'error': v.get('error'),
            } for v in variants],
            'current_method': extracted.extraction_method,
            'cache_expired': False,
        })

    @action(detail=True, methods=['post'], url_path='switch-method')
    def switch_method(self, request, pk=None):
        """
        Switch to a different extraction method from cached results.

        POST /api/extracted/{id}/switch-method/
        Body: {"method": "pdfplumber_explicit"}

        Updates the Extracted record with the chosen method's data
        and rewrites the CSV/JSON/XLSX files.
        """
        from django.core.cache import cache
        from api.tasks import _cache_key_for_selection, _deserialize_variants_from_cache
        from api.scripts.YOLOV3.predict_table import save_extraction_results, build_structure_json
        from api.scripts.extractors import ExtractionResult

        extracted = self.get_object()
        new_method = request.data.get('method')

        if not new_method:
            return Response(
                {'error': 'method parameter is required'},
                status=status.HTTP_400_BAD_REQUEST
            )

        if not extracted.selection_id:
            return Response(
                {'error': 'Cannot switch method - extraction not from selection'},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Get cached variants
        cache_key = _cache_key_for_selection(extracted.report_id, extracted.selection_id)
        cached_data = cache.get(cache_key)

        if not cached_data:
            return Response(
                {'error': 'Variants cache expired. Please re-extract to switch methods.'},
                status=status.HTTP_410_GONE
            )

        variants = _deserialize_variants_from_cache(cached_data)

        # Find the requested method
        chosen = None
        for v in variants:
            if v['method'] == new_method and v.get('dataframe') is not None:
                chosen = v
                break

        if not chosen:
            available_methods = [v['method'] for v in variants if v.get('dataframe') is not None]
            return Response(
                {'error': f'Method not found or has no data. Available: {available_methods}'},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Get file paths from current extraction
        report = extracted.report
        working_dir = Path(report.document.path).parent
        extract_dir = {
            "csv": working_dir / "csv",
            "json": working_dir / "json",
            "xlsx": working_dir / "xlsx",
        }


        # Ensure output directories exist
        for dir_path in extract_dir.values():
            dir_path.mkdir(parents=True, exist_ok=True)

        # Use transaction with select_for_update to prevent concurrent modifications
        with transaction.atomic():
            # Lock the selection to prevent race conditions
            TableSelection.objects.select_for_update().get(pk=extracted.selection_id)

            # Delete old records FIRST - django-cleanup will remove old files
            # This must happen before creating new files with same names
            Extracted.objects.filter(
                report=report,
                selection_id=extracted.selection_id
            ).delete()

            # Create new ExtractionResult and save (files now have unique paths)
            new_result = ExtractionResult(
                dataframe=chosen['dataframe'],
                confidence=chosen.get('confidence', 0),
                method=chosen['method'],
                metadata=chosen.get('metadata', {})
            )

            save_extraction_results(
                results=[new_result],
                file_path=report.document.path,
                page_num=extracted.page_num,
                report_db=report,
                extract_dir=extract_dir,
                page_type=extracted.page_type,
                selection=extracted.selection
            )

        # Query for newly created Extracted record
        new_extracted = Extracted.objects.filter(
            report=report,
            selection_id=extracted.selection_id,
            f_type='csv'
        ).first()

        # Build response with new extraction data
        response_data = {
            'status': 'ok',
            'method': new_method,
            'score': chosen.get('score', 0),
            'rows': chosen.get('rows', 0),
            'cols': chosen.get('cols', 0),
        }

        if new_extracted:
            response_data['extracted_id'] = new_extracted.id
            response_data['csv_url'] = new_extracted.file.url if new_extracted.file else None
            response_data['preview_url'] = f'/table-preview/{new_extracted.id}/'

            # Find matching JSON file
            json_extracted = Extracted.objects.filter(
                report=report,
                selection_id=extracted.selection_id,
                f_type='json'
            ).first()
            response_data['json_url'] = json_extracted.file.url if json_extracted and json_extracted.file else None

        return Response(response_data)


class TableSelectionViewSet(viewsets.ModelViewSet):
    """
    Nested viewset for TableSelection CRUD operations.

    List selections for a report:       GET     api/reports/{id}/selections/
    Filter by page:                     GET     api/reports/{id}/selections/?page_num=1
    Filter by status:                   GET     api/reports/{id}/selections/?status=pending,approved
    Create selection:                   POST    api/reports/{id}/selections/
    Update selection status:            PATCH   api/reports/{id}/selections/{sel_id}/
    Delete selection:                   DELETE  api/reports/{id}/selections/{sel_id}/
    """

    serializer_class = TableSelectionSerializer
    permission_classes = [IsAuthenticated]
    http_method_names = ['get', 'post', 'patch', 'delete', 'head', 'options']

    def get_report(self):
        """Get the parent report, ensuring ownership."""
        report_pk = self.kwargs.get('report_pk')
        try:
            report = Report.objects.get(pk=report_pk, owner=self.request.user)
        except Report.DoesNotExist:
            from rest_framework.exceptions import NotFound
            raise NotFound("Report not found.")
        return report

    def get_queryset(self):
        """Return selections for the specific report with optional filtering."""
        report = self.get_report()
        queryset = TableSelection.objects.filter(report=report)

        # Filter by page_num if provided
        page_num = self.request.query_params.get('page_num')
        if page_num:
            try:
                queryset = queryset.filter(page_num=int(page_num))
            except ValueError:
                pass

        # Filter by status if provided (comma-separated)
        status_param = self.request.query_params.get('status')
        if status_param:
            statuses = [s.strip() for s in status_param.split(',') if s.strip()]
            if statuses:
                queryset = queryset.filter(status__in=statuses)

        return queryset

    def get_object(self):
        """Get selection ensuring it belongs to the report."""
        report = self.get_report()
        sel_id = self.kwargs.get('pk')
        try:
            selection = TableSelection.objects.get(pk=sel_id, report=report)
        except TableSelection.DoesNotExist:
            from rest_framework.exceptions import NotFound
            raise NotFound("Selection not found.")
        return selection

    def get_serializer_context(self):
        """Add report to serializer context for validation."""
        context = super().get_serializer_context()
        if 'report_pk' in self.kwargs:
            context['report'] = self.get_report()
        return context

    def perform_create(self, serializer):
        """Set report from URL when creating a selection."""
        report = self.get_report()
        serializer.save(report=report)

    def partial_update(self, request, *args, **kwargs):
        """PATCH: Only allow updating the status field."""
        allowed_fields = {'status'}
        request_fields = set(request.data.keys())
        disallowed = request_fields - allowed_fields

        if disallowed:
            return Response(
                {'error': f"Only 'status' field can be updated. Disallowed fields: {list(disallowed)}"},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Validate status value
        if 'status' in request.data:
            valid_statuses = [choice[0] for choice in TableSelection.STATUS_CHOICES]
            if request.data['status'] not in valid_statuses:
                return Response(
                    {'error': f"Invalid status. Must be one of: {valid_statuses}"},
                    status=status.HTTP_400_BAD_REQUEST
                )

        return super().partial_update(request, *args, **kwargs)


class UploadView(APIView):
    """
    url based upload view with extraction function [WORKING]
    Add a new report and extract: POST api/upload/
    """

    parser_classes = (MultiPartParser, FormParser)
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
        # Annotate with table count to avoid N+1 queries
        queryset = queryset.annotate(
            table_count=Count('extracted', filter=Q(extracted__f_type='csv'))
        )
        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['search_query'] = self.request.GET.get('search', '')
        return context


class ReportDetailView(LoginRequiredMixin, DetailView):
    """Report detail page with table previews"""
    model = Report
    template_name = 'reports/detail.html'
    context_object_name = 'report'

    def get_queryset(self):
        return Report.objects.filter(owner=self.request.user)

    def get_context_data(self, **kwargs):
        import json as json_lib
        from django.core.cache import cache
        from api.tasks import _cache_key_for_selection, _deserialize_variants_from_cache

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

            # Get variants from cache if available
            variants = []
            variants_available = False
            if csv_ext.selection_id:
                cache_key = _cache_key_for_selection(report.id, csv_ext.selection_id)
                cached_data = cache.get(cache_key)
                if cached_data:
                    try:
                        all_variants = _deserialize_variants_from_cache(cached_data)
                        # Only include variants with valid data
                        variants = [{
                            'method': v['method'],
                            'score': round(v.get('score', 0), 3),
                            'confidence': round(v.get('confidence', 0), 3),
                            'rows': v.get('rows', 0),
                            'cols': v.get('cols', 0),
                            'warnings': v.get('warnings', []),
                            'has_data': v.get('dataframe') is not None and v.get('rows', 0) > 0,
                            'error': v.get('error'),
                        } for v in all_variants]
                        variants_available = True
                    except Exception:
                        pass

            table_data = {
                'id': csv_ext.id,
                'page_num': csv_ext.page_num,
                'table_num': csv_ext.table_num,
                'csv_file': csv_ext.file,
                'json_file': json_ext.file if json_ext else None,
                'extraction_method': csv_ext.extraction_method,
                'confidence_score': csv_ext.confidence_score,
                'selection_id': csv_ext.selection_id,
                'variants': variants,
                'variants_json': json_lib.dumps(variants),  # Pre-serialized for JS
                'variants_available': variants_available,
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
        report = get_object_or_404(Report, pk=pk, owner=request.user)
        report_name = report.name
        report.delete()
        messages.success(request, f'Report "{report_name}" deleted successfully.')
        return redirect('reports_list')


class TablePreviewView(LoginRequiredMixin, View):
    """AJAX endpoint to preview CSV table contents"""

    def get(self, request, pk):
        extracted = get_object_or_404(Extracted, pk=pk, report__owner=request.user)

        if not extracted.file or extracted.f_type != 'csv':
            return JsonResponse({'error': 'No CSV file available'}, status=404)

        file_path = extracted.file.path
        if not Path(file_path).exists():
            return JsonResponse({'error': f'File not found: {extracted.file.name}'}, status=404)

        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                reader = csv.reader(f)
                rows = list(reader)

            # Limit to first 20 rows for preview
            max_rows = 20
            truncated = len(rows) > max_rows + 1  # +1 for header

            headers = rows[0] if rows else []
            data_rows = rows[1:max_rows + 1] if len(rows) > 1 else []

            # Get header spans from structure_json if available
            header_spans = None
            if extracted.structure_json and 'header_spans' in extracted.structure_json:
                header_spans = extracted.structure_json['header_spans']

            return JsonResponse({
                'headers': headers,
                'rows': data_rows,
                'truncated': truncated,
                'total_rows': len(rows) - 1,
                'header_spans': header_spans
            })
        except Exception as e:
            return JsonResponse({'error': str(e)}, status=500)


class DownloadAllCSVView(View):
    """Download all CSV files for a report as a ZIP"""

    def get(self, request, pk):
        report = get_object_or_404(Report, pk=pk, owner=request.user)
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
        from api.tasks import extract_tables_task, detect_tables_for_review

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
        strip_text = request.POST.get('strip_text', '\n')
        merge_headers = request.POST.get('merge_headers', 'on') == 'on'
        extraction_mode = request.POST.get('extraction_mode', 'auto')

        # Get library toggles (all enabled by default)
        enabled_libraries = {
            'camelot': request.POST.get('use_camelot', 'on') == 'on',
            'pdfplumber': request.POST.get('use_pdfplumber', 'on') == 'on',
            'pymupdf': request.POST.get('use_pymupdf', 'on') == 'on',
            'vision': request.POST.get('use_vision', 'on') == 'on',
        }

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
        file_path = report.document.path
        file_name = Path(file_path).name

        # Update report with name, type, and extraction mode
        # Use the original filename (without extension) as the display name
        report.name = Path(file_name).stem
        report.f_type = Path(file_name).suffix.lstrip('.')
        report.extraction_mode = extraction_mode

        # Get total page count for proper multi-page handling
        try:
            pdf_doc = fitz.open(file_path)
            report.total_pages = len(pdf_doc)
            pdf_doc.close()
        except Exception:
            # If we can't read pages, default to 1 (will be corrected during extraction)
            report.total_pages = 1

        report.save()

        # Clean empty directories
        media_root_dir = settings.MEDIA_ROOT
        walk = list(os.walk(media_root_dir))
        for path, _, _ in walk[::-1]:
            if len(os.listdir(path)) == 0:
                Path.rmdir(Path(path))

        # Handle different extraction modes
        if extraction_mode == 'manual':
            # Manual mode: set status and redirect immediately to viewer
            report.extraction_status = 'pending_review'
            report.save(update_fields=['extraction_status'])
            return JsonResponse({
                'report_id': report.id,
                'status': 'ready',
                'redirect_url': f'/reports/{report.id}/viewer/'
            })

        elif extraction_mode == 'review':
            # Review mode: run detection task, then redirect to viewer
            task = detect_tables_for_review.delay(report.id)
            return JsonResponse({
                'task_id': task.id,
                'report_id': report.id,
                'status': 'queued'
            })

        else:
            # Auto mode (default): full extraction
            task = extract_tables_task.delay(
                report.id,
                file_path,
                start_page,
                end_page,
                enabled_libraries=enabled_libraries,
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


class BookViewerView(LoginRequiredMixin, View):
    """Book viewer for manual table selection and review"""

    def get(self, request, pk):
        report = get_object_or_404(Report, pk=pk)

        # Verify ownership
        if report.owner != request.user:
            return HttpResponse('Forbidden', status=403)

        return render(request, 'reports/book_viewer.html', {
            'report': report,
        })
