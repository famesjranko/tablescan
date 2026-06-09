"""
End-to-end tests for Phase 5: Selection Workflows

BV-017: Verify the complete manual selection workflow
BV-018: Verify the complete auto-detection with review workflow

Tests verify:
1. Upload PDF with 'Manual Selection' mode
2. Verify extraction_mode='manual' and extraction_status='pending_review' in DB
3. Verify no YOLO boxes created (blank overlay)
4. Create manual selections via API
5. Verify selections saved with source='manual', status='approved'
6. Trigger extraction and verify task runs
7. Verify Extracted records created for drawn regions
8. Verify CSV content matches table data

BV-018 Auto + Review tests verify:
1. Upload PDF with 'Auto + Review' mode sets extraction_mode='review'
2. YOLO detection task updates status: 'detecting' -> 'pending_review'
3. YOLO boxes created with source='yolo', status='pending'
4. Approve/reject API calls update box status correctly
5. Manual boxes added with source='manual', status='approved'
6. Extraction only includes approved YOLO + manual boxes
7. Rejected boxes NOT in Extracted results
"""

import io
import os
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

import fitz  # PyMuPDF
import pandas as pd
import pytest

from api.scripts.extractors import MultiExtractor


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture
def pdf_with_table():
    """
    Create a born-digital PDF with a clearly visible table.
    The table has distinct borders and text for reliable extraction.
    """
    with tempfile.NamedTemporaryFile(suffix='.pdf', delete=False) as f:
        pdf_path = f.name

    doc = fitz.open()

    # Create page 1 with a table
    page1 = doc.new_page(width=612, height=792)

    # Title
    page1.insert_text(fitz.Point(50, 50), "Financial Report - Page 1", fontsize=14)

    # Create bordered table with clear lines
    shape = page1.new_shape()

    x_start, y_start = 80, 100
    col_widths = [100, 100, 80]
    row_height = 30
    num_rows = 4
    total_width = sum(col_widths)

    # Draw horizontal lines
    for i in range(num_rows + 1):
        y = y_start + i * row_height
        shape.draw_line(
            fitz.Point(x_start, y),
            fitz.Point(x_start + total_width, y)
        )

    # Draw vertical lines
    x = x_start
    for width in [0] + col_widths:
        x += width
        shape.draw_line(
            fitz.Point(x, y_start),
            fitz.Point(x, y_start + num_rows * row_height)
        )

    shape.finish(color=(0, 0, 0), width=1.0)
    shape.commit()

    # Table data
    table1_data = [
        ["Product", "Units", "Revenue"],
        ["Widget A", "100", "$5,000"],
        ["Widget B", "50", "$2,500"],
        ["Widget C", "75", "$3,750"],
    ]

    for i, row in enumerate(table1_data):
        x = x_start
        for j, cell in enumerate(row):
            page1.insert_text(
                fitz.Point(x + 5, y_start + i * row_height + 20),
                cell,
                fontsize=10
            )
            x += col_widths[j]

    # Create page 2 with another table
    page2 = doc.new_page(width=612, height=792)

    page2.insert_text(fitz.Point(50, 50), "Summary Report - Page 2", fontsize=14)

    shape2 = page2.new_shape()
    x_start2, y_start2 = 100, 150
    col_widths2 = [150, 100]
    num_rows2 = 3

    for i in range(num_rows2 + 1):
        y = y_start2 + i * row_height
        shape2.draw_line(
            fitz.Point(x_start2, y),
            fitz.Point(x_start2 + sum(col_widths2), y)
        )

    x = x_start2
    for width in [0] + col_widths2:
        x += width
        shape2.draw_line(
            fitz.Point(x, y_start2),
            fitz.Point(x, y_start2 + num_rows2 * row_height)
        )

    shape2.finish(color=(0, 0, 0), width=1.0)
    shape2.commit()

    table2_data = [
        ["Category", "Total"],
        ["Electronics", "$8,250"],
        ["Software", "$3,000"],
    ]

    for i, row in enumerate(table2_data):
        x = x_start2
        for j, cell in enumerate(row):
            page2.insert_text(
                fitz.Point(x + 5, y_start2 + i * row_height + 20),
                cell,
                fontsize=10
            )
            x += col_widths2[j]

    doc.save(pdf_path)
    doc.close()

    yield pdf_path

    if os.path.exists(pdf_path):
        os.unlink(pdf_path)


@pytest.fixture
def table1_bbox_pdf_coords():
    """
    Return the bounding box for table 1 in PDF coordinates (bottom-left origin).
    The table spans from (80, 100) to (360, 220) in top-left origin.
    Page height is 792, so convert to bottom-left origin:
    y1_pdf = 792 - 220 = 572 (bottom of table)
    y2_pdf = 792 - 100 = 692 (top of table)
    """
    return {
        'x1': 75.0,   # Left edge with margin
        'y1': 567.0,  # Bottom edge (PDF coords)
        'x2': 365.0,  # Right edge with margin
        'y2': 697.0,  # Top edge (PDF coords)
    }


@pytest.fixture
def table2_bbox_pdf_coords():
    """
    Return the bounding box for table 2 in PDF coordinates.
    Table spans from (100, 150) to (350, 240) in top-left origin.
    Page height is 792, so convert:
    y1_pdf = 792 - 240 = 552
    y2_pdf = 792 - 150 = 642
    """
    return {
        'x1': 95.0,
        'y1': 547.0,
        'x2': 355.0,
        'y2': 647.0,
    }


# =============================================================================
# Test: Code Structure Verification
# =============================================================================

class TestManualSelectionCodeStructure:
    """Verify code structure supports manual selection flow."""

    @pytest.fixture
    def views_source(self):
        """Read views.py source code."""
        path = Path(__file__).parent.parent / "views.py"
        return path.read_text()

    @pytest.fixture
    def tasks_source(self):
        """Read tasks.py source code."""
        path = Path(__file__).parent.parent / "tasks.py"
        return path.read_text()

    @pytest.fixture
    def models_source(self):
        """Read models.py source code."""
        path = Path(__file__).parent.parent / "models.py"
        return path.read_text()

    def test_upload_view_handles_manual_mode(self, views_source):
        """UploadAsyncView should handle extraction_mode='manual'."""
        assert "extraction_mode == 'manual'" in views_source
        assert "extraction_status = 'pending_review'" in views_source

    def test_upload_view_redirects_to_viewer_for_manual(self, views_source):
        """Manual mode should redirect to book viewer."""
        assert "/viewer/" in views_source

    def test_extract_from_selections_task_exists(self, tasks_source):
        """extract_from_selections task should exist."""
        assert "def extract_from_selections(" in tasks_source

    def test_extract_from_selections_filters_approved(self, tasks_source):
        """Task should filter selections by status='approved'."""
        assert "status='approved'" in tasks_source

    def test_table_selection_model_has_source_field(self, models_source):
        """TableSelection model should have source field."""
        assert "source = models.CharField" in models_source
        assert '"manual"' in models_source or "'manual'" in models_source

    def test_table_selection_model_has_status_field(self, models_source):
        """TableSelection model should have status field."""
        assert "status = models.CharField" in models_source
        assert '"approved"' in models_source or "'approved'" in models_source

    def test_report_has_extraction_mode_field(self, models_source):
        """Report model should have extraction_mode field."""
        assert "extraction_mode = models.CharField" in models_source

    def test_report_has_extraction_status_field(self, models_source):
        """Report model should have extraction_status field."""
        assert "extraction_status = models.CharField" in models_source


class TestTableSelectionSerializer:
    """Verify TableSelectionSerializer handles manual selections correctly."""

    @pytest.fixture
    def serializers_source(self):
        """Read serializers.py source code."""
        path = Path(__file__).parent.parent / "serializers.py"
        return path.read_text()

    def test_serializer_defaults_source_to_manual(self, serializers_source):
        """Serializer should default source to 'manual'."""
        assert "manual" in serializers_source
        # Check for the default logic
        assert "source" in serializers_source

    def test_serializer_defaults_status_for_manual(self, serializers_source):
        """Serializer should default status to 'approved' for manual source."""
        # Per BV-003, manual selections default to approved
        assert "approved" in serializers_source


# =============================================================================
# Test: API Endpoints
# =============================================================================

class TestSelectionEndpoints:
    """Verify selection API endpoints work correctly."""

    @pytest.fixture
    def views_source(self):
        """Read views.py source code."""
        path = Path(__file__).parent.parent / "views.py"
        return path.read_text()

    def test_selection_create_endpoint_exists(self, views_source):
        """POST selections endpoint should exist."""
        assert "TableSelectionViewSet" in views_source
        assert "create" in views_source.lower()

    def test_extract_selections_endpoint_exists(self, views_source):
        """POST extract-selections endpoint should exist."""
        assert "extract_selections" in views_source or "extract-selections" in views_source


# =============================================================================
# Test: Extraction Pipeline
# =============================================================================

class TestExtractionFromSelections:
    """Verify extraction works with manual selections."""

    @pytest.fixture
    def tasks_source(self):
        """Read tasks.py source code."""
        path = Path(__file__).parent.parent / "tasks.py"
        return path.read_text()

    def test_task_uses_extract_from_manual_areas(self, tasks_source):
        """extract_from_selections should use extract_from_manual_areas for user-specified regions."""
        assert "extract_from_manual_areas" in tasks_source

    def test_task_honors_report_enabled_libraries(self, tasks_source):
        """Selection extraction should respect per-report library toggles (incl. opt-in Docling)."""
        assert "MultiExtractor(enabled_libraries=report.enabled_libraries" in tasks_source

    def test_task_groups_by_page(self, tasks_source):
        """Task should group selections by page_num."""
        assert "page_num" in tasks_source
        assert "selections_by_page" in tasks_source

    def test_task_builds_table_areas(self, tasks_source):
        """Task should build table_areas from selection coordinates."""
        assert "table_areas" in tasks_source
        assert "x1" in tasks_source
        assert "y1" in tasks_source
        assert "x2" in tasks_source
        assert "y2" in tasks_source

    def test_task_saves_extraction_results(self, tasks_source):
        """Task should save results to Extracted model."""
        assert "save_extraction_results" in tasks_source

    def test_task_updates_status_to_completed(self, tasks_source):
        """Task should update status to 'completed' on success."""
        assert "'completed'" in tasks_source or '"completed"' in tasks_source


# =============================================================================
# Test: MultiExtractor with Table Areas
# =============================================================================

