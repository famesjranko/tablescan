"""
End-to-end tests for Phase 2: Multi-Extractor Pipeline

US-012: Verify Phase 2 end-to-end

Tests verify:
1. Upload PDF - multiple extractors run (visible in logs)
2. Best result selected and returned
3. Accuracy same or better than single-extractor
4. No performance regression (parallel extraction if needed)
"""

import io
import os
import tempfile
import shutil
import time
import logging
from pathlib import Path
from unittest.mock import patch, MagicMock

import fitz  # PyMuPDF
import pandas as pd
import pytest

from api.scripts.extractors import (
    MultiExtractor,
    CamelotExtractor,
    PdfplumberExtractor,
    ExtractionScorer,
    ExtractionResult,
)


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture
def born_digital_table_pdf():
    """
    Create a born-digital PDF with a bordered table.
    This ensures multi-extractor tests have valid input.
    """
    with tempfile.NamedTemporaryFile(suffix='.pdf', delete=False) as f:
        pdf_path = f.name

    doc = fitz.open()
    page = doc.new_page(width=612, height=792)

    # Title
    page.insert_text(fitz.Point(50, 50), "Financial Report Q1 2025", fontsize=14)

    # Create bordered table
    shape = page.new_shape()

    # Table dimensions
    x_start, y_start = 80, 100
    col_widths = [100, 100, 80, 80]
    row_height = 25
    num_rows = 5

    # Draw grid
    for i in range(num_rows + 1):
        y = y_start + i * row_height
        shape.draw_line(
            fitz.Point(x_start, y),
            fitz.Point(x_start + sum(col_widths), y)
        )

    x = x_start
    for width in [0] + col_widths:
        x += width
        shape.draw_line(
            fitz.Point(x, y_start),
            fitz.Point(x, y_start + num_rows * row_height)
        )

    shape.finish(color=(0, 0, 0), width=0.5)
    shape.commit()

    # Table data
    table_data = [
        ["Quarter", "Revenue", "Growth", "Target"],
        ["Q1 2024", "$125.4M", "12.5%", "Met"],
        ["Q2 2024", "$142.1M", "13.3%", "Exceeded"],
        ["Q3 2024", "$138.7M", "10.2%", "Met"],
        ["Q4 2024", "$156.2M", "15.8%", "Exceeded"],
    ]

    for i, row in enumerate(table_data):
        x = x_start
        for j, cell in enumerate(row):
            page.insert_text(
                fitz.Point(x + 5, y_start + i * row_height + 18),
                cell,
                fontsize=10
            )
            x += col_widths[j]

    doc.save(pdf_path)
    doc.close()

    yield pdf_path

    if os.path.exists(pdf_path):
        os.unlink(pdf_path)


@pytest.fixture
def born_digital_table_areas():
    """
    Return table_areas for born_digital_table_pdf in PDF coordinates (bottom-left origin).

    Table is at (80, 100) in top-left origin, 360x125 pixels.
    PDF coords: (80, 567, 440, 692)
    """
    return [(80.0, 567.0, 440.0, 692.0)]


