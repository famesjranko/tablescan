"""
Tests for multi-result extraction with user selection.

Tests the extract_all_with_scores method, generate_warnings method,
variants caching, and method switching functionality.
"""

import json
import os
import tempfile
from unittest.mock import patch, MagicMock

import fitz
import pandas as pd
import pytest
from django.test import TestCase, override_settings
from django.contrib.auth.models import User
from rest_framework.test import APIClient

from api.models import Report, TableSelection, Extracted
from api.scripts.extractors import (
    MultiExtractor,
    ExtractionResult,
    ExtractionScorer,
    PdfplumberExtractor,
)
from api.tasks import (
    _cache_key_for_selection,
    _serialize_variants_for_cache,
    _deserialize_variants_from_cache,
)


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture
def simple_table_pdf():
    """Create a PDF with a simple table for testing."""
    with tempfile.NamedTemporaryFile(suffix='.pdf', delete=False) as f:
        pdf_path = f.name

    doc = fitz.open()
    page = doc.new_page(width=612, height=792)

    # Create a simple table with borders
    shape = page.new_shape()

    x_start, y_start = 100, 200
    cell_width, cell_height = 120, 30
    rows, cols = 4, 3

    # Draw table grid
    for i in range(rows + 1):
        y = y_start + i * cell_height
        shape.draw_line(fitz.Point(x_start, y), fitz.Point(x_start + cols * cell_width, y))

    for j in range(cols + 1):
        x = x_start + j * cell_width
        shape.draw_line(fitz.Point(x, y_start), fitz.Point(x, y_start + rows * cell_height))

    shape.finish(color=(0, 0, 0), width=0.5)
    shape.commit()

    # Add table text
    table_data = [
        ["Name", "Value", "Status"],
        ["Item A", "100", "Active"],
        ["Item B", "200", "Pending"],
        ["Item C", "300", "Complete"],
    ]

    for i, row in enumerate(table_data):
        for j, cell in enumerate(row):
            x = x_start + j * cell_width + 10
            y = y_start + i * cell_height + 20
            page.insert_text(fitz.Point(x, y), cell, fontsize=10, fontname="helv")

    doc.save(pdf_path)
    doc.close()

    yield pdf_path

    if os.path.exists(pdf_path):
        os.unlink(pdf_path)


@pytest.fixture
def sample_dataframe():
    """Create a sample DataFrame for testing."""
    return pd.DataFrame({
        'Name': ['Item A', 'Item B', 'Item C'],
        'Value': ['100', '200', '300'],
        'Status': ['Active', 'Pending', 'Complete'],
    })


@pytest.fixture
def sample_extraction_result(sample_dataframe):
    """Create a sample ExtractionResult for testing."""
    return ExtractionResult(
        dataframe=sample_dataframe,
        confidence=0.85,
        method='test_extractor',
        metadata={'test': True}
    )


# =============================================================================
# Test ExtractionScorer.generate_warnings
# =============================================================================