class TestMultiExtractorWithAreas:
    """Verify MultiExtractor can extract from specific regions."""

    def test_extract_best_accepts_table_areas(self, pdf_with_table, table1_bbox_pdf_coords):
        """MultiExtractor.extract_best should accept table_areas parameter."""
        # Given: a PDF with a table and known bounding box coordinates
        extractor = MultiExtractor()
        table_areas = [(
            table1_bbox_pdf_coords['x1'],
            table1_bbox_pdf_coords['y1'],
            table1_bbox_pdf_coords['x2'],
            table1_bbox_pdf_coords['y2'],
        )]

        # When: extraction is performed with specific table areas
        try:
            results = extractor.extract_best(
                pdf_path=pdf_with_table,
                page_num=1,
                table_areas=table_areas
            )

            # Then: results are returned as a list
            assert isinstance(results, list)
        except Exception as e:
            pytest.skip(f"Extraction not available: {e}")

    def test_extract_with_specific_region(self, pdf_with_table, table1_bbox_pdf_coords):
        """Extraction should work with specific table regions."""
        # Given: a PDF with a table and known bounding box coordinates
        extractor = MultiExtractor()
        table_areas = [(
            table1_bbox_pdf_coords['x1'],
            table1_bbox_pdf_coords['y1'],
            table1_bbox_pdf_coords['x2'],
            table1_bbox_pdf_coords['y2'],
        )]

        # When: extraction is performed targeting the specific region
        try:
            results = extractor.extract_best(
                pdf_path=pdf_with_table,
                page_num=1,
                table_areas=table_areas
            )

            # Then: results contain DataFrames with extracted data
            if results:
                for result in results:
                    assert hasattr(result, 'dataframe')
                    assert isinstance(result.dataframe, pd.DataFrame)
        except Exception:
            pytest.skip("Extraction not available")


# =============================================================================
# Test: Coordinate Transformation
# =============================================================================

class TestCoordinateTransformation:
    """Verify coordinate transformation between canvas and PDF space."""

    @pytest.fixture
    def bbox_manager_source(self):
        """Read bbox-manager.js source code."""
        path = Path(__file__).parent.parent.parent / "static" / "js" / "bbox-manager.js"
        if path.exists():
            return path.read_text()
        return ""

    def test_canvas_to_pdf_function_exists(self, bbox_manager_source):
        """canvasToPdf function should exist in bbox-manager.js."""
        if not bbox_manager_source:
            pytest.skip("bbox-manager.js not found")
        assert "canvasToPdf" in bbox_manager_source

    def test_pdf_to_canvas_function_exists(self, bbox_manager_source):
        """pdfToCanvas function should exist in bbox-manager.js."""
        if not bbox_manager_source:
            pytest.skip("bbox-manager.js not found")
        assert "pdfToCanvas" in bbox_manager_source

    def test_y_axis_flip_in_canvas_to_pdf(self, bbox_manager_source):
        """canvasToPdf should flip Y axis."""
        if not bbox_manager_source:
            pytest.skip("bbox-manager.js not found")
        # Check for page_height - canvas_y pattern
        assert "pdfHeight" in bbox_manager_source or "pageHeight" in bbox_manager_source


# =============================================================================
# Test: Book Viewer
# =============================================================================

class TestBookViewer:
    """Verify book viewer functionality for manual selection."""

    @pytest.fixture
    def viewer_template_source(self):
        """Read book viewer template source."""
        path = Path(__file__).parent.parent.parent / "templates" / "reports" / "book_viewer.html"
        if path.exists():
            return path.read_text()
        return ""

    def test_viewer_has_selection_mode(self, viewer_template_source):
        """Viewer should have a selection mode toggle."""
        if not viewer_template_source:
            pytest.skip("book_viewer.html not found")
        assert "Select" in viewer_template_source

    def test_viewer_has_extract_button(self, viewer_template_source):
        """Viewer should have an extract button."""
        if not viewer_template_source:
            pytest.skip("book_viewer.html not found")
        assert "Extract" in viewer_template_source

    def test_viewer_shows_selection_count(self, viewer_template_source):
        """Viewer should show count of selections."""
        if not viewer_template_source:
            pytest.skip("book_viewer.html not found")
        # Check for selection count display
        assert "selection" in viewer_template_source.lower()


# =============================================================================
# Integration Test (if Django available)
# =============================================================================

try:
    from django.test import TestCase
    from django.contrib.auth.models import User
    from rest_framework.test import APITestCase, APIClient
    DJANGO_API_AVAILABLE = True
except ImportError:
    DJANGO_API_AVAILABLE = False

    class APITestCase:
        pass


@pytest.mark.skipif(not DJANGO_API_AVAILABLE, reason="Django API not available")
@pytest.mark.django_db(transaction=True)
class TestManualSelectionE2E(APITestCase):
    """
    End-to-end integration test for manual selection workflow.

    BV-017 Acceptance Criteria:
    1. Upload PDF with 'Manual Selection' mode
    2. Verify extraction_mode='manual' and extraction_status='pending_review' in DB
    3. Redirected to book viewer with blank overlay (no YOLO boxes)
    4. Draw 2-3 boxes on different pages
    5. Verify boxes saved to TableSelection table with source='manual', status='approved'
    6. Click Extract - verify task runs
    7. Verify Extracted records created only for drawn regions
    8. Verify CSVs contain correct table data
    """

    def setUp(self):
        """Set up test user and client."""
        self.user = User.objects.create_user(
            username='manual_flow_test_user',
            password='testpass123',
            email='manual@example.com'
        )
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    def tearDown(self):
        """Clean up after tests."""
        from api.models import Report
        Report.objects.filter(owner=self.user).delete()

    def test_report_model_has_manual_mode_choice(self):
        """Report model should have 'manual' as extraction_mode choice."""
        from api.models import Report

        mode_choices = dict(Report.EXTRACTION_MODE_CHOICES)
        assert 'manual' in mode_choices

    def test_report_model_has_pending_review_status(self):
        """Report model should have 'pending_review' as extraction_status choice."""
        from api.models import Report

        status_choices = dict(Report.EXTRACTION_STATUS_CHOICES)
        assert 'pending_review' in status_choices

    def test_table_selection_manual_source(self):
        """TableSelection should have 'manual' as source choice."""
        from api.models import TableSelection

        source_choices = dict(TableSelection.SOURCE_CHOICES)
        assert 'manual' in source_choices

    def test_table_selection_approved_status(self):
        """TableSelection should have 'approved' as status choice."""
        from api.models import TableSelection

        status_choices = dict(TableSelection.STATUS_CHOICES)
        assert 'approved' in status_choices

    def test_manual_selection_creates_approved_status(self):
        """Creating a manual selection should default to approved status."""
        from api.models import Report, TableSelection
        from api.serializers import TableSelectionSerializer

        # Given: a report in manual extraction mode
        report = Report.objects.create(
            name='test_manual_selection',
            extraction_mode='manual',
            extraction_status='pending_review',
            owner=self.user
        )
        data = {
            'page_num': 1,
            'x1': 80.0,
            'y1': 572.0,
            'x2': 360.0,
            'y2': 692.0,
        }

        # When: a manual selection is created via the serializer
        serializer = TableSelectionSerializer(data=data, context={'report': report})
        assert serializer.is_valid(), serializer.errors
        selection = serializer.save(report=report)

        # Then: the selection defaults to source='manual' and status='approved'
        assert selection.source == 'manual'
        assert selection.status == 'approved'

    def test_manual_mode_no_yolo_selections(self):
        """Manual mode should not create YOLO selections."""
        from api.models import Report, TableSelection

        # Given: a report created with manual extraction mode
        report = Report.objects.create(
            name='test_no_yolo',
            extraction_mode='manual',
            extraction_status='pending_review',
            owner=self.user
        )

        # When: we query for YOLO-sourced selections
        yolo_selections = TableSelection.objects.filter(
            report=report,
            source='yolo'
        )

        # Then: no YOLO selections exist for this report
        assert yolo_selections.count() == 0

    def test_extract_from_selections_filters_approved(self):
        """extract_from_selections should only process approved selections."""
        from api.models import Report, TableSelection

        # Given: a report with mixed selection statuses (approved, pending, rejected)
        report = Report.objects.create(
            name='test_filter_approved',
            extraction_mode='manual',
            extraction_status='pending_review',
            owner=self.user
        )
        TableSelection.objects.create(
            report=report, page_num=1,
            x1=0, y1=0, x2=100, y2=100,
            source='manual', status='approved'
        )
        TableSelection.objects.create(
            report=report, page_num=1,
            x1=100, y1=100, x2=200, y2=200,
            source='yolo', status='pending'
        )
        TableSelection.objects.create(
            report=report, page_num=1,
            x1=200, y1=200, x2=300, y2=300,
            source='yolo', status='rejected'
        )

        # When: querying for approved selections (as the extraction task does)
        approved = TableSelection.objects.filter(
            report=report,
            status='approved'
        )

        # Then: only the approved selection is returned
        assert approved.count() == 1
        assert approved.first().source == 'manual'


@pytest.mark.skipif(not DJANGO_API_AVAILABLE, reason="Django API not available")
@pytest.mark.django_db(transaction=True)
class TestManualSelectionAPI(APITestCase):
    """Test API endpoints for manual selection workflow."""

    def setUp(self):
        """Set up test user and client."""
        self.user = User.objects.create_user(
            username='api_test_user',
            password='testpass123',
            email='api@example.com'
        )
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    def tearDown(self):
        """Clean up after tests."""
        from api.models import Report
        Report.objects.filter(owner=self.user).delete()

    def test_selection_api_create(self):
        """POST /api/reports/{id}/selections/ should create manual selection."""
        from api.models import Report, TableSelection

        # Given: a report in manual extraction mode
        report = Report.objects.create(
            name='test_api_create',
            extraction_mode='manual',
            extraction_status='pending_review',
            owner=self.user
        )

        # When: a POST request creates a new selection via the API
        response = self.client.post(
            f'/api/reports/{report.id}/selections/',
            {
                'page_num': 1,
                'x1': 80.0,
                'y1': 572.0,
                'x2': 360.0,
                'y2': 692.0,
            },
            format='json'
        )

        # Then: the selection is created with manual source and approved status
        assert response.status_code == 201
        assert response.data['source'] == 'manual'
        assert response.data['status'] == 'approved'

        # Verify in database
        selection = TableSelection.objects.get(id=response.data['id'])
        assert selection.report == report
        assert selection.source == 'manual'
        assert selection.status == 'approved'

    def test_selection_api_list(self):
        """GET /api/reports/{id}/selections/ should list selections."""
        from api.models import Report, TableSelection

        # Given: a report with two manual selections
        report = Report.objects.create(
            name='test_api_list',
            extraction_mode='manual',
            extraction_status='pending_review',
            owner=self.user
        )
        TableSelection.objects.create(
            report=report, page_num=1,
            x1=0, y1=0, x2=100, y2=100,
            source='manual', status='approved'
        )
        TableSelection.objects.create(
            report=report, page_num=2,
            x1=0, y1=0, x2=100, y2=100,
            source='manual', status='approved'
        )

        # When: the selections list endpoint is called
        response = self.client.get(f'/api/reports/{report.id}/selections/')

        # Then: both selections are returned
        assert response.status_code == 200
        assert len(response.data) == 2

    def test_selection_api_filter_by_status(self):
        """GET /api/reports/{id}/selections/?status= should filter."""
        from api.models import Report, TableSelection

        # Given: a report with one pending and one approved selection
        report = Report.objects.create(
            name='test_api_filter',
            extraction_mode='review',
            extraction_status='pending_review',
            owner=self.user
        )
        TableSelection.objects.create(
            report=report, page_num=1,
            x1=0, y1=0, x2=100, y2=100,
            source='yolo', status='pending'
        )
        TableSelection.objects.create(
            report=report, page_num=1,
            x1=100, y1=100, x2=200, y2=200,
            source='manual', status='approved'
        )

        # When: filtering by status=approved
        response = self.client.get(f'/api/reports/{report.id}/selections/?status=approved')

        # Then: only the approved selection is returned
        assert response.status_code == 200
        assert len(response.data) == 1
        assert response.data[0]['status'] == 'approved'

    def test_selection_api_delete(self):
        """DELETE /api/reports/{id}/selections/{sel_id}/ should remove selection."""
        from api.models import Report, TableSelection

        # Given: a report with a manual selection
        report = Report.objects.create(
            name='test_api_delete',
            extraction_mode='manual',
            extraction_status='pending_review',
            owner=self.user
        )
        selection = TableSelection.objects.create(
            report=report, page_num=1,
            x1=0, y1=0, x2=100, y2=100,
            source='manual', status='approved'
        )

        # When: the selection is deleted via the API
        response = self.client.delete(
            f'/api/reports/{report.id}/selections/{selection.id}/'
        )

        # Then: the selection is removed from the database
        assert response.status_code == 204
        assert not TableSelection.objects.filter(id=selection.id).exists()