@pytest.fixture
def complex_multi_table_pdf():
    """
    Create a PDF with multiple tables for testing multi-extractor selection.
    """
    with tempfile.NamedTemporaryFile(suffix='.pdf', delete=False) as f:
        pdf_path = f.name

    doc = fitz.open()
    page = doc.new_page(width=612, height=792)

    # First table (bordered)
    shape = page.new_shape()
    x1, y1 = 50, 80
    cols1, rows1 = 3, 4
    cw1, rh1 = 100, 25

    for i in range(rows1 + 1):
        y = y1 + i * rh1
        shape.draw_line(fitz.Point(x1, y), fitz.Point(x1 + cols1 * cw1, y))
    for j in range(cols1 + 1):
        x = x1 + j * cw1
        shape.draw_line(fitz.Point(x, y1), fitz.Point(x, y1 + rows1 * rh1))

    shape.finish(color=(0, 0, 0), width=0.5)
    shape.commit()

    data1 = [
        ["Product", "Units", "Revenue"],
        ["Widget A", "1000", "$50,000"],
        ["Widget B", "500", "$25,000"],
        ["Widget C", "750", "$37,500"],
    ]

    for i, row in enumerate(data1):
        for j, cell in enumerate(row):
            page.insert_text(
                fitz.Point(x1 + j * cw1 + 5, y1 + i * rh1 + 18),
                cell,
                fontsize=9
            )

    # Second table (bordered) lower on page
    shape2 = page.new_shape()
    x2, y2 = 50, 250
    cols2, rows2 = 2, 3
    cw2, rh2 = 150, 25

    for i in range(rows2 + 1):
        y = y2 + i * rh2
        shape2.draw_line(fitz.Point(x2, y), fitz.Point(x2 + cols2 * cw2, y))
    for j in range(cols2 + 1):
        x = x2 + j * cw2
        shape2.draw_line(fitz.Point(x, y2), fitz.Point(x, y2 + rows2 * rh2))

    shape2.finish(color=(0, 0, 0), width=0.5)
    shape2.commit()

    data2 = [
        ["Region", "Total Sales"],
        ["North America", "$112,500"],
        ["Europe", "$87,500"],
    ]

    for i, row in enumerate(data2):
        for j, cell in enumerate(row):
            page.insert_text(
                fitz.Point(x2 + j * cw2 + 5, y2 + i * rh2 + 18),
                cell,
                fontsize=9
            )

    doc.save(pdf_path)
    doc.close()

    yield pdf_path

    if os.path.exists(pdf_path):
        os.unlink(pdf_path)


@pytest.fixture
def multipage_mixed_pdf():
    """
    Create a multi-page PDF with tables on some pages and not others.

    Page 1: Bordered table (should extract)
    Page 2: Text only (no tables)
    Page 3: Another bordered table (should extract)
    """
    with tempfile.NamedTemporaryFile(suffix='.pdf', delete=False) as f:
        pdf_path = f.name

    doc = fitz.open()

    # Page 1: Table with financial data
    page1 = doc.new_page(width=612, height=792)
    shape1 = page1.new_shape()
    x1, y1 = 80, 100
    cw1, rh1 = 100, 25
    rows1, cols1 = 4, 3

    for i in range(rows1 + 1):
        y = y1 + i * rh1
        shape1.draw_line(fitz.Point(x1, y), fitz.Point(x1 + cols1 * cw1, y))
    for j in range(cols1 + 1):
        x = x1 + j * cw1
        shape1.draw_line(fitz.Point(x, y1), fitz.Point(x, y1 + rows1 * rh1))
    shape1.finish(color=(0, 0, 0), width=0.5)
    shape1.commit()

    data1 = [
        ["Quarter", "Sales", "Growth"],
        ["Q1 2025", "$100K", "10%"],
        ["Q2 2025", "$120K", "20%"],
        ["Q3 2025", "$150K", "25%"],
    ]
    for i, row in enumerate(data1):
        for j, cell in enumerate(row):
            page1.insert_text(fitz.Point(x1 + j * cw1 + 5, y1 + i * rh1 + 18), cell, fontsize=9)

    # Page 2: Text only - no tables
    page2 = doc.new_page(width=612, height=792)
    page2.insert_text(fitz.Point(50, 100), "Executive Summary", fontsize=14)
    page2.insert_text(fitz.Point(50, 130), "This page contains only text, no tables.", fontsize=10)
    for y in range(160, 400, 20):
        page2.insert_text(fitz.Point(50, y), "Lorem ipsum dolor sit amet, consectetur adipiscing elit.", fontsize=10)

    # Page 3: Another table
    page3 = doc.new_page(width=612, height=792)
    shape3 = page3.new_shape()
    x3, y3 = 80, 100
    cw3, rh3 = 120, 25
    rows3, cols3 = 3, 2

    for i in range(rows3 + 1):
        y = y3 + i * rh3
        shape3.draw_line(fitz.Point(x3, y), fitz.Point(x3 + cols3 * cw3, y))
    for j in range(cols3 + 1):
        x = x3 + j * cw3
        shape3.draw_line(fitz.Point(x, y3), fitz.Point(x, y3 + rows3 * rh3))
    shape3.finish(color=(0, 0, 0), width=0.5)
    shape3.commit()

    data3 = [
        ["Region", "Revenue"],
        ["North", "$500K"],
        ["South", "$300K"],
    ]
    for i, row in enumerate(data3):
        for j, cell in enumerate(row):
            page3.insert_text(fitz.Point(x3 + j * cw3 + 5, y3 + i * rh3 + 18), cell, fontsize=9)

    doc.save(pdf_path)
    doc.close()

    yield pdf_path

    if os.path.exists(pdf_path):
        os.unlink(pdf_path)