class TestGenerateWarnings:
    """Tests for ExtractionScorer.generate_warnings method."""

    def test_generate_warnings_empty_table_returns_warning(self):
        # Given: an extraction result with an empty dataframe
        scorer = ExtractionScorer()
        result = ExtractionResult(
            dataframe=pd.DataFrame(),
            confidence=0.0,
            method='test',
            metadata={}
        )

        # When: generating warnings
        warnings = scorer.generate_warnings(result)

        # Then: should include empty table warning
        assert 'Empty table - no data extracted' in warnings

    def test_generate_warnings_low_coverage_table(self):
        # Given: a table with many empty cells (low coverage)
        scorer = ExtractionScorer()
        df = pd.DataFrame({
            'A': ['', '', 'value'],
            'B': ['', '', ''],
            'C': ['', '', ''],
        })
        result = ExtractionResult(
            dataframe=df,
            confidence=0.5,
            method='test',
            metadata={}
        )

        # When: generating warnings
        warnings = scorer.generate_warnings(result)

        # Then: should warn about low coverage or empty cells
        assert any('coverage' in w.lower() or 'empty' in w.lower() for w in warnings)

    def test_generate_warnings_good_quality_table(self, sample_extraction_result):
        # Given: a high-quality extraction result
        scorer = ExtractionScorer()

        # When: generating warnings
        warnings = scorer.generate_warnings(sample_extraction_result)

        # Then: should have few or no warnings
        assert len(warnings) <= 2

    def test_generate_warnings_irregular_structure(self):
        # Given: a table with irregular structure (mostly empty rows)
        scorer = ExtractionScorer()
        df = pd.DataFrame({
            'A': ['header', '', '', ''],
            'B': ['header', '', '', ''],
        })
        result = ExtractionResult(
            dataframe=df,
            confidence=0.5,
            method='test',
            metadata={}
        )

        # When: generating warnings
        warnings = scorer.generate_warnings(result)

        # Then: should warn about structure issues
        assert any('structure' in w.lower() or 'irregular' in w.lower() or 'empty' in w.lower() for w in warnings)


# =============================================================================
# Test MultiExtractor.extract_all_with_scores
# =============================================================================

class TestExtractAllWithScores:
    """Tests for MultiExtractor.extract_all_with_scores method."""

    def test_returns_results_from_all_extractors(self, simple_table_pdf):
        # Given: a PDF with a table and multi-extractor
        extractor = MultiExtractor()

        # When: extracting with all methods
        results = extractor.extract_all_with_scores(simple_table_pdf, 1)

        # Then: should have results from multiple methods
        methods = [r['method'] for r in results if r.get('dataframe') is not None]
        assert len(methods) >= 1  # At least one extractor should succeed

    def test_results_sorted_by_score_descending(self, simple_table_pdf):
        # Given: a PDF with a table
        extractor = MultiExtractor()

        # When: extracting with all methods
        results = extractor.extract_all_with_scores(simple_table_pdf, 1)

        # Then: results should be sorted by score descending
        scores = [r.get('score', 0) for r in results]
        assert scores == sorted(scores, reverse=True)

    def test_result_structure_contains_required_fields(self, simple_table_pdf):
        # Given: a PDF with a table
        extractor = MultiExtractor()

        # When: extracting with all methods
        results = extractor.extract_all_with_scores(simple_table_pdf, 1)

        # Then: each result should have the required fields
        for result in results:
            assert 'method' in result
            assert 'score' in result
            assert 'confidence' in result
            assert 'rows' in result
            assert 'cols' in result
            assert 'warnings' in result

    def test_failed_extractor_returns_error_in_result(self):
        # Given: a multi-extractor with a mocked failing extractor
        extractor = MultiExtractor()
        with patch.object(extractor._extractors[0], 'extract', side_effect=Exception('Test error')):
            # When: extracting (will fail for first extractor)
            results = extractor.extract_all_with_scores('/fake/path.pdf', 1)

            # Then: should include error info for failed extractor
            failed_results = [r for r in results if 'error' in r]
            assert len(failed_results) >= 1


# =============================================================================
# Test PdfplumberExtractor name property
# =============================================================================

class TestPdfplumberExtractorName:
    """Tests for PdfplumberExtractor name variations."""

    def test_default_strategy_name(self):
        # Given: default pdfplumber extractor
        extractor = PdfplumberExtractor()

        # When: getting name
        name = extractor.name

        # Then: should be 'pdfplumber'
        assert name == 'pdfplumber'

    def test_explicit_strategy_name(self):
        # Given: pdfplumber extractor with explicit strategy
        extractor = PdfplumberExtractor(
            vertical_strategy='explicit',
            horizontal_strategy='explicit'
        )

        # When: getting name
        name = extractor.name

        # Then: should be 'pdfplumber_explicit'
        assert name == 'pdfplumber_explicit'

    def test_pdfplumber_text_strategy_has_distinct_name(self):
        """PdfplumberExtractor with text strategy should have unique name."""
        # Given: pdfplumber extractor with text strategy (for borderless tables)
        extractor = PdfplumberExtractor(
            vertical_strategy='text',
            horizontal_strategy='text'
        )

        # When: getting name
        name = extractor.name

        # Then: should be 'pdfplumber_text'
        assert name == 'pdfplumber_text'