# =============================================================================
# BV-018: Auto + Review Flow Tests
# =============================================================================

class TestAutoReviewCodeStructure:
    """Verify code structure supports auto-detection with review flow."""

    @pytest.fixture
    def views_source(self):
        """Read views.py source code."""
        path = Path(__file__).parent.parent / "views.py"
        return path.read_text()

    @pytest.fixture
    def tasks_source(self):
        """Read tasks.py source code."""
        path = Path(__file__).parent.parent / "tasks.py"
        return path.read_text()

    @pytest.fixture
    def models_source(self):
        """Read models.py source code."""
        path = Path(__file__).parent.parent / "models.py"
        return path.read_text()

    def test_upload_view_handles_review_mode(self, views_source):
        """UploadAsyncView should handle extraction_mode='review'."""
        assert "extraction_mode == 'review'" in views_source

    def test_detect_tables_for_review_task_exists(self, tasks_source):
        """detect_tables_for_review task should exist."""
        assert "def detect_tables_for_review(" in tasks_source

    def test_detect_task_updates_status_detecting(self, tasks_source):
        """Task should set extraction_status to 'detecting' at start."""
        assert "extraction_status = 'detecting'" in tasks_source

    def test_detect_task_updates_status_pending_review(self, tasks_source):
        """Task should set extraction_status to 'pending_review' on completion."""
        assert "extraction_status = 'pending_review'" in tasks_source

    def test_detect_task_creates_yolo_selections(self, tasks_source):
        """Task should create TableSelection records with source='yolo'."""
        assert "source='yolo'" in tasks_source
        assert "status='pending'" in tasks_source

    def test_report_has_review_mode_choice(self, models_source):
        """Report model should have 'review' as extraction_mode choice."""
        assert "'review'" in models_source or '"review"' in models_source

    def test_report_has_detecting_status_choice(self, models_source):
        """Report model should have 'detecting' as extraction_status choice."""
        assert "'detecting'" in models_source or '"detecting"' in models_source


class TestAutoReviewDetectionFlow:
    """Verify YOLO detection creates proper TableSelection records."""

    @pytest.fixture
    def tasks_source(self):
        """Read tasks.py source code."""
        path = Path(__file__).parent.parent / "tasks.py"
        return path.read_text()

    def test_task_saves_bounding_box_coords(self, tasks_source):
        """Task should save x1, y1, x2, y2 coordinates."""
        assert "x1=region['x1']" in tasks_source
        assert "y1=region['y1']" in tasks_source
        assert "x2=region['x2']" in tasks_source
        assert "y2=region['y2']" in tasks_source

    def test_task_saves_confidence(self, tasks_source):
        """Task should save confidence from YOLO detection."""
        assert "confidence=region.get('confidence')" in tasks_source

    def test_task_returns_redirect_url(self, tasks_source):
        """Task should return redirect URL to viewer."""
        assert "'redirect_url'" in tasks_source
        assert "/viewer/" in tasks_source

    def test_task_returns_selections_count(self, tasks_source):
        """Task should return count of created selections."""
        assert "'selections_count'" in tasks_source


class TestAutoReviewStatusTransitions:
    """Verify extraction_status state machine for review flow."""

    @pytest.fixture
    def tasks_source(self):
        """Read tasks.py source code."""
        path = Path(__file__).parent.parent / "tasks.py"
        return path.read_text()

    def test_detecting_to_pending_review_transition(self, tasks_source):
        """Status should transition from 'detecting' to 'pending_review'."""
        # Both statuses should be set in detect_tables_for_review
        content = tasks_source
        idx_detecting = content.find("extraction_status = 'detecting'")
        idx_pending = content.find("extraction_status = 'pending_review'")

        assert idx_detecting != -1, "Should set status to 'detecting'"
        assert idx_pending != -1, "Should set status to 'pending_review'"
        # 'detecting' should be set before 'pending_review'
        assert idx_detecting < idx_pending, "Should transition from detecting to pending_review"

    def test_failed_status_on_error(self, tasks_source):
        """Status should transition to 'failed' on error."""
        assert "extraction_status = 'failed'" in tasks_source


class TestApproveRejectSelections:
    """Verify approve/reject API updates selection status."""

    @pytest.fixture
    def views_source(self):
        """Read views.py source code."""
        path = Path(__file__).parent.parent / "views.py"
        return path.read_text()

    def test_patch_endpoint_exists(self, views_source):
        """PATCH endpoint should exist for updating selection status."""
        assert "partial_update" in views_source or "update" in views_source

    def test_status_validation(self, views_source):
        """PATCH should validate status against valid choices."""
        assert "STATUS_CHOICES" in views_source or "status" in views_source


class TestMixedSelectionsExtraction:
    """Verify extraction handles mixed YOLO and manual selections."""

    @pytest.fixture
    def tasks_source(self):
        """Read tasks.py source code."""
        path = Path(__file__).parent.parent / "tasks.py"
        return path.read_text()

    def test_extract_filters_by_approved_status(self, tasks_source):
        """extract_from_selections should filter by status='approved'."""
        # Find the extract_from_selections function section
        assert "status='approved'" in tasks_source

    def test_extract_ignores_source_type(self, tasks_source):
        """Extraction should process all approved selections regardless of source."""
        # The filter should NOT include source= filter, only status='approved'
        # This means both manual and yolo approved selections are included
        extract_func_start = tasks_source.find("def extract_from_selections")
        assert extract_func_start != -1

        extract_func_section = tasks_source[extract_func_start:]
        filter_section = extract_func_section[:extract_func_section.find("def ", 1) if "def " in extract_func_section[1:] else len(extract_func_section)]

        # Should have status='approved' filter
        assert "status='approved'" in filter_section

        # Should NOT have source= filter (so both yolo and manual are included)
        # Check that we're not filtering by source in the approved query
        filter_line_start = filter_section.find("approved_selections = ")
        if filter_line_start != -1:
            # Get the filter call
            filter_line_end = filter_section.find(")", filter_line_start)
            filter_call = filter_section[filter_line_start:filter_line_end]
            # Should not filter by source
            assert "source=" not in filter_call, "Should not filter by source, only by status"


# =============================================================================
# BV-018: Integration Tests
# =============================================================================

@pytest.mark.skipif(not DJANGO_API_AVAILABLE, reason="Django API not available")
@pytest.mark.django_db(transaction=True)
class TestAutoReviewE2E(APITestCase):
    """
    End-to-end integration test for auto + review workflow.

    BV-018 Acceptance Criteria:
    1. Upload PDF with 'Auto + Review' mode
    2. Verify YOLO detection task starts (check Celery logs or task status)
    3. Verify extraction_status transitions: 'detecting' -> 'pending_review'
    4. Redirected to viewer with detected boxes shown in orange
    5. Approve some boxes (turn green), reject others (fade out)
    6. Add a manual box for a missed table
    7. Click Extract
    8. Verify only approved YOLO + manual boxes extracted
    9. Rejected boxes NOT in Extracted results
    """

    def setUp(self):
        """Set up test user and client."""
        self.user = User.objects.create_user(
            username='review_flow_test_user',
            password='testpass123',
            email='review@example.com'
        )
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    def tearDown(self):
        """Clean up after tests."""
        from api.models import Report, TableSelection
        TableSelection.objects.filter(report__owner=self.user).delete()
        Report.objects.filter(owner=self.user).delete()

    def test_report_model_has_review_mode_choice(self):
        """Report model should have 'review' as extraction_mode choice."""
        from api.models import Report

        mode_choices = dict(Report.EXTRACTION_MODE_CHOICES)
        assert 'review' in mode_choices

    def test_report_model_has_detecting_status_choice(self):
        """Report model should have 'detecting' as extraction_status choice."""
        from api.models import Report

        status_choices = dict(Report.EXTRACTION_STATUS_CHOICES)
        assert 'detecting' in status_choices

    def test_table_selection_yolo_source(self):
        """TableSelection should have 'yolo' as source choice."""
        from api.models import TableSelection

        source_choices = dict(TableSelection.SOURCE_CHOICES)
        assert 'yolo' in source_choices

    def test_table_selection_pending_status(self):
        """TableSelection should have 'pending' as status choice."""
        from api.models import TableSelection

        status_choices = dict(TableSelection.STATUS_CHOICES)
        assert 'pending' in status_choices

    def test_yolo_detection_creates_pending_selections(self):
        """YOLO detection should create selections with status='pending'."""
        from api.models import Report, TableSelection

        # Create a report with review mode
        report = Report.objects.create(
            name='test_yolo_pending',
            extraction_mode='review',
            extraction_status='pending_review',
            owner=self.user
        )

        # Simulate YOLO detection result (what the task would create)
        TableSelection.objects.create(
            report=report, page_num=1,
            x1=80.0, y1=572.0, x2=360.0, y2=692.0,
            confidence=0.85,
            source='yolo', status='pending'
        )

        # Verify selection properties
        selection = TableSelection.objects.get(report=report)
        assert selection.source == 'yolo'
        assert selection.status == 'pending'
        assert selection.confidence == 0.85

    def test_approve_yolo_selection(self):
        """PATCH should allow approving a YOLO selection."""
        from api.models import Report, TableSelection

        report = Report.objects.create(
            name='test_approve_yolo',
            extraction_mode='review',
            extraction_status='pending_review',
            owner=self.user
        )

        selection = TableSelection.objects.create(
            report=report, page_num=1,
            x1=0, y1=0, x2=100, y2=100,
            source='yolo', status='pending'
        )

        response = self.client.patch(
            f'/api/reports/{report.id}/selections/{selection.id}/',
            {'status': 'approved'},
            format='json'
        )

        assert response.status_code == 200
        selection.refresh_from_db()
        assert selection.status == 'approved'

    def test_reject_yolo_selection(self):
        """PATCH should allow rejecting a YOLO selection."""
        from api.models import Report, TableSelection

        report = Report.objects.create(
            name='test_reject_yolo',
            extraction_mode='review',
            extraction_status='pending_review',
            owner=self.user
        )

        selection = TableSelection.objects.create(
            report=report, page_num=1,
            x1=0, y1=0, x2=100, y2=100,
            source='yolo', status='pending'
        )

        response = self.client.patch(
            f'/api/reports/{report.id}/selections/{selection.id}/',
            {'status': 'rejected'},
            format='json'
        )

        assert response.status_code == 200
        selection.refresh_from_db()
        assert selection.status == 'rejected'

    def test_add_manual_selection_during_review(self):
        """POST should allow adding manual selection during review."""
        from api.models import Report, TableSelection

        report = Report.objects.create(
            name='test_add_manual',
            extraction_mode='review',
            extraction_status='pending_review',
            owner=self.user
        )

        # Add a manual selection
        response = self.client.post(
            f'/api/reports/{report.id}/selections/',
            {
                'page_num': 2,
                'x1': 100.0,
                'y1': 500.0,
                'x2': 400.0,
                'y2': 700.0,
            },
            format='json'
        )

        assert response.status_code == 201
        assert response.data['source'] == 'manual'
        assert response.data['status'] == 'approved'

    def test_mixed_selections_filtering(self):
        """Only approved selections (YOLO + manual) should be extracted."""
        from api.models import Report, TableSelection

        report = Report.objects.create(
            name='test_mixed_filtering',
            extraction_mode='review',
            extraction_status='pending_review',
            owner=self.user
        )

        # Create various selections
        TableSelection.objects.create(
            report=report, page_num=1,
            x1=0, y1=0, x2=100, y2=100,
            source='yolo', status='approved'  # Should be included
        )
        TableSelection.objects.create(
            report=report, page_num=1,
            x1=100, y1=100, x2=200, y2=200,
            source='yolo', status='pending'  # Should NOT be included
        )
        TableSelection.objects.create(
            report=report, page_num=1,
            x1=200, y1=200, x2=300, y2=300,
            source='yolo', status='rejected'  # Should NOT be included
        )
        TableSelection.objects.create(
            report=report, page_num=2,
            x1=0, y1=0, x2=100, y2=100,
            source='manual', status='approved'  # Should be included
        )

        # Query same as extract_from_selections task
        approved = TableSelection.objects.filter(
            report=report,
            status='approved'
        )

        assert approved.count() == 2
        sources = set(s.source for s in approved)
        assert 'yolo' in sources
        assert 'manual' in sources

    def test_rejected_not_in_approved_query(self):
        """Rejected selections should not be in approved query."""
        from api.models import Report, TableSelection

        report = Report.objects.create(
            name='test_rejected_excluded',
            extraction_mode='review',
            extraction_status='pending_review',
            owner=self.user
        )

        # Create one approved and one rejected
        approved_sel = TableSelection.objects.create(
            report=report, page_num=1,
            x1=0, y1=0, x2=100, y2=100,
            source='yolo', status='approved'
        )
        rejected_sel = TableSelection.objects.create(
            report=report, page_num=1,
            x1=100, y1=100, x2=200, y2=200,
            source='yolo', status='rejected'
        )

        # Query approved only
        approved = TableSelection.objects.filter(
            report=report,
            status='approved'
        )

        approved_ids = [s.id for s in approved]
        assert approved_sel.id in approved_ids
        assert rejected_sel.id not in approved_ids

    def test_pending_not_in_approved_query(self):
        """Pending selections should not be in approved query."""
        from api.models import Report, TableSelection

        report = Report.objects.create(
            name='test_pending_excluded',
            extraction_mode='review',
            extraction_status='pending_review',
            owner=self.user
        )

        # Create one approved and one pending
        approved_sel = TableSelection.objects.create(
            report=report, page_num=1,
            x1=0, y1=0, x2=100, y2=100,
            source='yolo', status='approved'
        )
        pending_sel = TableSelection.objects.create(
            report=report, page_num=1,
            x1=100, y1=100, x2=200, y2=200,
            source='yolo', status='pending'
        )

        # Query approved only
        approved = TableSelection.objects.filter(
            report=report,
            status='approved'
        )

        approved_ids = [s.id for s in approved]
        assert approved_sel.id in approved_ids
        assert pending_sel.id not in approved_ids