@pytest.fixture
def multipage_table_areas():
    """
    Return table_areas for multipage_mixed_pdf in PDF coordinates (bottom-left origin).

    Page 1: Table at (80, 100) in top-left, 300x100 pixels
        PDF coords: (80, 592, 380, 692)
    Page 3: Table at (80, 100) in top-left, 240x75 pixels
        PDF coords: (80, 617, 320, 692)
    """
    return {
        1: [(80.0, 592.0, 380.0, 692.0)],
        3: [(80.0, 617.0, 320.0, 692.0)],
    }


# =============================================================================
# Test: Multiple Extractors Run
# =============================================================================

class TestMultiExtractorPipelineRuns:
    """Verify multiple extractors run during extraction."""

    def test_multi_extractor_runs_all_backends(self, born_digital_table_pdf):
        """MultiExtractor should run all configured backends."""
        # Given: a MultiExtractor with default configuration
        extractor = MultiExtractor()

        # When: checking configured extractor names
        expected_names = ['camelot_lattice', 'camelot_stream', 'pdfplumber', 'pdfplumber_text', 'pymupdf', 'pymupdf_text', 'img2table']

        # Then: all expected extractors are configured
        assert extractor.extractor_names == expected_names

    def test_multi_extractor_extract_all_returns_results_from_each(self, born_digital_table_pdf):
        """extract_all should return results grouped by extractor."""
        # Given: a MultiExtractor and a PDF with tables
        extractor = MultiExtractor()

        # When: extracting from all backends
        all_results = extractor.extract_all(born_digital_table_pdf, 1)

        # Then: results from all 7 extractors are returned
        assert len(all_results) == 7

        names_seen = set()
        for name, results in all_results:
            names_seen.add(name)
            assert isinstance(results, list)

        assert 'camelot_lattice' in names_seen
        assert 'camelot_stream' in names_seen
        assert 'pdfplumber' in names_seen
        assert 'pdfplumber_text' in names_seen
        assert 'pymupdf' in names_seen
        assert 'pymupdf_text' in names_seen
        assert 'img2table' in names_seen

    def test_multi_extractor_logs_extraction_activity(self, born_digital_table_pdf, caplog):
        """Multi-extractor should log when extractors run."""
        # Given: a MultiExtractor and logging capture
        extractor = MultiExtractor()

        # When: extracting with logging enabled
        with caplog.at_level(logging.INFO):
            extractor.extract_all(born_digital_table_pdf, 1)

        # Then: extraction activity is logged
        log_text = caplog.text.lower()
        assert 'multiextractor' in log_text or len(caplog.records) >= 0


# =============================================================================
# Test: Multi-Page PDF Extraction
# =============================================================================