# =============================================================================
# Test Variants Cache Serialization
# =============================================================================

class TestVariantsCacheSerialization:
    """Tests for variants cache serialization/deserialization."""

    def test_cache_key_format(self):
        # Given: report_id and selection_id
        report_id = 123
        selection_id = 456

        # When: generating cache key
        key = _cache_key_for_selection(report_id, selection_id)

        # Then: key should have expected format
        assert key == 'extraction_variants:123:456'

    def test_serialize_and_deserialize_variants(self, sample_dataframe):
        # Given: a list of variants with dataframes
        variants = [
            {
                'method': 'pdfplumber',
                'score': 0.85,
                'confidence': 0.8,
                'rows': 3,
                'cols': 3,
                'warnings': [],
                'dataframe': sample_dataframe,
                'metadata': {'test': True},
            },
            {
                'method': 'camelot_stream',
                'score': 0.75,
                'confidence': 0.7,
                'rows': 3,
                'cols': 3,
                'warnings': ['Low coverage'],
                'dataframe': sample_dataframe,
                'metadata': {},
            },
        ]

        # When: serializing and deserializing
        serialized = _serialize_variants_for_cache(variants)
        deserialized = _deserialize_variants_from_cache(serialized)

        # Then: deserialized should match original (except dataframe identity)
        assert len(deserialized) == len(variants)
        for orig, deser in zip(variants, deserialized):
            assert deser['method'] == orig['method']
            assert deser['score'] == orig['score']
            assert deser['warnings'] == orig['warnings']
            # DataFrame values should be equal (dtypes may differ due to JSON serialization)
            assert deser['dataframe'].shape == orig['dataframe'].shape
            assert list(deser['dataframe'].columns) == list(orig['dataframe'].columns)
            # Compare values as strings to handle type coercion
            for col in orig['dataframe'].columns:
                orig_vals = orig['dataframe'][col].astype(str).tolist()
                deser_vals = deser['dataframe'][col].astype(str).tolist()
                assert orig_vals == deser_vals

    def test_serialize_variants_with_none_dataframe(self):
        # Given: a variant with no dataframe (failed extraction)
        variants = [
            {
                'method': 'vision',
                'score': 0,
                'confidence': 0,
                'rows': 0,
                'cols': 0,
                'warnings': [],
                'dataframe': None,
                'error': 'Extraction failed',
            }
        ]

        # When: serializing and deserializing
        serialized = _serialize_variants_for_cache(variants)
        deserialized = _deserialize_variants_from_cache(serialized)

        # Then: should preserve None dataframe
        assert deserialized[0]['dataframe'] is None
        assert deserialized[0]['error'] == 'Extraction failed'


# =============================================================================
# Test API Endpoints (Django TestCase)
# =============================================================================

@pytest.mark.django_db
class TestVariantsEndpoint(TestCase):
    """Tests for /api/extracted/{id}/variants/ endpoint."""

    def setUp(self):
        # Create test user
        self.user = User.objects.create_user(
            username='testuser',
            password='testpass123'
        )
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    def test_variants_without_selection_returns_empty(self):
        # Given: an extracted table without a selection link
        report = Report.objects.create(
            owner=self.user,
            name='test_report',
            f_type='pdf'
        )
        extracted = Extracted.objects.create(
            report=report,
            page_num=1,
            table_num=0,
            f_type='csv',
            extraction_method='pdfplumber',
            selection=None  # No selection linked
        )

        # When: requesting variants
        response = self.client.get(f'/api/extracted/{extracted.id}/variants/')

        # Then: should return empty variants list
        assert response.status_code == 200
        data = response.json()
        assert data['variants'] == []
        assert 'not from selection' in data.get('message', '').lower()