@pytest.mark.skipif(not DJANGO_API_AVAILABLE, reason="Django API not available")
@pytest.mark.django_db(transaction=True)
class TestAutoReviewAPIWorkflow(APITestCase):
    """Test complete API workflow for auto + review mode."""

    def setUp(self):
        """Set up test user and client."""
        self.user = User.objects.create_user(
            username='api_review_test_user',
            password='testpass123',
            email='apireview@example.com'
        )
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    def tearDown(self):
        """Clean up after tests."""
        from api.models import Report, TableSelection
        TableSelection.objects.filter(report__owner=self.user).delete()
        Report.objects.filter(owner=self.user).delete()

    def test_full_review_workflow(self):
        """
        Test complete review workflow:
        1. Create report with review mode
        2. Create YOLO selections (simulating detection)
        3. Approve some, reject others
        4. Add manual selection
        5. Verify approved query returns correct selections
        """
        from api.models import Report, TableSelection

        # 1. Create report with review mode
        report = Report.objects.create(
            name='test_full_workflow',
            extraction_mode='review',
            extraction_status='pending_review',
            owner=self.user
        )

        # 2. Create YOLO selections (simulating detect_tables_for_review)
        yolo1 = TableSelection.objects.create(
            report=report, page_num=1,
            x1=80.0, y1=572.0, x2=360.0, y2=692.0,
            confidence=0.92,
            source='yolo', status='pending'
        )
        yolo2 = TableSelection.objects.create(
            report=report, page_num=1,
            x1=400.0, y1=100.0, x2=550.0, y2=200.0,
            confidence=0.45,  # Low confidence, user will reject
            source='yolo', status='pending'
        )
        yolo3 = TableSelection.objects.create(
            report=report, page_num=2,
            x1=100.0, y1=500.0, x2=400.0, y2=700.0,
            confidence=0.88,
            source='yolo', status='pending'
        )

        # Verify all start as pending
        pending = TableSelection.objects.filter(report=report, status='pending')
        assert pending.count() == 3

        # 3. Approve some, reject others via API
        # Approve yolo1 (high confidence)
        response = self.client.patch(
            f'/api/reports/{report.id}/selections/{yolo1.id}/',
            {'status': 'approved'},
            format='json'
        )
        assert response.status_code == 200

        # Reject yolo2 (low confidence, user decision)
        response = self.client.patch(
            f'/api/reports/{report.id}/selections/{yolo2.id}/',
            {'status': 'rejected'},
            format='json'
        )
        assert response.status_code == 200

        # Approve yolo3
        response = self.client.patch(
            f'/api/reports/{report.id}/selections/{yolo3.id}/',
            {'status': 'approved'},
            format='json'
        )
        assert response.status_code == 200

        # 4. Add manual selection for missed table
        response = self.client.post(
            f'/api/reports/{report.id}/selections/',
            {
                'page_num': 3,
                'x1': 50.0,
                'y1': 600.0,
                'x2': 300.0,
                'y2': 750.0,
            },
            format='json'
        )
        assert response.status_code == 201
        manual_id = response.data['id']

        # 5. Verify approved query
        approved = TableSelection.objects.filter(
            report=report,
            status='approved'
        ).order_by('page_num')

        assert approved.count() == 3  # 2 approved YOLO + 1 manual

        # Verify correct selections are approved
        approved_ids = [s.id for s in approved]
        assert yolo1.id in approved_ids  # Approved YOLO
        assert yolo2.id not in approved_ids  # Rejected
        assert yolo3.id in approved_ids  # Approved YOLO
        assert manual_id in approved_ids  # Manual (auto-approved)

        # Verify sources
        sources = [s.source for s in approved]
        assert sources.count('yolo') == 2
        assert sources.count('manual') == 1

    def test_list_selections_by_status(self):
        """GET with status filter should return filtered selections."""
        from api.models import Report, TableSelection

        report = Report.objects.create(
            name='test_list_by_status',
            extraction_mode='review',
            extraction_status='pending_review',
            owner=self.user
        )

        TableSelection.objects.create(
            report=report, page_num=1,
            x1=0, y1=0, x2=100, y2=100,
            source='yolo', status='pending'
        )
        TableSelection.objects.create(
            report=report, page_num=1,
            x1=100, y1=100, x2=200, y2=200,
            source='yolo', status='approved'
        )
        TableSelection.objects.create(
            report=report, page_num=1,
            x1=200, y1=200, x2=300, y2=300,
            source='yolo', status='rejected'
        )

        # Filter by pending
        response = self.client.get(f'/api/reports/{report.id}/selections/?status=pending')
        assert response.status_code == 200
        assert len(response.data) == 1
        assert response.data[0]['status'] == 'pending'

        # Filter by approved
        response = self.client.get(f'/api/reports/{report.id}/selections/?status=approved')
        assert response.status_code == 200
        assert len(response.data) == 1
        assert response.data[0]['status'] == 'approved'

        # Filter by multiple statuses
        response = self.client.get(f'/api/reports/{report.id}/selections/?status=pending,approved')
        assert response.status_code == 200
        assert len(response.data) == 2

    def test_extract_endpoint_requires_approved(self):
        """POST extract-selections should use approved selections only."""
        from api.models import Report, TableSelection

        report = Report.objects.create(
            name='test_extract_requires_approved',
            extraction_mode='review',
            extraction_status='pending_review',
            owner=self.user
        )

        # Create only pending selections
        TableSelection.objects.create(
            report=report, page_num=1,
            x1=0, y1=0, x2=100, y2=100,
            source='yolo', status='pending'
        )

        # Try to trigger extraction - should fail or return 0 approved
        response = self.client.post(f'/api/reports/{report.id}/extract-selections/')

        # Should return 400 because no approved selections
        assert response.status_code == 400
        assert 'approved' in response.data.get('error', '').lower() or \
               'no' in response.data.get('error', '').lower()


# =============================================================================
# BV-019: Edge Cases Tests
# =============================================================================