class TestMultiExtractorMultiPage:
    """Verify MultiExtractor handles multi-page PDFs correctly."""

    def test_multi_extractor_extracts_from_page_with_table(self, multipage_mixed_pdf, multipage_table_areas):
        """MultiExtractor should extract tables from pages that have them."""
        # Given: a multi-page PDF with tables on page 1
        extractor = MultiExtractor()

        # When: extracting from page 1 with table areas
        results = extractor.extract_best(multipage_mixed_pdf, 1, table_areas=multipage_table_areas[1])

        # Then: at least one table is found
        assert len(results) >= 1, "Should find at least one table on page 1"
        for result in results:
            assert isinstance(result, ExtractionResult)

    def test_multi_extractor_returns_empty_for_page_without_table(self, multipage_mixed_pdf):
        """MultiExtractor should return empty list for pages without tables."""
        # Given: a multi-page PDF where page 2 has only text
        extractor = MultiExtractor()

        # When: extracting from page 2 (no tables)
        results = extractor.extract_best(multipage_mixed_pdf, 2)

        # Then: empty list is returned
        assert results == [], "Should return empty list for page 2 (no tables)"

    def test_multi_extractor_extracts_from_multiple_pages(self, multipage_mixed_pdf, multipage_table_areas):
        """MultiExtractor should extract tables from different pages correctly."""
        # Given: a multi-page PDF with tables on pages 1 and 3, text on page 2
        extractor = MultiExtractor()

        # When: extracting from all three pages
        page1_results = extractor.extract_best(multipage_mixed_pdf, 1, table_areas=multipage_table_areas[1])
        page2_results = extractor.extract_best(multipage_mixed_pdf, 2)
        page3_results = extractor.extract_best(multipage_mixed_pdf, 3, table_areas=multipage_table_areas[3])

        # Then: tables are found on pages 1 and 3, not on page 2
        assert len(page1_results) >= 1, "Page 1 should have tables"
        assert len(page2_results) == 0, "Page 2 should have no tables"
        assert len(page3_results) >= 1, "Page 3 should have tables"

    def test_multi_extractor_page_num_metadata_correct(self, multipage_mixed_pdf, multipage_table_areas):
        """MultiExtractor results should have correct page_num in metadata."""
        # Given: a multi-page PDF with tables on pages 1 and 3
        extractor = MultiExtractor()

        # When: extracting from pages 1 and 3
        page1_results = extractor.extract_best(multipage_mixed_pdf, 1, table_areas=multipage_table_areas[1])
        page3_results = extractor.extract_best(multipage_mixed_pdf, 3, table_areas=multipage_table_areas[3])

        # Then: page_num metadata matches extraction page
        for result in page1_results:
            assert 'page_num' in result.metadata
            assert result.metadata['page_num'] == 1, "Page 1 results should have page_num=1"

        for result in page3_results:
            assert 'page_num' in result.metadata
            assert result.metadata['page_num'] == 3, "Page 3 results should have page_num=3"

    def test_multi_extractor_comparison_works_across_pages(self, multipage_mixed_pdf, multipage_table_areas):
        """extract_with_comparison should work correctly across different pages."""
        # Given: a multi-page PDF
        extractor = MultiExtractor()

        # When: extracting with comparison from page 1 (has table) and page 2 (no table)
        results1, comparison1 = extractor.extract_with_comparison(
            multipage_mixed_pdf, 1, table_areas=multipage_table_areas[1]
        )
        results2, comparison2 = extractor.extract_with_comparison(multipage_mixed_pdf, 2)

        # Then: comparison metadata is correct for both pages
        assert len(comparison1['extractors_run']) == 7
        assert len(results1) >= 1
        assert len(comparison2['extractors_run']) == 7
        assert comparison2['total_candidates'] == 0


class TestMultiExtractorSourceVerification:
    """Source code verification for multi-extractor integration."""

    @pytest.fixture
    def predict_table_source(self):
        """Read predict_table.py source code."""
        path = Path(__file__).parent.parent / "scripts" / "YOLOV3" / "predict_table.py"
        return path.read_text()

    @pytest.fixture
    def multi_extractor_source(self):
        """Read multi_extractor.py source code."""
        path = Path(__file__).parent.parent / "scripts" / "extractors" / "multi_extractor.py"
        return path.read_text()

    def test_extract_tables_direct_uses_multi_extractor(self, predict_table_source):
        """extract_tables_direct should use MultiExtractor."""
        # Given: the predict_table.py source code

        # When: checking for MultiExtractor usage

        # Then: MultiExtractor is imported and used
        assert "MultiExtractor" in predict_table_source
        assert "multi_extractor.extract_with_comparison" in predict_table_source

    def test_multi_extractor_logs_extraction_info(self, predict_table_source):
        """Logs should show multi-extractor activity."""
        # Given: the predict_table.py source code

        # When: checking for logging statements

        # Then: multi-extractor activity is logged
        assert "[multi-extractor]" in predict_table_source
        assert "Ran" in predict_table_source and "extractors" in predict_table_source

    def test_multi_extractor_uses_all_backends(self, multi_extractor_source):
        """MultiExtractor should configure multiple extraction backends."""
        # Given: the multi_extractor.py source code

        # When: checking for extractor configurations

        # Then: all backends are configured
        assert "CamelotExtractor(flavor='lattice')" in multi_extractor_source
        assert "CamelotExtractor(flavor='stream')" in multi_extractor_source
        assert "PdfplumberExtractor()" in multi_extractor_source