@pytest.mark.django_db
@override_settings(
    CACHES={
        'default': {
            'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
        }
    }
)
class TestSwitchMethodEndpoint(TestCase):
    """Tests for /api/extracted/{id}/switch-method/ endpoint."""

    def setUp(self):
        self.user = User.objects.create_user(
            username='testuser',
            password='testpass123'
        )
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    def test_switch_method_without_selection_returns_error(self):
        # Given: an extracted table without a selection link
        report = Report.objects.create(
            owner=self.user,
            name='test_report',
            f_type='pdf'
        )
        extracted = Extracted.objects.create(
            report=report,
            page_num=1,
            table_num=0,
            f_type='csv',
            extraction_method='pdfplumber',
            selection=None
        )

        # When: attempting to switch method
        response = self.client.post(
            f'/api/extracted/{extracted.id}/switch-method/',
            {'method': 'camelot_stream'},
            format='json'
        )

        # Then: should return error
        assert response.status_code == 400
        assert 'not from selection' in response.json().get('error', '').lower()

    def test_switch_method_requires_method_param(self):
        # Given: an extracted table
        report = Report.objects.create(
            owner=self.user,
            name='test_report',
            f_type='pdf'
        )
        selection = TableSelection.objects.create(
            report=report,
            page_num=1,
            x1=10, y1=20, x2=90, y2=80,
            status='approved',
            source='manual'
        )
        extracted = Extracted.objects.create(
            report=report,
            page_num=1,
            table_num=0,
            f_type='csv',
            extraction_method='pdfplumber',
            selection=selection
        )

        # When: calling switch-method without method param
        response = self.client.post(
            f'/api/extracted/{extracted.id}/switch-method/',
            {},
            format='json'
        )

        # Then: should return error
        assert response.status_code == 400
        assert 'method' in response.json().get('error', '').lower()

    def test_switch_method_success_replaces_extraction(self):
        # Given: a report with document, selection, extracted table, and cached variants
        import shutil
        from django.core.files.uploadedfile import SimpleUploadedFile
        from django.core.cache import cache

        # Create PDF bytes
        doc = fitz.open()
        page = doc.new_page(width=612, height=792)
        shape = page.new_shape()
        x, y = 100, 200
        cw, ch = 120, 30
        for i in range(5):
            shape.draw_line(fitz.Point(x, y + i * ch), fitz.Point(x + 3 * cw, y + i * ch))
        for j in range(4):
            shape.draw_line(fitz.Point(x + j * cw, y), fitz.Point(x + j * cw, y + 4 * ch))
        shape.finish(color=(0, 0, 0), width=0.5)
        shape.commit()
        data = [["Name", "Value", "Status"], ["A", "100", "OK"], ["B", "200", "OK"], ["C", "300", "OK"]]
        for i, row in enumerate(data):
            for j, cell in enumerate(row):
                page.insert_text(fitz.Point(x + j * cw + 10, y + i * ch + 20), cell, fontsize=10)
        pdf_bytes = doc.tobytes()
        doc.close()

        pdf_file = SimpleUploadedFile('test_switch.pdf', pdf_bytes, content_type='application/pdf')
        report = Report.objects.create(
            owner=self.user, name='test_switch', f_type='pdf', document=pdf_file
        )

        selection = TableSelection.objects.create(
            report=report, page_num=1,
            x1=10, y1=20, x2=90, y2=80,
            status='approved', source='manual'
        )

        # Create output directories and initial extracted record
        working_dir = report.document.path.rsplit('/', 1)[0]
        csv_dir = os.path.join(working_dir, 'csv')
        json_dir = os.path.join(working_dir, 'json')
        xlsx_dir = os.path.join(working_dir, 'xlsx')
        os.makedirs(csv_dir, exist_ok=True)
        os.makedirs(json_dir, exist_ok=True)
        os.makedirs(xlsx_dir, exist_ok=True)
        csv_path = os.path.join(csv_dir, 'test-1-table-0.csv')
        with open(csv_path, 'w') as f:
            f.write("Name,Value,Status\nA,100,OK\n")

        extracted = Extracted.objects.create(
            report=report, page_num=1, table_num=0, f_type='csv',
            extraction_method='pdfplumber', selection=selection,
            file=f'test_switch/csv/test-1-table-0.csv'
        )

        # Populate cache with variants including an alternate method
        alt_df = pd.DataFrame({'Name': ['X', 'Y'], 'Value': ['999', '888'], 'Status': ['NEW', 'NEW']})
        variants = [
            {'method': 'pdfplumber', 'dataframe': pd.DataFrame({'Name': ['A'], 'Value': ['100'], 'Status': ['OK']}),
             'score': 0.8, 'confidence': 0.9, 'rows': 1, 'cols': 3, 'metadata': {}},
            {'method': 'camelot_stream', 'dataframe': alt_df,
             'score': 0.85, 'confidence': 0.95, 'rows': 2, 'cols': 3, 'metadata': {}},
        ]
        cache_key = _cache_key_for_selection(report.id, selection.id)
        cache.set(cache_key, _serialize_variants_for_cache(variants), timeout=3600)

        old_extracted_id = extracted.id

        # When: switching to camelot_stream method
        response = self.client.post(
            f'/api/extracted/{extracted.id}/switch-method/',
            {'method': 'camelot_stream'},
            format='json'
        )

        # Then: should succeed with new extraction data
        assert response.status_code == 200
        data = response.json()
        assert data['status'] == 'ok'
        assert data['method'] == 'camelot_stream'
        assert data['rows'] == 2
        assert data['cols'] == 3

        # And: old extracted record should be deleted
        assert not Extracted.objects.filter(id=old_extracted_id).exists()

        # And: new extracted records should exist
        new_extractions = Extracted.objects.filter(report=report, selection_id=selection.id)
        assert new_extractions.count() >= 1

        # Cleanup
        shutil.rmtree(working_dir, ignore_errors=True)