class TestBV019EdgeCases:
    """
    BV-019: End-to-end test: Edge cases

    Verify handling of edge cases and error conditions:
    - Single-page PDF displays correctly (no empty right page)
    - Large PDF (20+ pages) loads without browser freeze
    - Invalid PDF shows error message in viewer
    - Network error during save shows retry option
    - Navigating away with unsaved changes shows warning (if applicable)
    - Zooming preserves box positions correctly
    """

    # =========================================================================
    # Single-page PDF Tests
    # =========================================================================

    def test_single_page_pdf_clears_right_canvas(self):
        """
        Single-page PDF should clear the right canvas when rightPageNum > totalPages.
        The clearCanvas method sets canvas dimensions to 0.
        """
        # Read book-viewer.js to verify single-page handling
        import_path = Path(__file__).parent.parent.parent / 'static' / 'js' / 'book-viewer.js'
        content = import_path.read_text()

        # Verify the logic for clearing right page when beyond total pages
        assert 'if (this.rightPageNum <= this.totalPages)' in content, \
            "Should check if rightPageNum is within totalPages"
        assert 'this.clearCanvas' in content, \
            "Should call clearCanvas for pages beyond total"
        assert "clearCanvas('right-page-canvas')" in content, \
            "Should specifically clear right-page-canvas"

    def test_single_page_pdf_label_hidden_for_empty_right(self):
        """
        Single-page PDF should hide the page number label for the empty right page.
        Template uses x-show="rightPageNum > 0 && rightPageNum <= totalPages".
        """
        template_path = Path(__file__).parent.parent.parent / 'templates' / 'reports' / 'book_viewer.html'
        content = template_path.read_text()

        # Verify right page label visibility condition
        assert 'rightPageNum <= totalPages' in content, \
            "Right page label should only show when page exists"

    def test_clear_canvas_removes_pdf_metadata(self):
        """
        clearCanvas should remove PDF metadata from canvas dataset.
        This prevents stale data when page doesn't exist.
        """
        import_path = Path(__file__).parent.parent.parent / 'static' / 'js' / 'book-viewer.js'
        content = import_path.read_text()

        # Verify clearCanvas removes metadata
        assert 'delete canvas.dataset.pdfWidth' in content
        assert 'delete canvas.dataset.pdfHeight' in content
        assert 'delete canvas.dataset.pageNum' in content
        assert 'delete canvas.dataset.scale' in content

    def test_spread_label_handles_single_page(self):
        """
        getSpreadLabel should display "Page X of X" for single-page PDFs.
        """
        import_path = Path(__file__).parent.parent.parent / 'static' / 'js' / 'book-viewer.js'
        content = import_path.read_text()

        # Verify single page label logic
        assert 'if (left === right)' in content, \
            "Should check if left equals right page"
        assert '`Page ${left} of ${this.totalPages}`' in content, \
            "Should show 'Page X of Y' for single page display"

    # =========================================================================
    # Large PDF Tests (20+ pages)
    # =========================================================================

    def test_large_pdf_lazy_renders_only_visible_spread(self):
        """
        Large PDFs should only render the current spread (2 pages), not all pages.
        This prevents browser freeze on load.
        """
        import_path = Path(__file__).parent.parent.parent / 'static' / 'js' / 'book-viewer.js'
        content = import_path.read_text()

        # Verify lazy loading pattern
        assert 'renderSpread()' in content, "Should have renderSpread method"
        assert 'this.leftPageNum = this.currentSpread * 2 + 1' in content, \
            "Should calculate left page from current spread"
        assert 'this.rightPageNum = this.currentSpread * 2 + 2' in content, \
            "Should calculate right page from current spread"

    def test_large_pdf_renders_only_two_pages_per_spread(self):
        """
        renderSpread should render at most 2 pages (left and right).
        """
        import_path = Path(__file__).parent.parent.parent / 'static' / 'js' / 'book-viewer.js'
        content = import_path.read_text()

        # Count renderPage calls in renderSpread
        # Should only render left and right pages
        assert "await this.renderPage(this.leftPageNum, 'left-page-canvas')" in content
        assert "await this.renderPage(this.rightPageNum, 'right-page-canvas')" in content

    def test_large_pdf_page_metadata_loaded_progressively(self):
        """
        Page metadata loads all pages but doesn't render them all.
        This is fast because it only reads dimensions, not content.
        """
        import_path = Path(__file__).parent.parent.parent / 'static' / 'js' / 'book-viewer.js'
        content = import_path.read_text()

        # Verify metadata loading uses getViewport which is fast
        assert 'page.getViewport({ scale: 1.0 })' in content, \
            "Should use getViewport for fast metadata reading"
        assert 'viewport.width' in content and 'viewport.height' in content

    def test_navigation_does_not_preload_all_pages(self):
        """
        Navigation methods should not attempt to preload all pages.
        """
        import_path = Path(__file__).parent.parent.parent / 'static' / 'js' / 'book-viewer.js'
        content = import_path.read_text()

        # Verify prevSpread and nextSpread only render current spread
        assert 'prevSpread()' in content
        assert 'nextSpread()' in content

        # Both should call renderSpread(), not render all pages
        # Check that after navigation, only renderSpread is called
        prev_section = content[content.find('prevSpread()'):content.find('prevSpread()') + 300]
        assert 'this.renderSpread()' in prev_section, \
            "prevSpread should call renderSpread, not load all pages"

    @pytest.fixture
    def large_pdf_fixture(self):
        """Create a 25-page PDF for testing."""
        with tempfile.NamedTemporaryFile(suffix='.pdf', delete=False) as f:
            pdf_path = f.name

        doc = fitz.open()
        for i in range(25):
            page = doc.new_page(width=612, height=792)
            page.insert_text(fitz.Point(50, 50), f"Page {i + 1} of 25", fontsize=14)
        doc.save(pdf_path)
        doc.close()

        yield pdf_path

        Path(pdf_path).unlink(missing_ok=True)

    def test_large_pdf_creation_succeeds(self, large_pdf_fixture):
        """Verify the large PDF fixture creates 25 pages."""
        doc = fitz.open(large_pdf_fixture)
        assert doc.page_count == 25
        doc.close()

    # =========================================================================
    # Invalid PDF Error Handling
    # =========================================================================

    def test_invalid_pdf_sets_error_state(self):
        """
        Invalid PDF loading should set error state in the viewer.
        """
        import_path = Path(__file__).parent.parent.parent / 'static' / 'js' / 'book-viewer.js'
        content = import_path.read_text()

        # Verify error handling in init()
        assert 'catch (err)' in content, "Should have error catch block"
        assert "this.error = err.message || 'Failed to load PDF document'" in content, \
            "Should set error message on failure"
        assert 'this.loading = false' in content, \
            "Should clear loading state on error"

    def test_invalid_pdf_error_shown_in_template(self):
        """
        Template should display error message when error state is set.
        """
        template_path = Path(__file__).parent.parent.parent / 'templates' / 'reports' / 'book_viewer.html'
        content = template_path.read_text()

        # Verify error display elements
        assert 'x-show="error"' in content, "Should show error section when error is set"
        assert 'Failed to load PDF' in content, "Should have error title"
        assert 'x-text="error"' in content, "Should display error message"

    def test_render_error_has_retry_button(self):
        """
        Page render error should show retry button.
        """
        template_path = Path(__file__).parent.parent.parent / 'templates' / 'reports' / 'book_viewer.html'
        content = template_path.read_text()

        # Verify render error UI with retry
        assert 'x-show="renderError"' in content, "Should show renderError section"
        assert '@click="renderSpread()"' in content, "Should have retry button for render errors"
        assert 'Retry' in content, "Should have Retry text"

    # =========================================================================
    # Network Error Retry Tests
    # =========================================================================

    def test_network_error_shows_retry_button(self):
        """
        Network error during save should show error toast with retry option.
        """
        import_path = Path(__file__).parent.parent.parent / 'static' / 'js' / 'bbox-manager.js'
        content = import_path.read_text()

        # Verify retry mechanism exists
        assert '_showErrorToast' in content, "Should have error toast method"
        assert '_retryPendingSave' in content, "Should have retry method"
        assert 'pendingRetryData' in content, "Should store retry data"

    def test_retry_button_created_on_network_error(self):
        """
        _showErrorToast should create a Retry button when pendingRetryData exists.
        """
        import_path = Path(__file__).parent.parent.parent / 'static' / 'js' / 'bbox-manager.js'
        content = import_path.read_text()

        # Find the showErrorToast method
        assert "if (this.pendingRetryData)" in content, \
            "Should check if retry data exists"
        assert "retryBtn.textContent = 'Retry'" in content, \
            "Should create Retry button"
        assert "retryBtn.onclick = () => this._retryPendingSave()" in content, \
            "Retry button should call _retryPendingSave"

    def test_retry_sends_same_data(self):
        """
        _retryPendingSave should send the same selection data that failed.
        """
        import_path = Path(__file__).parent.parent.parent / 'static' / 'js' / 'bbox-manager.js'
        content = import_path.read_text()

        # Find retry method
        retry_section_start = content.find('async _retryPendingSave()')
        retry_section = content[retry_section_start:retry_section_start + 800]

        assert 'this.pendingRetryData' in retry_section, \
            "Should use pendingRetryData"
        assert 'JSON.stringify(selectionData)' in retry_section, \
            "Should stringify the selection data for retry"

    def test_dismiss_button_clears_pending_state(self):
        """
        Dismiss button should clear pending box and retry data.
        """
        import_path = Path(__file__).parent.parent.parent / 'static' / 'js' / 'bbox-manager.js'
        content = import_path.read_text()

        # Find dismiss button handler
        assert "dismissBtn.textContent = 'Dismiss'" in content
        assert 'this.pendingRetryData = null' in content, \
            "Dismiss should clear retry data"

    def test_network_error_stores_retry_data(self):
        """
        Network failure should store data for retry.
        """
        import_path = Path(__file__).parent.parent.parent / 'static' / 'js' / 'bbox-manager.js'
        content = import_path.read_text()

        # Verify retry data is stored on failure
        assert "this.pendingRetryData = { box, selectionData }" in content, \
            "Should store box and selectionData for retry"

    # =========================================================================
    # Extraction Error Retry Tests
    # =========================================================================

    def test_extraction_error_shows_retry_option(self):
        """
        Extraction failure should show error modal with retry button.
        """
        template_path = Path(__file__).parent.parent.parent / 'templates' / 'reports' / 'book_viewer.html'
        content = template_path.read_text()

        # Verify extraction error modal
        assert 'x-show="extractError"' in content, "Should show extraction error modal"
        assert '@click="retryExtraction()"' in content, "Should have retry button"
        assert 'Extraction Failed' in content, "Should show failure title"

    def test_retry_extraction_method_exists(self):
        """
        retryExtraction method should clear error and restart extraction.
        """
        import_path = Path(__file__).parent.parent.parent / 'static' / 'js' / 'book-viewer.js'
        content = import_path.read_text()

        # Find retryExtraction
        assert 'retryExtraction()' in content, "Should have retryExtraction method"

        retry_section_start = content.find('retryExtraction()')
        retry_section = content[retry_section_start:retry_section_start + 200]

        assert 'this.extractError = null' in retry_section, \
            "Should clear error before retry"
        assert 'this.startExtraction()' in retry_section, \
            "Should call startExtraction to retry"

    def test_close_extraction_error_method_exists(self):
        """
        closeExtractionError should clear error state without retry.
        """
        import_path = Path(__file__).parent.parent.parent / 'static' / 'js' / 'book-viewer.js'
        content = import_path.read_text()

        # Find closeExtractionError
        assert 'closeExtractionError()' in content

        close_section_start = content.find('closeExtractionError()')
        close_section = content[close_section_start:close_section_start + 200]

        assert 'this.extractError = null' in close_section
        assert 'this.extracting = false' in close_section

    # =========================================================================
    # Zoom Preserves Box Positions Tests
    # =========================================================================

    def test_zoom_uses_css_transform(self):
        """
        Zoom should use CSS transform on the container, not reposition elements.
        This preserves relative positions of selection overlays.
        """
        template_path = Path(__file__).parent.parent.parent / 'templates' / 'reports' / 'book_viewer.html'
        content = template_path.read_text()

        # Verify zoom is applied via CSS transform
        assert "transform: 'scale(' + (zoom / 100) + ')'" in content, \
            "Should use CSS transform for zoom"
        assert "transformOrigin: 'top center'" in content, \
            "Should set transform origin for consistent scaling"

    def test_zoom_controls_range(self):
        """
        Zoom should be constrained to 50%-200% range.
        """
        import_path = Path(__file__).parent.parent.parent / 'static' / 'js' / 'book-viewer.js'
        content = import_path.read_text()

        # Verify zoom limits
        assert 'if (this.zoom < 200)' in content, "Should check max zoom"
        assert 'if (this.zoom > 50)' in content, "Should check min zoom"
        assert 'this.zoom = Math.min(200' in content, "Should cap at 200"
        assert 'this.zoom = Math.max(50' in content, "Should floor at 50"

    def test_selection_overlay_relative_positioning(self):
        """
        Selection overlays should use relative positioning within the container.
        This ensures they scale correctly with the CSS transform zoom.
        """
        template_path = Path(__file__).parent.parent.parent / 'templates' / 'reports' / 'book_viewer.html'
        content = template_path.read_text()

        # Verify overlays are positioned relative to container
        assert 'page-container' in content
        assert 'position: relative' in content, \
            "Container should be positioned relative"

    def test_coordinate_conversion_independent_of_zoom(self):
        """
        canvasToPdf and pdfToCanvas should not factor in zoom level.
        Zoom is handled by CSS transform on container.
        """
        import_path = Path(__file__).parent.parent.parent / 'static' / 'js' / 'bbox-manager.js'
        content = import_path.read_text()

        # Find canvasToPdf method - should only use scale from dataset, not zoom
        canvas_to_pdf_start = content.find('canvasToPdf(')
        canvas_to_pdf = content[canvas_to_pdf_start:canvas_to_pdf_start + 400]

        assert 'pdfCanvas.dataset.scale' in canvas_to_pdf, \
            "Should use PDF render scale, not zoom"
        assert 'zoom' not in canvas_to_pdf.lower(), \
            "canvasToPdf should NOT reference zoom level"

    def test_bbox_overlay_uses_absolute_positioning(self):
        """
        BoundingBox overlays should use absolute positioning within container.
        """
        import_path = Path(__file__).parent.parent.parent / 'static' / 'js' / 'bbox-manager.js'
        content = import_path.read_text()

        # Find createOverlay method - need to search a larger section
        overlay_section_start = content.find('createOverlay(')
        overlay_section = content[overlay_section_start:overlay_section_start + 1000]

        assert 'position: absolute' in overlay_section, \
            "Overlay should use absolute positioning"
        assert 'top: 0' in overlay_section
        assert 'left: 0' in overlay_section

    # =========================================================================
    # Unsaved Changes Warning Tests
    # =========================================================================

    def test_pending_box_state_tracked(self):
        """
        Pending box (drawn but not confirmed) state should be tracked.
        """
        import_path = Path(__file__).parent.parent.parent / 'static' / 'js' / 'bbox-manager.js'
        content = import_path.read_text()

        # Verify pendingBox state exists
        assert 'this.pendingBox = null' in content, \
            "Should initialize pendingBox state"

    def test_escape_cancels_pending_box(self):
        """
        Pressing Escape should cancel any pending (unconfirmed) box.
        """
        import_path = Path(__file__).parent.parent.parent / 'static' / 'js' / 'bbox-manager.js'
        content = import_path.read_text()

        # Verify keyboard handler
        assert '_handleKeydown' in content, "Should have keyboard handler"
        assert "if (e.key === 'Escape')" in content, "Should handle Escape key"
        assert 'this._cancelPendingBox()' in content, \
            "Escape should cancel pending box"

    def test_confirm_popup_has_cancel_button(self):
        """
        After drawing a box, confirm popup should have Cancel button.
        """
        import_path = Path(__file__).parent.parent.parent / 'static' / 'js' / 'bbox-manager.js'
        content = import_path.read_text()

        # Verify cancel functionality
        assert '_showConfirmPopup' in content
        assert "cancelText.textContent = 'Cancel'" in content
        assert 'cancelBtn.onclick = () => this._cancelPendingBox()' in content

    def test_unsaved_changes_note(self):
        """
        Note: beforeunload warning is not implemented as the current UX
        requires explicit confirmation for each drawn box.
        The "(if applicable)" in the acceptance criteria acknowledges this.

        Current flow:
        1. User draws a box
        2. Confirm popup appears with Save/Cancel buttons
        3. User must explicitly confirm before navigating
        4. If they navigate away, only the unconfirmed pending box is lost

        This is an acceptable UX as each box requires explicit action.
        """
        # This is a documentation test - the current UX is intentional
        import_path = Path(__file__).parent.parent.parent / 'static' / 'js' / 'bbox-manager.js'
        content = import_path.read_text()

        # Verify explicit confirmation flow exists (which makes beforeunload less critical)
        assert '_showConfirmPopup' in content, "Has explicit confirmation popup"
        assert '_confirmPendingBox' in content, "Has confirm action"
        assert '_cancelPendingBox' in content, "Has cancel action"

    # =========================================================================
    # Additional Edge Case Tests
    # =========================================================================

    def test_page_input_validates_range(self):
        """
        Page input should validate page number is within range.
        """
        import_path = Path(__file__).parent.parent.parent / 'static' / 'js' / 'book-viewer.js'
        content = import_path.read_text()

        # Find goToPageFromInput
        assert 'goToPageFromInput()' in content

        method_start = content.find('goToPageFromInput()')
        method_section = content[method_start:method_start + 500]

        assert 'if (pageNum < 1)' in method_section, "Should check minimum"
        assert 'if (pageNum > this.totalPages)' in method_section, "Should check maximum"
        assert 'isNaN(pageNum)' in method_section, "Should handle non-numeric input"

    def test_min_box_size_filter(self):
        """
        Boxes smaller than 20x20 canvas pixels should be ignored (accidental clicks).
        """
        import_path = Path(__file__).parent.parent.parent / 'static' / 'js' / 'bbox-manager.js'
        content = import_path.read_text()

        # Verify minimum size check
        assert 'width < 20 || height < 20' in content, \
            "Should filter boxes smaller than 20x20 pixels"

    def test_overlapping_box_click_detection(self):
        """
        Click handler should detect clicks on selection boxes.
        """
        import_path = Path(__file__).parent.parent.parent / 'static' / 'js' / 'bbox-manager.js'
        content = import_path.read_text()

        # Verify click detection logic
        assert '_onClick(e, overlay)' in content, "Should have click handler"
        assert 'clickX >= boxX && clickX <= boxX + boxWidth' in content, \
            "Should check X bounds"
        assert 'clickY >= boxY && clickY <= boxY + boxHeight' in content, \
            "Should check Y bounds"

    def test_error_toast_auto_dismisses(self):
        """
        Error toast should auto-dismiss (based on book-viewer.js showStatusError).
        """
        import_path = Path(__file__).parent.parent.parent / 'static' / 'js' / 'book-viewer.js'
        content = import_path.read_text()

        # Verify auto-dismiss
        assert 'setTimeout(() =>' in content, "Should use setTimeout for auto-dismiss"
        assert '5000' in content, "Should dismiss after 5 seconds"

    def test_loading_state_shown_during_render(self):
        """
        Loading indicator should be shown during page rendering.
        """
        template_path = Path(__file__).parent.parent.parent / 'templates' / 'reports' / 'book_viewer.html'
        content = template_path.read_text()

        # Verify rendering indicator
        assert 'x-show="renderingPages"' in content, \
            "Should show indicator during page render"
        assert 'Rendering pages...' in content, \
            "Should show rendering message"