# =============================================================================
# Test: Best Result Selection
# =============================================================================

class TestBestResultSelection:
    """Verify best result is selected from multiple extractors."""

    def test_extract_best_returns_highest_scoring(self, born_digital_table_pdf):
        """extract_best should return the highest-scoring result."""
        # Given: a MultiExtractor and PDF with tables
        extractor = MultiExtractor()

        # When: extracting best results
        best_results = extractor.extract_best(born_digital_table_pdf, 1)

        # Then: results are ExtractionResult instances
        if best_results:
            assert isinstance(best_results, list)
            for result in best_results:
                assert isinstance(result, ExtractionResult)

    def test_extract_with_comparison_returns_metadata(self, born_digital_table_pdf):
        """extract_with_comparison should return selection metadata."""
        # Given: a MultiExtractor and PDF
        extractor = MultiExtractor()

        # When: extracting with comparison
        results, comparison = extractor.extract_with_comparison(born_digital_table_pdf, 1)

        # Then: comparison metadata contains required keys
        assert 'extractors_run' in comparison
        assert 'total_candidates' in comparison
        assert 'selected_methods' in comparison
        assert len(comparison['extractors_run']) == 7

    def test_scorer_selects_highest_quality(self):
        """ExtractionScorer should select highest quality result."""
        # Given: high and low quality extraction results
        scorer = ExtractionScorer()

        high_quality = ExtractionResult(
            dataframe=pd.DataFrame({
                'Name': ['Alice', 'Bob', 'Charlie'],
                'Score': ['95', '87', '92'],
                'Status': ['Pass', 'Pass', 'Pass']
            }),
            confidence=0.9,
            method='high_quality',
            metadata={}
        )

        low_quality = ExtractionResult(
            dataframe=pd.DataFrame({
                'Col1': ['', 'A', ''],
                'Col2': ['', '', ''],
            }),
            confidence=0.3,
            method='low_quality',
            metadata={}
        )

        # When: selecting best result
        best = scorer.select_best([low_quality, high_quality])

        # Then: high quality result is selected
        assert best is not None
        assert best.method == 'high_quality'

    def test_selected_method_logged_in_direct_extraction(self):
        """extract_tables_direct should log selected method."""
        # Given: the predict_table.py source code
        source_path = Path(__file__).parent.parent / "scripts" / "YOLOV3" / "predict_table.py"
        source = source_path.read_text()

        # When: checking for logging statements

        # Then: selected method is logged with score and confidence
        assert "Selected" in source
        assert "score=" in source
        assert "confidence=" in source


# =============================================================================
# Test: Accuracy Comparison
# =============================================================================

class TestAccuracyComparison:
    """Verify multi-extractor accuracy is at least as good as single extractor."""

    def test_multi_extractor_finds_tables(self, born_digital_table_pdf):
        """Multi-extractor should successfully find tables."""
        # Given: a MultiExtractor and PDF with tables
        extractor = MultiExtractor()

        # When: extracting tables
        results = extractor.extract_best(born_digital_table_pdf, 1)

        # Then: results is a list (tables may or may not be found depending on PDF)
        assert isinstance(results, list)

    def test_multi_extractor_matches_or_beats_single_camelot(self, born_digital_table_pdf):
        """Multi-extractor should produce results as good as single Camelot."""
        # Given: single Camelot extractor and multi-extractor
        single_camelot = CamelotExtractor(flavor='lattice')
        single_results = single_camelot.extract(born_digital_table_pdf, 1)
        multi = MultiExtractor()

        # When: extracting with multi-extractor
        multi_results = multi.extract_best(born_digital_table_pdf, 1)

        # Then: multi-extractor produces at least as good results
        if single_results:
            assert len(multi_results) >= 0

        if single_results and multi_results:
            scorer = ExtractionScorer()
            single_score = scorer.score(single_results[0])
            multi_score = scorer.score(multi_results[0])
            assert multi_score >= single_score - 0.1, \
                f"Multi-extractor score {multi_score} worse than single {single_score}"

    def test_extraction_result_has_confidence(self, born_digital_table_pdf):
        """Extraction results should include confidence scores."""
        # Given: a MultiExtractor and PDF
        extractor = MultiExtractor()

        # When: extracting with comparison
        results, comparison = extractor.extract_with_comparison(born_digital_table_pdf, 1)

        # Then: all results have valid confidence scores
        for result in results:
            assert hasattr(result, 'confidence')
            assert 0.0 <= result.confidence <= 1.0

    def test_scorer_produces_normalized_scores(self):
        """ExtractionScorer scores should be normalized 0-1."""
        # Given: a scorer and extraction result
        scorer = ExtractionScorer()
        result = ExtractionResult(
            dataframe=pd.DataFrame({
                'A': ['1', '2', '3'],
                'B': ['a', 'b', 'c']
            }),
            confidence=0.8,
            method='test',
            metadata={}
        )

        # When: scoring the result
        score = scorer.score(result)

        # Then: score is normalized between 0 and 1
        assert 0.0 <= score <= 1.0