# =============================================================================
# Test extract_from_selections Integration
# =============================================================================

@pytest.mark.django_db(transaction=True)
@override_settings(
    CELERY_TASK_ALWAYS_EAGER=True,
    CELERY_TASK_EAGER_PROPAGATES=True,
    CACHES={
        'default': {
            'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
        }
    }
)
class TestExtractFromSelectionsIntegration(TestCase):
    """Integration tests for extract_from_selections task."""

    def setUp(self):
        self.user = User.objects.create_user(username='testuser', password='testpass123')

    def test_extract_from_selections_creates_extractions(self):
        # Given: a report with a PDF document and approved selection
        import shutil
        from django.core.files.uploadedfile import SimpleUploadedFile
        from api.tasks import extract_from_selections

        # Create PDF with bordered table
        doc = fitz.open()
        page = doc.new_page(width=612, height=792)
        shape = page.new_shape()
        x, y = 100, 200
        cw, ch = 120, 30
        rows, cols = 4, 3
        for i in range(rows + 1):
            shape.draw_line(fitz.Point(x, y + i * ch), fitz.Point(x + cols * cw, y + i * ch))
        for j in range(cols + 1):
            shape.draw_line(fitz.Point(x + j * cw, y), fitz.Point(x + j * cw, y + rows * ch))
        shape.finish(color=(0, 0, 0), width=0.5)
        shape.commit()
        data = [["Name", "Value", "Status"], ["Item A", "100", "Active"],
                ["Item B", "200", "Pending"], ["Item C", "300", "Complete"]]
        for i, row in enumerate(data):
            for j, cell in enumerate(row):
                page.insert_text(fitz.Point(x + j * cw + 10, y + i * ch + 20), cell, fontsize=10)
        pdf_bytes = doc.tobytes()
        doc.close()

        pdf_file = SimpleUploadedFile('integration_test.pdf', pdf_bytes, content_type='application/pdf')
        report = Report.objects.create(
            owner=self.user, name='integration_test', f_type='pdf', document=pdf_file
        )

        # Create approved selection covering the table area (canvas coordinates 0-100)
        # Table is at x=100-460, y=200-320 on 612x792 page
        # Canvas coords: x1=16%, y1=25%, x2=75%, y2=40%
        TableSelection.objects.create(
            report=report, page_num=1,
            x1=16, y1=25, x2=75, y2=41,
            status='approved', source='manual'
        )

        # When: running the extract_from_selections task
        result = extract_from_selections.apply(args=[report.id]).get()

        # Then: extraction should complete successfully
        assert result['status'] in ('completed', 'partial'), f"Unexpected status: {result}"
        assert result['report_id'] == report.id

        # And: extracted records should exist
        extractions = Extracted.objects.filter(report=report)
        assert extractions.count() >= 1, "Expected at least one extraction"

        # And: CSV file should exist
        csv_extractions = extractions.filter(f_type='csv')
        assert csv_extractions.count() >= 1, "Expected CSV extraction"

        # Cleanup
        working_dir = report.document.path.rsplit('/', 1)[0]
        shutil.rmtree(working_dir, ignore_errors=True)

    def test_extract_from_selections_caches_variants(self):
        # Given: a report with approved selection
        import shutil
        from django.core.files.uploadedfile import SimpleUploadedFile
        from django.core.cache import cache
        from api.tasks import extract_from_selections

        # Create simple PDF with table
        doc = fitz.open()
        page = doc.new_page(width=612, height=792)
        shape = page.new_shape()
        x, y = 100, 200
        cw, ch = 120, 30
        for i in range(4):
            shape.draw_line(fitz.Point(x, y + i * ch), fitz.Point(x + 3 * cw, y + i * ch))
        for j in range(4):
            shape.draw_line(fitz.Point(x + j * cw, y), fitz.Point(x + j * cw, y + 3 * ch))
        shape.finish(color=(0, 0, 0), width=0.5)
        shape.commit()
        data = [["Col1", "Col2", "Col3"], ["A", "B", "C"], ["D", "E", "F"]]
        for i, row in enumerate(data):
            for j, cell in enumerate(row):
                page.insert_text(fitz.Point(x + j * cw + 10, y + i * ch + 20), cell, fontsize=10)
        pdf_bytes = doc.tobytes()
        doc.close()

        pdf_file = SimpleUploadedFile('cache_test.pdf', pdf_bytes, content_type='application/pdf')
        report = Report.objects.create(
            owner=self.user, name='cache_test', f_type='pdf', document=pdf_file
        )

        selection = TableSelection.objects.create(
            report=report, page_num=1,
            x1=16, y1=25, x2=75, y2=40,
            status='approved', source='manual'
        )

        # When: running extraction
        extract_from_selections.apply(args=[report.id]).get()

        # Then: variants should be cached
        cache_key = _cache_key_for_selection(report.id, selection.id)
        cached_data = cache.get(cache_key)
        assert cached_data is not None, "Expected variants to be cached"

        variants = _deserialize_variants_from_cache(cached_data)
        assert len(variants) >= 1, "Expected at least one variant in cache"

        # And: each variant should have expected structure
        for v in variants:
            assert 'method' in v
            assert 'score' in v

        # Cleanup
        working_dir = report.document.path.rsplit('/', 1)[0]
        shutil.rmtree(working_dir, ignore_errors=True)