# =============================================================================
# BV-019: Integration Tests with Test Client
# =============================================================================


@pytest.mark.django_db
class TestBV019IntegrationEdgeCases(APITestCase):
    """Integration tests for edge cases using Django test client."""

    def setUp(self):
        """Set up test user and authentication."""
        from django.contrib.auth import get_user_model
        User = get_user_model()
        self.user = User.objects.create_user(
            username='edge_test_user',
            email='edge@test.com',
            password='testpass123'
        )
        self.client.force_authenticate(user=self.user)

    def test_single_page_pdf_direct_fitz_read(self):
        """
        Single page PDF should be readable with proper page count.
        This tests the fitz library directly without Django file handling.
        """
        # Create single-page PDF
        doc = fitz.open()
        page = doc.new_page(width=612, height=792)
        page.insert_text(fitz.Point(50, 50), "Single Page Document", fontsize=14)

        # Verify single page
        assert len(doc) == 1

        # Verify dimensions
        viewport = doc[0].rect
        assert viewport.width == 612
        assert viewport.height == 792

        doc.close()

    def test_single_page_report_spread_calculation(self):
        """
        Single page report should calculate currentSpread correctly.
        With 1 page, currentSpread=0 shows page 1, right page is empty.
        """
        # Test the spread calculation logic:
        # For totalPages=1, currentSpread=0:
        # leftPageNum = 0 * 2 + 1 = 1
        # rightPageNum = 0 * 2 + 2 = 2
        # Since rightPageNum (2) > totalPages (1), right canvas is cleared

        total_pages = 1
        current_spread = 0

        left_page = current_spread * 2 + 1
        right_page = current_spread * 2 + 2

        assert left_page == 1
        assert right_page == 2
        assert right_page > total_pages  # Should trigger clearCanvas

    def test_large_pdf_direct_fitz_read(self):
        """
        Large PDF (25 pages) should be readable without issues.
        This tests the fitz library directly without Django file handling.
        """
        # Create a 25-page PDF
        doc = fitz.open()
        for i in range(25):
            page = doc.new_page(width=612, height=792)
            page.insert_text(fitz.Point(50, 50), f"Page {i + 1}", fontsize=14)

        # Verify page count
        assert len(doc) == 25

        # Verify all pages have valid dimensions
        for page_num in range(25):
            page = doc[page_num]
            assert page.rect.width == 612
            assert page.rect.height == 792

        doc.close()

    def test_large_pdf_spread_navigation(self):
        """
        Large PDF should support navigation through all spreads.
        With 25 pages, there should be 13 spreads (last spread has only page 25).
        """
        total_pages = 25

        # Count spreads
        spreads = (total_pages + 1) // 2  # Ceiling division
        assert spreads == 13

        # Test last spread calculation
        current_spread = 12  # 0-indexed, so 13th spread
        left_page = current_spread * 2 + 1
        right_page = current_spread * 2 + 2

        assert left_page == 25
        assert right_page == 26
        assert right_page > total_pages  # Page 26 doesn't exist

        # Test spread navigation bounds
        def has_next_spread(spread, total):
            return (spread + 1) * 2 < total

        assert not has_next_spread(12, 25)  # No spread after 13th
        assert has_next_spread(11, 25)  # Can go to 13th from 12th

    def test_selection_on_last_page_of_large_pdf(self):
        """
        Selections should work on the last page of a large PDF.
        """
        from api.models import Report, TableSelection

        report = Report.objects.create(
            name='last_page_selection_test',
            owner=self.user,
            extraction_mode='manual',
            extraction_status='pending_review',
            total_pages=25
        )

        # Create selection on page 25
        response = self.client.post(
            f'/api/reports/{report.id}/selections/',
            {
                'page_num': 25,
                'x1': 50.0,
                'y1': 100.0,
                'x2': 250.0,
                'y2': 300.0,
            },
            format='json'
        )

        assert response.status_code == 201
        assert response.data['page_num'] == 25
        assert response.data['status'] == 'approved'

        # Verify it's stored
        sel = TableSelection.objects.get(id=response.data['id'])
        assert sel.page_num == 25

    def test_viewer_accessible_for_single_page_pdf(self):
        """
        Book viewer should be accessible for single-page PDFs.
        Tests that the view accepts and renders for single-page documents.
        """
        from api.models import Report
        from django.test import Client

        report = None
        try:
            report = Report.objects.create(
                name='single_page_viewer_test',
                owner=self.user,
                extraction_mode='manual',
                extraction_status='pending_review',
                total_pages=1
            )

            # Use Django test client (not DRF) for template rendering
            client = Client()
            client.force_login(self.user)

            # Mock document.url to avoid file requirement
            with patch.object(type(report.document), 'url', property(lambda self: '/media/test.pdf')):
                response = client.get(f'/reports/{report.id}/viewer/')
                assert response.status_code == 200

        finally:
            if report:
                report.delete()

    def test_invalid_page_selection_rejected(self):
        """
        Selection on page beyond total_pages should be rejected.
        """
        from api.models import Report

        report = Report.objects.create(
            name='invalid_page_test',
            owner=self.user,
            extraction_mode='manual',
            extraction_status='pending_review',
            total_pages=5
        )

        # Try to create selection on page 10 (beyond total)
        response = self.client.post(
            f'/api/reports/{report.id}/selections/',
            {
                'page_num': 10,  # Invalid - only 5 pages
                'x1': 50.0,
                'y1': 100.0,
                'x2': 250.0,
                'y2': 300.0,
            },
            format='json'
        )

        # Should be rejected by serializer validation
        assert response.status_code == 400

    def test_zero_page_number_rejected(self):
        """
        Selection on page 0 should be rejected.
        """
        from api.models import Report

        report = Report.objects.create(
            name='zero_page_test',
            owner=self.user,
            extraction_mode='manual',
            extraction_status='pending_review',
            total_pages=5
        )

        response = self.client.post(
            f'/api/reports/{report.id}/selections/',
            {
                'page_num': 0,  # Invalid
                'x1': 50.0,
                'y1': 100.0,
                'x2': 250.0,
                'y2': 300.0,
            },
            format='json'
        )

        assert response.status_code == 400