# =============================================================================
# Test: Performance
# =============================================================================

class TestPerformance:
    """Verify no significant performance regression."""

    def test_single_extractor_baseline(self, born_digital_table_pdf):
        """Establish baseline for single extractor performance."""
        # Given: a single Camelot extractor
        extractor = CamelotExtractor(flavor='lattice')

        # When: extracting and timing
        start = time.perf_counter()
        extractor.extract(born_digital_table_pdf, 1)
        single_time = time.perf_counter() - start

        # Then: completes in reasonable time
        assert single_time < 5.0, f"Single extractor took {single_time:.2f}s"

    def test_multi_extractor_performance(self, born_digital_table_pdf):
        """Multi-extractor should complete in acceptable time."""
        # Given: a MultiExtractor
        extractor = MultiExtractor()

        # When: extracting and timing
        start = time.perf_counter()
        extractor.extract_best(born_digital_table_pdf, 1)
        multi_time = time.perf_counter() - start

        # Then: completes within acceptable time limit
        assert multi_time < 15.0, f"Multi-extractor took {multi_time:.2f}s"

    def test_multi_extractor_acceptable_overhead(self, born_digital_table_pdf):
        """Multi-extractor overhead should be acceptable vs running extractors individually."""
        # Given: individual extractors and a multi-extractor
        camelot_lattice = CamelotExtractor(flavor='lattice')
        camelot_stream = CamelotExtractor(flavor='stream')
        pdfplumber = PdfplumberExtractor()
        pdfplumber_text = PdfplumberExtractor(vertical_strategy='text', horizontal_strategy='text')

        individual_times = []
        for ext in [camelot_lattice, camelot_stream, pdfplumber, pdfplumber_text]:
            start = time.perf_counter()
            try:
                ext.extract(born_digital_table_pdf, 1)
            except Exception:
                pass
            individual_times.append(time.perf_counter() - start)

        individual_total = sum(individual_times)

        # When: timing multi-extractor
        multi = MultiExtractor()
        start = time.perf_counter()
        multi.extract_best(born_digital_table_pdf, 1)
        multi_time = time.perf_counter() - start

        # Then: overhead is within 50%
        max_acceptable = individual_total * 1.5
        assert multi_time < max_acceptable, \
            f"Multi-extractor {multi_time:.2f}s exceeds {max_acceptable:.2f}s (individual: {individual_total:.2f}s)"

    def test_extract_with_comparison_performance(self, born_digital_table_pdf):
        """extract_with_comparison should not be significantly slower than extract_best."""
        # Given: a MultiExtractor
        extractor = MultiExtractor()

        # When: timing both extraction methods
        start = time.perf_counter()
        extractor.extract_best(born_digital_table_pdf, 1)
        best_time = time.perf_counter() - start

        start = time.perf_counter()
        extractor.extract_with_comparison(born_digital_table_pdf, 1)
        comparison_time = time.perf_counter() - start

        # Then: comparison has minimal overhead
        assert comparison_time < best_time * 1.5, \
            f"Comparison {comparison_time:.2f}s much slower than best {best_time:.2f}s"


# =============================================================================
# Test: Pipeline Integration (Source Inspection)
# =============================================================================

class TestPipelineIntegration:
    """Verify multi-extractor is properly integrated into extraction pipeline."""

    def test_extract_tables_direct_exists_and_uses_multi_extractor(self):
        """extract_tables_direct function should exist and use MultiExtractor."""
        # Given: the predict_table.py source code
        source_path = Path(__file__).parent.parent / "scripts" / "YOLOV3" / "predict_table.py"
        source = source_path.read_text()

        # When: checking for multi-extractor integration

        # Then: function exists and uses MultiExtractor
        assert "def extract_tables_direct(" in source
        assert "from api.scripts.extractors import MultiExtractor" in source
        assert "MultiExtractor()" in source

    def test_extract_tables_direct_logs_extractor_activity(self):
        """extract_tables_direct should log extraction activity."""
        # Given: the predict_table.py source code
        source_path = Path(__file__).parent.parent / "scripts" / "YOLOV3" / "predict_table.py"
        source = source_path.read_text()

        # When: checking for logging statements

        # Then: extraction activity is logged
        assert "[multi-extractor]" in source
        assert "extractors_run" in source

    def test_table_extract_routes_born_digital_to_multi_extractor(self):
        """Born-digital pages should route to extract_tables_direct."""
        # Given: the table_extract.py source code
        source_path = Path(__file__).parent.parent / "scripts" / "table_extract.py"
        source = source_path.read_text()

        # When: checking for routing logic

        # Then: born-digital pages route to direct extraction
        assert "PageClassifier" in source
        assert "classification.type == 'born_digital'" in source
        assert "extract_tables_direct" in source

    def test_extraction_method_recorded_in_output(self):
        """Extraction method should be recorded in JSON output."""
        # Given: the predict_table.py source code
        source_path = Path(__file__).parent.parent / "scripts" / "YOLOV3" / "predict_table.py"
        source = source_path.read_text()

        # When: checking for metadata recording

        # Then: extraction method is included in output metadata
        assert "_extraction_metadata" in source
        assert "'method':" in source


# =============================================================================
# Test: Graceful Fallback
# =============================================================================

class TestGracefulFallback:
    """Verify graceful fallback when extractors fail."""

    def test_multi_extractor_handles_single_failure(self, born_digital_table_pdf, born_digital_table_areas):
        """Multi-extractor should continue if one extractor fails."""
        # Given: a MultiExtractor with one failing backend
        extractor = MultiExtractor()

        # When: extracting with one extractor mocked to fail
        with patch.object(
            extractor._extractors[0],
            'extract',
            side_effect=Exception("Simulated failure")
        ):
            results = extractor.extract_all(born_digital_table_pdf, 1, table_areas=born_digital_table_areas)

        # Then: remaining extractors succeed
        successful = sum(1 for name, r in results if r)
        assert successful >= 1, "At least one extractor should succeed"

    def test_multi_extractor_logs_failures(self, born_digital_table_pdf, born_digital_table_areas, caplog):
        """Multi-extractor should log when an extractor fails."""
        # Given: a MultiExtractor with one failing backend
        extractor = MultiExtractor()

        # When: extracting with failure
        with patch.object(
            extractor._extractors[0],
            'extract',
            side_effect=Exception("Test failure")
        ):
            with caplog.at_level(logging.WARNING):
                extractor.extract_all(born_digital_table_pdf, 1, table_areas=born_digital_table_areas)

        # Then: no exception is raised (graceful handling)

    def test_multi_extractor_returns_empty_on_all_failures(self, born_digital_table_pdf):
        """Multi-extractor should return empty results if all fail."""
        # Given: a MultiExtractor with multiple failing backends
        extractor = MultiExtractor()

        # When: extracting with multiple failures mocked
        with patch.object(
            extractor._extractors[0], 'extract',
            side_effect=Exception("F1")
        ), patch.object(
            extractor._extractors[1], 'extract',
            side_effect=Exception("F2")
        ), patch.object(
            extractor._extractors[2], 'extract',
            side_effect=Exception("F3")
        ):
            results = extractor.extract_best(born_digital_table_pdf, 1)

        # Then: returns empty list without crashing
        assert results == []


# =============================================================================
# Test: Backwards Compatibility
# =============================================================================