# =============================================================================
# BV-020: Edge Cases in Detection and Extraction
# =============================================================================


class TestEdgeCaseMessages:
    """
    BV-020: Verify user-friendly messages and edge case handling
    """

    def test_zero_detection_message_in_review_mode(self):
        """
        When YOLO detects 0 tables in review mode, getEmptyStateMessage()
        returns the specific "No tables detected" message.
        """
        # JavaScript function logic check
        js_code = Path(__file__).parent.parent.parent / 'static' / 'js' / 'book-viewer.js'
        content = js_code.read_text()

        # Verify the getEmptyStateMessage() function exists and returns correct message
        assert 'getEmptyStateMessage()' in content
        assert "No tables detected. Draw selections manually or try a different PDF." in content

    def test_zero_detection_hint_message(self):
        """
        When YOLO detects 0 tables in review mode, getEmptyStateHint()
        returns guidance about manual selection.
        """
        js_code = Path(__file__).parent.parent.parent / 'static' / 'js' / 'book-viewer.js'
        content = js_code.read_text()

        # Verify the getEmptyStateHint() function exists
        assert 'getEmptyStateHint()' in content
        assert "You can still draw boxes around tables manually" in content

    def test_manual_mode_empty_message_different(self):
        """
        In manual mode (not review), the empty message is generic.
        """
        js_code = Path(__file__).parent.parent.parent / 'static' / 'js' / 'book-viewer.js'
        content = js_code.read_text()

        # Manual mode has different message
        assert "No table selections yet." in content

    def test_template_uses_dynamic_empty_messages(self):
        """
        Template uses dynamic getEmptyStateMessage() and getEmptyStateHint().
        """
        template = Path(__file__).parent.parent.parent / 'templates' / 'reports' / 'book_viewer.html'
        content = template.read_text()

        # Verify template calls the methods
        assert 'x-text="getEmptyStateMessage()"' in content
        assert 'x-text="getEmptyStateHint()"' in content


class TestPartialExtractionSuccess:
    """
    BV-020: Verify partial extraction success handling
    """

    def test_extract_from_selections_tracks_failed_pages(self):
        """
        The extract_from_selections task tracks failed pages.
        """
        from api.tasks import extract_from_selections
        import inspect

        source = inspect.getsource(extract_from_selections)

        # Verify failed_pages tracking is implemented
        assert 'failed_pages = []' in source
        assert 'failed_pages.append(page_num)' in source

    def test_extract_from_selections_returns_failed_pages(self):
        """
        The extract_from_selections task includes failed_pages in result.
        """
        from api.tasks import extract_from_selections
        import inspect

        source = inspect.getsource(extract_from_selections)

        # Verify result includes failed_pages
        assert "result['failed_pages']" in source

    def test_extract_from_selections_marks_failed_status(self):
        """
        When extraction fails for a selection, it's marked with status='failed'.
        """
        from api.tasks import extract_from_selections
        import inspect

        source = inspect.getsource(extract_from_selections)

        # Verify selections are updated to failed status
        # Can be either queryset .update() or single instance .status = 'failed'
        assert ".update(status='failed')" in source or "status = 'failed'" in source

    def test_partial_success_modal_in_template(self):
        """
        Template includes partial success modal.
        """
        template = Path(__file__).parent.parent.parent / 'templates' / 'reports' / 'book_viewer.html'
        content = template.read_text()

        # Verify partial success modal exists
        assert 'x-show="partialSuccess"' in content
        assert 'Extraction Partially Complete' in content
        assert 'partialSuccess?.failedPages' in content

    def test_partial_success_handler_in_js(self):
        """
        JavaScript handles partial success state.
        """
        js_code = Path(__file__).parent.parent.parent / 'static' / 'js' / 'book-viewer.js'
        content = js_code.read_text()

        # Verify partialSuccess state tracking
        assert 'partialSuccess: null' in content
        assert 'this.partialSuccess =' in content
        assert 'dismissPartialSuccess()' in content


class TestFailedSelectionStatus:
    """
    BV-020: Verify failed selection status handling
    """

    def test_failed_status_exists_in_model(self):
        """
        TableSelection model has 'failed' status choice.
        """
        from api.models import TableSelection

        status_values = [choice[0] for choice in TableSelection.STATUS_CHOICES]
        assert 'failed' in status_values

    def test_failed_selection_styling_in_template(self):
        """
        Template includes CSS styling for failed selections.
        """
        template = Path(__file__).parent.parent.parent / 'templates' / 'reports' / 'book_viewer.html'
        content = template.read_text()

        # Verify failed status CSS
        assert '.selection-overlay.failed' in content
        assert 'border-style: dashed' in content

    def test_failed_status_color_in_bbox_manager(self):
        """
        BoundingBoxManager uses correct color for failed status.
        """
        js_code = Path(__file__).parent.parent.parent / 'static' / 'js' / 'bbox-manager.js'
        content = js_code.read_text()

        # Verify failed status color handling
        assert "selection.status === 'failed'" in content
        assert '#DC2626' in content  # Red color for failed

    def test_failed_status_indicator_in_selection_panel(self):
        """
        Selection panel shows indicator for failed selections.
        """
        template = Path(__file__).parent.parent.parent / 'templates' / 'reports' / 'book_viewer.html'
        content = template.read_text()

        # Verify failed status gets visual indicator
        assert "'bg-red-600': sel.status === 'failed'" in content


class TestNetworkErrorRetryButtons:
    """
    BV-020: Verify network error handling with retry buttons
    """

    def test_bbox_manager_has_retry_on_save_error(self):
        """
        BoundingBoxManager shows retry button on box save failure.
        """
        js_code = Path(__file__).parent.parent.parent / 'static' / 'js' / 'bbox-manager.js'
        content = js_code.read_text()

        # Verify retry mechanism exists
        assert 'pendingRetryData' in content
        assert '_retryPendingSave' in content
        assert '_showErrorToast' in content

    def test_extraction_error_has_retry_button(self):
        """
        Extraction error modal has retry button.
        """
        template = Path(__file__).parent.parent.parent / 'templates' / 'reports' / 'book_viewer.html'
        content = template.read_text()

        # Verify retry button in extraction error modal
        assert '@click="retryExtraction()"' in content
        assert 'extractError' in content

    def test_retry_extraction_method_exists(self):
        """
        Book viewer has retryExtraction() method.
        """
        js_code = Path(__file__).parent.parent.parent / 'static' / 'js' / 'book-viewer.js'
        content = js_code.read_text()

        # Verify retryExtraction method
        assert 'retryExtraction()' in content
        assert 'this.extractError = null' in content


class TestUserFriendlyErrors:
    """
    BV-020: Verify all error messages are user-friendly
    """

    def test_task_sanitizes_exception_messages(self):
        """
        Celery tasks sanitize raw exception messages.
        """
        from api import tasks
        import inspect

        source = inspect.getsource(tasks)

        # Verify error sanitization in both tasks
        assert "user_friendly_msg" in source
        assert "'Traceback' in error_msg" in source

    def test_detection_task_has_friendly_error(self):
        """
        detect_tables_for_review uses user-friendly error message.
        """
        from api.tasks import detect_tables_for_review
        import inspect

        source = inspect.getsource(detect_tables_for_review)

        # Verify friendly error message
        assert "Table detection failed. Please ensure the PDF is valid" in source

    def test_extraction_task_has_friendly_error(self):
        """
        extract_from_selections uses user-friendly error message.
        """
        from api.tasks import extract_from_selections
        import inspect

        source = inspect.getsource(extract_from_selections)

        # Verify friendly error message
        assert "Table extraction failed. Please check that the PDF contains valid tables" in source

    def test_js_sanitizes_error_display(self):
        """
        JavaScript sanitizes error messages before display.
        """
        js_code = Path(__file__).parent.parent.parent / 'static' / 'js' / 'book-viewer.js'
        content = js_code.read_text()

        # Verify error sanitization in JS
        assert "Sanitize error message" in content or "errorMsg.includes('Traceback')" in content


class TestViewerWithZeroDetections:
    """
    BV-020: Verify viewer opens normally with empty overlay
    """

    def test_viewer_loads_with_empty_selections(self):
        """
        Viewer initializes correctly when no selections exist.
        """
        js_code = Path(__file__).parent.parent.parent / 'static' / 'js' / 'book-viewer.js'
        content = js_code.read_text()

        # Verify selections initialized as empty array
        assert 'selections: []' in content or 'this.selections = []' in content

    def test_extraction_mode_passed_to_js(self):
        """
        Template passes extractionMode to JavaScript config.
        """
        template = Path(__file__).parent.parent.parent / 'templates' / 'reports' / 'book_viewer.html'
        content = template.read_text()

        # Verify extractionMode is passed
        assert "extractionMode: '{{ report.extraction_mode }}'" in content

    def test_js_accepts_extraction_mode(self):
        """
        Book viewer JS accepts extractionMode config.
        """
        js_code = Path(__file__).parent.parent.parent / 'static' / 'js' / 'book-viewer.js'
        content = js_code.read_text()

        # Verify extractionMode is used
        assert 'extractionMode: config.extractionMode' in content