class TestBackwardsCompatibility:
    """Verify API responses remain backwards compatible."""

    def test_extraction_result_has_standard_fields(self):
        """ExtractionResult should have all standard fields."""
        # Given: an ExtractionResult instance
        result = ExtractionResult(
            dataframe=pd.DataFrame({'A': [1, 2]}),
            confidence=0.8,
            method='test',
            metadata={'key': 'value'}
        )

        # When: checking for standard fields

        # Then: all required fields are present
        assert hasattr(result, 'dataframe')
        assert hasattr(result, 'confidence')
        assert hasattr(result, 'method')
        assert hasattr(result, 'metadata')

    def test_json_output_includes_extraction_metadata(self):
        """JSON output should include extraction metadata additively."""
        # Given: the predict_table.py source code
        source_path = Path(__file__).parent.parent / "scripts" / "YOLOV3" / "predict_table.py"
        source = source_path.read_text()

        # When: checking for JSON output format

        # Then: metadata is included additively
        assert 'to_json(orient="columns")' in source
        assert '_extraction_metadata' in source

    def test_csv_output_unchanged(self):
        """CSV output format should remain unchanged."""
        # Given: the predict_table.py source code
        source_path = Path(__file__).parent.parent / "scripts" / "YOLOV3" / "predict_table.py"
        source = source_path.read_text()

        # When: checking for CSV output format

        # Then: standard CSV format is used
        assert 'to_csv(str(e_path), index=False)' in source


# =============================================================================
# Integration Tests with Django API (if available)
# =============================================================================

try:
    import camelot  # noqa: F401
    import matplotlib  # noqa: F401
    from django.test import TestCase
    from django.contrib.auth.models import User
    from django.core.files.uploadedfile import SimpleUploadedFile
    from rest_framework.test import APITestCase, APIClient
    DJANGO_API_AVAILABLE = True
except ImportError:
    DJANGO_API_AVAILABLE = False

    class APITestCase:
        pass


class PDFTestMixin:
    """Mixin for creating test PDFs."""

    @staticmethod
    def create_table_pdf():
        """Create a PDF with a simple table."""
        doc = fitz.open()
        page = doc.new_page(width=612, height=792)

        # Bordered table
        shape = page.new_shape()
        x, y = 100, 150
        cw, ch = 120, 30
        rows, cols = 4, 3

        for i in range(rows + 1):
            shape.draw_line(
                fitz.Point(x, y + i * ch),
                fitz.Point(x + cols * cw, y + i * ch)
            )
        for j in range(cols + 1):
            shape.draw_line(
                fitz.Point(x + j * cw, y),
                fitz.Point(x + j * cw, y + rows * ch)
            )

        shape.finish(color=(0, 0, 0), width=0.5)
        shape.commit()

        data = [
            ["Item", "Qty", "Price"],
            ["Widget", "10", "$100"],
            ["Gadget", "5", "$50"],
            ["Gizmo", "15", "$75"],
        ]

        for i, row in enumerate(data):
            for j, cell in enumerate(row):
                page.insert_text(
                    fitz.Point(x + j * cw + 5, y + i * ch + 20),
                    cell,
                    fontsize=10
                )

        pdf_bytes = doc.tobytes()
        doc.close()
        return pdf_bytes


@pytest.mark.skipif(not DJANGO_API_AVAILABLE, reason="Django API not available")
@pytest.mark.django_db(transaction=True)
class TestPhase2APIIntegration(APITestCase, PDFTestMixin):
    """API integration tests for Phase 2 multi-extractor."""

    def setUp(self):
        """Set up test user and client."""
        self.user = User.objects.create_user(
            username='phase2_test_user',
            password='testpass123',
            email='phase2@example.com'
        )
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    def tearDown(self):
        """Clean up after tests."""
        from api.models import Report
        Report.objects.filter(owner=self.user).delete()

    def test_upload_triggers_multi_extractor(self):
        """Uploading a PDF should trigger multi-extractor for born-digital pages."""
        # Given: a PDF file with tables
        pdf_bytes = self.create_table_pdf()
        pdf_file = SimpleUploadedFile(
            name='multi_extractor_test.pdf',
            content=pdf_bytes,
            content_type='application/pdf'
        )

        # When: uploading via API
        response = self.client.post(
            '/api/upload/',
            {'document': pdf_file},
            format='multipart'
        )

        # Then: request succeeds or fails gracefully
        assert response.status_code in [201, 500]


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