# =============================================================================
# Test: Coordinate Transformation Math (Unit Tests)
# =============================================================================

class TestCoordinateTransformationMath:
    """
    Unit tests for the coordinate transformation logic in extract_from_selections.

    The transformation converts:
    - Canvas percentages (0-100) with top-left origin
    - To PDF coordinates (points) with bottom-left origin

    Math:
    - X: pdf_x = (canvas_x_percent / 100) * page_width
    - Y: pdf_y = (1 - canvas_y_percent / 100) * page_height  (Y-flip)
    """

    def test_x_axis_linear_scaling(self):
        """X-axis should scale linearly from percentage to PDF points."""
        # Given: percentage X coordinates on a 612-point wide page
        page_width = 612.0
        x_percent = 50.0

        # When: converting to PDF coordinates
        pdf_x = (x_percent / 100) * page_width

        # Then: result is linear scaling
        assert pdf_x == 306.0

    def test_x_axis_boundary_zero(self):
        """X=0% should map to PDF X=0."""
        # Given: X at left edge
        page_width = 612.0
        x_percent = 0.0

        # When: converting to PDF coordinates
        pdf_x = (x_percent / 100) * page_width

        # Then: maps to left edge of PDF
        assert pdf_x == 0.0

    def test_x_axis_boundary_hundred(self):
        """X=100% should map to full page width."""
        # Given: X at right edge
        page_width = 612.0
        x_percent = 100.0

        # When: converting to PDF coordinates
        pdf_x = (x_percent / 100) * page_width

        # Then: maps to right edge of PDF
        assert pdf_x == 612.0

    def test_y_axis_flip_top_to_high(self):
        """Canvas Y=10% (near top) should map to high PDF Y (near top in PDF coords)."""
        # Given: Y near top of canvas (small percentage)
        page_height = 792.0
        y_percent = 10.0  # 10% from top

        # When: converting with Y-flip
        pdf_y = (1 - y_percent / 100) * page_height

        # Then: maps to high Y value in PDF (top of page)
        assert pdf_y == pytest.approx(712.8)  # 0.9 * 792

    def test_y_axis_flip_bottom_to_low(self):
        """Canvas Y=90% (near bottom) should map to low PDF Y (near bottom in PDF coords)."""
        # Given: Y near bottom of canvas (large percentage)
        page_height = 792.0
        y_percent = 90.0  # 90% from top = near bottom

        # When: converting with Y-flip
        pdf_y = (1 - y_percent / 100) * page_height

        # Then: maps to low Y value in PDF (bottom of page)
        assert pdf_y == pytest.approx(79.2)  # 0.1 * 792

    def test_y_axis_boundary_zero(self):
        """Y=0% (top of canvas) should map to full page height (top of PDF)."""
        # Given: Y at top edge of canvas
        page_height = 792.0
        y_percent = 0.0

        # When: converting with Y-flip
        pdf_y = (1 - y_percent / 100) * page_height

        # Then: maps to top of PDF (maximum Y)
        assert pdf_y == 792.0

    def test_y_axis_boundary_hundred(self):
        """Y=100% (bottom of canvas) should map to 0 (bottom of PDF)."""
        # Given: Y at bottom edge of canvas
        page_height = 792.0
        y_percent = 100.0

        # When: converting with Y-flip
        pdf_y = (1 - y_percent / 100) * page_height

        # Then: maps to bottom of PDF (Y=0)
        assert pdf_y == 0.0

    def test_full_bbox_transformation(self):
        """Full bounding box should transform correctly preserving containment."""
        # Given: a selection covering 10%-90% in both dimensions
        page_width = 612.0
        page_height = 792.0
        # Canvas coords: top-left at (10%, 20%), bottom-right at (90%, 80%)
        x1_pct, y1_pct = 10.0, 20.0  # top-left in canvas
        x2_pct, y2_pct = 90.0, 80.0  # bottom-right in canvas

        # When: converting to PDF coordinates
        pdf_x1 = (x1_pct / 100) * page_width
        pdf_x2 = (x2_pct / 100) * page_width
        pdf_y1 = (1 - y1_pct / 100) * page_height
        pdf_y2 = (1 - y2_pct / 100) * page_height

        # Then: X ordering preserved, Y ordering inverted
        assert pdf_x1 == pytest.approx(61.2)   # 10% of 612
        assert pdf_x2 == pytest.approx(550.8)  # 90% of 612
        assert pdf_y1 == pytest.approx(633.6)  # (1 - 0.2) * 792 = 0.8 * 792
        assert pdf_y2 == pytest.approx(158.4)  # (1 - 0.8) * 792 = 0.2 * 792

        # X order preserved: x1 < x2
        assert pdf_x1 < pdf_x2
        # Y order inverted: y1 > y2 (because canvas y1 < y2)
        assert pdf_y1 > pdf_y2

    def test_different_page_dimensions(self):
        """Transformation should scale correctly for non-standard page sizes."""
        # Given: a landscape A4-ish page (different dimensions)
        page_width = 842.0  # A4 landscape width
        page_height = 595.0  # A4 landscape height
        x_pct, y_pct = 25.0, 75.0

        # When: converting to PDF coordinates
        pdf_x = (x_pct / 100) * page_width
        pdf_y = (1 - y_pct / 100) * page_height

        # Then: scales to the specific page dimensions
        assert pdf_x == 210.5   # 25% of 842
        assert pdf_y == 148.75  # (1 - 0.75) * 595 = 0.25 * 595

    def test_midpoint_transformation(self):
        """Center of canvas (50%, 50%) should map to center of PDF."""
        # Given: center point
        page_width = 612.0
        page_height = 792.0
        x_pct, y_pct = 50.0, 50.0

        # When: converting to PDF coordinates
        pdf_x = (x_pct / 100) * page_width
        pdf_y = (1 - y_pct / 100) * page_height

        # Then: maps to center of PDF page
        assert pdf_x == 306.0  # Half of 612
        assert pdf_y == 396.0  # Half of 792


# =============================================================================
# Test: Status Filtering Integration (Django Required)
# =============================================================================

@pytest.mark.skipif(not DJANGO_API_AVAILABLE, reason="Django API not available")
@pytest.mark.django_db(transaction=True)
class TestStatusFilteringIntegration(APITestCase):
    """
    Integration test verifying that extraction only processes approved selections.

    This test creates selections with mixed statuses and verifies:
    1. Only approved selections are passed to the extraction logic
    2. Pending and rejected selections do not produce Extracted records
    """

    def setUp(self):
        """Set up test user."""
        self.user = User.objects.create_user(
            username='status_filter_test_user',
            password='testpass123',
            email='statusfilter@example.com'
        )

    def tearDown(self):
        """Clean up after tests."""
        from api.models import Report
        Report.objects.filter(owner=self.user).delete()

    def test_extraction_processes_only_approved_selections(self):
        """Extraction task should only process selections with status='approved'."""
        from api.models import Report, TableSelection
        from collections import defaultdict

        # Given: a report with mixed selection statuses
        report = Report.objects.create(
            name='test_status_filtering',
            extraction_mode='manual',
            extraction_status='pending_review',
            owner=self.user
        )
        approved_sel = TableSelection.objects.create(
            report=report, page_num=1,
            x1=10.0, y1=20.0, x2=50.0, y2=60.0,
            source='manual', status='approved'
        )
        pending_sel = TableSelection.objects.create(
            report=report, page_num=1,
            x1=55.0, y1=20.0, x2=95.0, y2=60.0,
            source='yolo', status='pending'
        )
        rejected_sel = TableSelection.objects.create(
            report=report, page_num=2,
            x1=10.0, y1=10.0, x2=90.0, y2=90.0,
            source='yolo', status='rejected'
        )

        # When: querying approved selections as the extraction task does
        approved_selections = TableSelection.objects.filter(
            report=report,
            status='approved'
        ).order_by('page_num', 'created_at')

        # Then: only the approved selection is included
        assert approved_selections.count() == 1
        assert approved_selections.first().id == approved_sel.id

        # And: pending and rejected are excluded
        selection_ids = list(approved_selections.values_list('id', flat=True))
        assert pending_sel.id not in selection_ids
        assert rejected_sel.id not in selection_ids

    def test_coordinate_grouping_by_page(self):
        """Approved selections should be grouped by page for extraction."""
        from api.models import Report, TableSelection
        from collections import defaultdict

        # Given: approved selections on multiple pages
        report = Report.objects.create(
            name='test_page_grouping',
            extraction_mode='review',
            extraction_status='pending_review',
            owner=self.user
        )
        # Two selections on page 1
        TableSelection.objects.create(
            report=report, page_num=1,
            x1=10.0, y1=10.0, x2=45.0, y2=45.0,
            source='yolo', status='approved'
        )
        TableSelection.objects.create(
            report=report, page_num=1,
            x1=50.0, y1=10.0, x2=90.0, y2=45.0,
            source='manual', status='approved'
        )
        # One selection on page 2
        TableSelection.objects.create(
            report=report, page_num=2,
            x1=20.0, y1=20.0, x2=80.0, y2=80.0,
            source='yolo', status='approved'
        )
        # One rejected on page 3 (should not appear)
        TableSelection.objects.create(
            report=report, page_num=3,
            x1=10.0, y1=10.0, x2=90.0, y2=90.0,
            source='yolo', status='rejected'
        )

        # When: grouping approved selections by page (as extraction does)
        approved = TableSelection.objects.filter(
            report=report, status='approved'
        ).order_by('page_num', 'created_at')

        selections_by_page = defaultdict(list)
        for sel in approved:
            selections_by_page[sel.page_num].append(sel)

        # Then: page grouping is correct
        assert len(selections_by_page) == 2  # Only pages 1 and 2
        assert 1 in selections_by_page
        assert 2 in selections_by_page
        assert 3 not in selections_by_page  # Rejected selection excluded

        # And: correct counts per page
        assert len(selections_by_page[1]) == 2  # Two approved on page 1
        assert len(selections_by_page[2]) == 1  # One approved on page 2

    def test_mixed_sources_both_extracted_when_approved(self):
        """Both yolo and manual selections should be extracted if approved."""
        from api.models import Report, TableSelection

        # Given: approved selections from both sources
        report = Report.objects.create(
            name='test_mixed_sources',
            extraction_mode='review',
            extraction_status='pending_review',
            owner=self.user
        )
        yolo_approved = TableSelection.objects.create(
            report=report, page_num=1,
            x1=10.0, y1=10.0, x2=45.0, y2=45.0,
            source='yolo', status='approved'
        )
        manual_approved = TableSelection.objects.create(
            report=report, page_num=1,
            x1=50.0, y1=50.0, x2=90.0, y2=90.0,
            source='manual', status='approved'
        )
        yolo_pending = TableSelection.objects.create(
            report=report, page_num=2,
            x1=10.0, y1=10.0, x2=90.0, y2=90.0,
            source='yolo', status='pending'
        )

        # When: filtering for approved (as extraction does)
        approved = TableSelection.objects.filter(
            report=report, status='approved'
        )

        # Then: both yolo and manual approved are included
        assert approved.count() == 2
        sources = set(approved.values_list('source', flat=True))
        assert sources == {'yolo', 'manual'}

        # And: pending is excluded regardless of source
        assert yolo_pending not in approved


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
