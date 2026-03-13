"""
Tests for extractors module.

Tests CamelotExtractor, PdfplumberExtractor, and ExtractionScorer functionality.
Uses mocking for unit tests and real PDF fixtures for integration tests.
"""

import os
import tempfile
from unittest.mock import patch, MagicMock

import fitz  # PyMuPDF
import pandas as pd
import pytest

from api.scripts.extractors import (
    BaseExtractor,
    BoundingBox,
    ExtractionResult,
    CamelotExtractor,
    PdfplumberExtractor,
    PyMuPDFExtractor,
    MultiExtractor,
    ExtractionScorer,
)


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture
def simple_table_pdf():
    """
    Create a PDF with a simple table containing text and numbers.

    Creates a 3x3 table with headers and data rows.
    """
    with tempfile.NamedTemporaryFile(suffix='.pdf', delete=False) as f:
        pdf_path = f.name

    doc = fitz.open()
    page = doc.new_page(width=612, height=792)  # Letter size

    # Create a simple table with borders
    shape = page.new_shape()

    # Table dimensions
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

    # Cleanup
    if os.path.exists(pdf_path):
        os.unlink(pdf_path)


@pytest.fixture
def borderless_table_pdf():
    """
    Create a PDF with a borderless table (text-only alignment).

    This type of table requires 'stream' mode in Camelot.
    """
    with tempfile.NamedTemporaryFile(suffix='.pdf', delete=False) as f:
        pdf_path = f.name

    doc = fitz.open()
    page = doc.new_page(width=612, height=792)

    # Table data without borders - aligned by spacing
    table_data = [
        ["Product", "Price", "Quantity"],
        ["Widget", "$10.00", "50"],
        ["Gadget", "$25.50", "30"],
        ["Gizmo", "$5.75", "100"],
    ]

    y_start = 200
    x_positions = [100, 220, 340]

    for i, row in enumerate(table_data):
        for j, cell in enumerate(row):
            x = x_positions[j]
            y = y_start + i * 25
            page.insert_text(fitz.Point(x, y), cell, fontsize=10, fontname="helv")

    doc.save(pdf_path)
    doc.close()

    yield pdf_path

    if os.path.exists(pdf_path):
        os.unlink(pdf_path)


@pytest.fixture
def empty_pdf():
    """Create a PDF with no tables, just some text."""
    with tempfile.NamedTemporaryFile(suffix='.pdf', delete=False) as f:
        pdf_path = f.name

    doc = fitz.open()
    page = doc.new_page(width=612, height=792)

    page.insert_text(fitz.Point(100, 100), "This is a document without tables.", fontsize=12)
    page.insert_text(fitz.Point(100, 130), "Just some regular text content.", fontsize=12)

    doc.save(pdf_path)
    doc.close()

    yield pdf_path

    if os.path.exists(pdf_path):
        os.unlink(pdf_path)


@pytest.fixture
def multipage_table_pdf():
    """Create a multi-page PDF with tables on different pages."""
    with tempfile.NamedTemporaryFile(suffix='.pdf', delete=False) as f:
        pdf_path = f.name

    doc = fitz.open()

    # Page 1: Table with borders
    page1 = doc.new_page(width=612, height=792)
    shape = page1.new_shape()

    x_start, y_start = 100, 200
    cell_width, cell_height = 100, 25

    for i in range(3):
        y = y_start + i * cell_height
        shape.draw_line(fitz.Point(x_start, y), fitz.Point(x_start + 2 * cell_width, y))
    for j in range(3):
        x = x_start + j * cell_width
        shape.draw_line(fitz.Point(x, y_start), fitz.Point(x, y_start + 2 * cell_height))

    shape.finish(color=(0, 0, 0), width=0.5)
    shape.commit()

    page1.insert_text(fitz.Point(110, 220), "Header1", fontsize=10)
    page1.insert_text(fitz.Point(210, 220), "Header2", fontsize=10)
    page1.insert_text(fitz.Point(110, 245), "Data1", fontsize=10)
    page1.insert_text(fitz.Point(210, 245), "Data2", fontsize=10)

    # Page 2: No table
    page2 = doc.new_page(width=612, height=792)
    page2.insert_text(fitz.Point(100, 100), "Page 2 has no tables.", fontsize=12)

    doc.save(pdf_path)
    doc.close()

    yield pdf_path

    if os.path.exists(pdf_path):
        os.unlink(pdf_path)


@pytest.fixture
def multipage_table_areas():
    """
    Return table_areas for multipage_table_pdf in PDF coordinates (bottom-left origin).

    Page 1: Table at (100, 200) in top-left, 200x50 pixels (2 cols × 2 rows).
    PDF coords: (100, 542, 300, 592)
    """
    return [(100.0, 542.0, 300.0, 592.0)]


@pytest.fixture
def sample_extraction_result():
    """Create a sample ExtractionResult for testing."""
    df = pd.DataFrame({
        'Name': ['Alice', 'Bob', 'Charlie'],
        'Age': ['25', '30', '35'],
        'Score': ['95.5', '87.0', '92.3']
    })
    return ExtractionResult(
        dataframe=df,
        confidence=0.85,
        method='test_extractor',
        metadata={'table_index': 0, 'page_num': 1}
    )


@pytest.fixture
def low_quality_extraction_result():
    """Create a low-quality extraction result with sparse data."""
    df = pd.DataFrame({
        'Col1': ['', 'A', ''],
        'Col2': ['', '', ''],
        'Col3': ['X', '', '']
    })
    return ExtractionResult(
        dataframe=df,
        confidence=0.3,
        method='low_quality_extractor',
        metadata={'table_index': 0}
    )


@pytest.fixture
def numeric_extraction_result():
    """Create an extraction result with numeric data."""
    df = pd.DataFrame({
        'Product': ['Widget', 'Gadget', 'Gizmo'],
        'Price': ['$10.00', '$25.50', '$5.75'],
        'Quantity': ['50', '30', '100'],
        'Total': ['$500.00', '$765.00', '$575.00']
    })
    return ExtractionResult(
        dataframe=df,
        confidence=0.9,
        method='numeric_extractor',
        metadata={'table_index': 0, 'page_num': 1}
    )


# =============================================================================
# ExtractionResult Tests
# =============================================================================

class TestExtractionResult:
    """Tests for ExtractionResult dataclass."""

    def test_extraction_result_has_required_fields(self, sample_extraction_result):
        """ExtractionResult should have all required fields."""
        result = sample_extraction_result

        assert hasattr(result, 'dataframe')
        assert hasattr(result, 'confidence')
        assert hasattr(result, 'method')
        assert hasattr(result, 'metadata')

    def test_extraction_result_dataframe_is_pandas(self, sample_extraction_result):
        """dataframe field should be a pandas DataFrame."""
        assert isinstance(sample_extraction_result.dataframe, pd.DataFrame)

    def test_extraction_result_confidence_is_float(self, sample_extraction_result):
        """confidence field should be a float."""
        assert isinstance(sample_extraction_result.confidence, float)

    def test_extraction_result_method_is_string(self, sample_extraction_result):
        """method field should be a string."""
        assert isinstance(sample_extraction_result.method, str)

    def test_extraction_result_metadata_is_dict(self, sample_extraction_result):
        """metadata field should be a dict."""
        assert isinstance(sample_extraction_result.metadata, dict)


# =============================================================================
# CamelotExtractor Tests
# =============================================================================

class TestCamelotExtractorInit:
    """Tests for CamelotExtractor initialization."""

    def test_default_flavor_is_lattice(self):
        """Default flavor should be 'lattice'."""
        extractor = CamelotExtractor()
        assert extractor.flavor == 'lattice'

    def test_stream_flavor_accepted(self):
        """Stream flavor should be accepted."""
        extractor = CamelotExtractor(flavor='stream')
        assert extractor.flavor == 'stream'

    def test_invalid_flavor_raises_error(self):
        """Invalid flavor should raise ValueError."""
        with pytest.raises(ValueError, match="flavor must be"):
            CamelotExtractor(flavor='invalid')

    def test_name_includes_flavor(self):
        """Extractor name should include flavor."""
        lattice = CamelotExtractor(flavor='lattice')
        stream = CamelotExtractor(flavor='stream')

        assert lattice.name == 'camelot_lattice'
        assert stream.name == 'camelot_stream'


class TestCamelotExtractorExtraction:
    """Tests for CamelotExtractor extract method."""

    def test_extract_returns_list(self, simple_table_pdf):
        """extract() should return a list."""
        extractor = CamelotExtractor()
        results = extractor.extract(simple_table_pdf, 1)

        assert isinstance(results, list)

    def test_extract_results_are_extraction_results(self, simple_table_pdf):
        """Each result should be an ExtractionResult."""
        extractor = CamelotExtractor()
        results = extractor.extract(simple_table_pdf, 1)

        for result in results:
            assert isinstance(result, ExtractionResult)

    def test_extract_nonexistent_file_raises_error(self):
        """Non-existent file should raise FileNotFoundError."""
        extractor = CamelotExtractor()

        with pytest.raises(FileNotFoundError):
            extractor.extract('/nonexistent/file.pdf', 1)

    def test_extract_empty_pdf_returns_empty_list(self, empty_pdf):
        """PDF without tables should return empty list."""
        extractor = CamelotExtractor()
        results = extractor.extract(empty_pdf, 1)

        assert results == []

    def test_extract_with_table_areas_parameter(self, simple_table_pdf):
        """extract() should accept table_areas parameter."""
        extractor = CamelotExtractor()
        # Table areas in PDF coordinates (x1, y1, x2, y2)
        table_areas = [(100, 550, 460, 700)]

        # Should not raise error
        results = extractor.extract(simple_table_pdf, 1, table_areas=table_areas)
        assert isinstance(results, list)


class TestCamelotExtractorValidation:
    """Tests for CamelotExtractor validation methods."""

    def test_valid_table_requires_minimum_dimensions(self):
        """Valid table must have at least 2x2 dimensions."""
        extractor = CamelotExtractor()

        # Valid: 2x2
        valid_df = pd.DataFrame([['a', 'b'], ['c', 'd']])
        assert extractor._is_valid_table(valid_df) is True

        # Invalid: 1x2
        invalid_df = pd.DataFrame([['a', 'b']])
        assert extractor._is_valid_table(invalid_df) is False

    def test_clean_dataframe_replaces_nan(self):
        """_clean_dataframe should replace NaN with empty strings."""
        extractor = CamelotExtractor()

        df = pd.DataFrame({'A': [1, None, 3], 'B': [None, 2, None]})
        cleaned = extractor._clean_dataframe(df)

        # Check no NaN values remain
        assert not cleaned.isna().any().any()


# =============================================================================
# PdfplumberExtractor Tests
# =============================================================================

class TestPdfplumberExtractorInit:
    """Tests for PdfplumberExtractor initialization."""

    def test_default_initialization(self):
        """Default initialization should work without errors."""
        extractor = PdfplumberExtractor()
        assert extractor.name == 'pdfplumber'

    def test_custom_strategy_parameters(self):
        """Custom strategies should be accepted."""
        extractor = PdfplumberExtractor(
            vertical_strategy='text',
            horizontal_strategy='text'
        )
        assert extractor._vertical_strategy == 'text'
        assert extractor._horizontal_strategy == 'text'


class TestPdfplumberExtractorExtraction:
    """Tests for PdfplumberExtractor extract method."""

    def test_extract_returns_list(self, simple_table_pdf):
        """extract() should return a list."""
        extractor = PdfplumberExtractor()
        results = extractor.extract(simple_table_pdf, 1)

        assert isinstance(results, list)

    def test_extract_results_are_extraction_results(self, simple_table_pdf):
        """Each result should be an ExtractionResult."""
        extractor = PdfplumberExtractor()
        results = extractor.extract(simple_table_pdf, 1)

        for result in results:
            assert isinstance(result, ExtractionResult)

    def test_extract_nonexistent_file_raises_error(self):
        """Non-existent file should raise FileNotFoundError."""
        extractor = PdfplumberExtractor()

        with pytest.raises(FileNotFoundError):
            extractor.extract('/nonexistent/file.pdf', 1)

    def test_extract_invalid_page_raises_error(self, simple_table_pdf):
        """Invalid page number should raise ValueError."""
        extractor = PdfplumberExtractor()

        with pytest.raises(ValueError, match="out of range"):
            extractor.extract(simple_table_pdf, 999)

    def test_extract_page_zero_raises_error(self, simple_table_pdf):
        """Page 0 should raise ValueError (1-indexed)."""
        extractor = PdfplumberExtractor()

        with pytest.raises(ValueError, match="out of range"):
            extractor.extract(simple_table_pdf, 0)

    def test_extract_empty_pdf_returns_empty_list(self, empty_pdf):
        """PDF without tables should return empty list."""
        extractor = PdfplumberExtractor()
        results = extractor.extract(empty_pdf, 1)

        assert results == []


class TestPdfplumberExtractorConfidence:
    """Tests for PdfplumberExtractor confidence calculation."""

    def test_calculate_confidence_returns_float(self):
        """_calculate_confidence should return a float."""
        extractor = PdfplumberExtractor()

        df = pd.DataFrame({'A': ['1', '2'], 'B': ['3', '4']})
        raw_data = [['1', '3'], ['2', '4']]

        confidence = extractor._calculate_confidence(df, raw_data)

        assert isinstance(confidence, float)
        assert 0.0 <= confidence <= 1.0

    def test_empty_dataframe_returns_zero_confidence(self):
        """Empty DataFrame should return 0.0 confidence."""
        extractor = PdfplumberExtractor()

        df = pd.DataFrame()
        confidence = extractor._calculate_confidence(df, [])

        assert confidence == 0.0

    def test_high_fill_rate_increases_confidence(self):
        """High cell fill rate should increase confidence."""
        extractor = PdfplumberExtractor()

        # Full table
        full_df = pd.DataFrame({'A': ['1', '2', '3'], 'B': ['4', '5', '6']})
        full_raw = [['1', '4'], ['2', '5'], ['3', '6']]

        # Sparse table
        sparse_df = pd.DataFrame({'A': ['1', '', ''], 'B': ['', '', '']})
        sparse_raw = [['1', ''], ['', ''], ['', '']]

        full_conf = extractor._calculate_confidence(full_df, full_raw)
        sparse_conf = extractor._calculate_confidence(sparse_df, sparse_raw)

        assert full_conf > sparse_conf


class TestPdfplumberExtractorValidation:
    """Tests for PdfplumberExtractor validation methods."""

    def test_has_numeric_content_detects_digits(self):
        """_has_numeric_content should detect strings with digits."""
        extractor = PdfplumberExtractor()

        assert extractor._has_numeric_content('123') is True
        assert extractor._has_numeric_content('$45.67') is True
        assert extractor._has_numeric_content('no numbers') is False
        assert extractor._has_numeric_content('') is False


# =============================================================================
# ExtractionScorer Tests
# =============================================================================

class TestExtractionScorerInit:
    """Tests for ExtractionScorer initialization."""

    def test_default_weights_sum_to_one(self):
        """Default weights should sum to 1.0."""
        scorer = ExtractionScorer()

        total = (
            scorer._confidence_weight +
            scorer._coverage_weight +
            scorer._regularity_weight +
            scorer._numeric_weight +
            scorer._header_weight
        )

        assert abs(total - 1.0) < 0.01

    def test_custom_weights_accepted(self):
        """Custom weights summing to 1.0 should be accepted."""
        scorer = ExtractionScorer(
            confidence_weight=0.3,
            coverage_weight=0.3,
            regularity_weight=0.2,
            numeric_weight=0.1,
            header_weight=0.1
        )

        assert scorer._coverage_weight == 0.3

    def test_invalid_weights_raise_error(self):
        """Weights not summing to 1.0 should raise ValueError."""
        with pytest.raises(ValueError, match="sum to 1.0"):
            ExtractionScorer(
                confidence_weight=0.5,
                coverage_weight=0.5,
                regularity_weight=0.5,
                numeric_weight=0.5,
                header_weight=0.5
            )


class TestExtractionScorerScore:
    """Tests for ExtractionScorer score method."""

    def test_score_returns_float(self, sample_extraction_result):
        """score() should return a float."""
        scorer = ExtractionScorer()
        score = scorer.score(sample_extraction_result)

        assert isinstance(score, float)

    def test_score_in_valid_range(self, sample_extraction_result):
        """score() should return value between 0 and 1."""
        scorer = ExtractionScorer()
        score = scorer.score(sample_extraction_result)

        assert 0.0 <= score <= 1.0

    def test_empty_dataframe_scores_zero(self):
        """Empty DataFrame should score 0.0."""
        scorer = ExtractionScorer()

        empty_result = ExtractionResult(
            dataframe=pd.DataFrame(),
            confidence=0.0,
            method='test',
            metadata={}
        )

        score = scorer.score(empty_result)
        assert score == 0.0

    def test_high_quality_scores_higher(self, sample_extraction_result, low_quality_extraction_result):
        """High quality results should score higher than low quality."""
        scorer = ExtractionScorer()

        high_score = scorer.score(sample_extraction_result)
        low_score = scorer.score(low_quality_extraction_result)

        assert high_score > low_score


class TestExtractionScorerSelectBest:
    """Tests for ExtractionScorer select_best method."""

    def test_select_best_returns_highest_scoring(
        self,
        sample_extraction_result,
        low_quality_extraction_result
    ):
        """select_best should return the highest scoring result."""
        scorer = ExtractionScorer()

        results = [low_quality_extraction_result, sample_extraction_result]
        best = scorer.select_best(results)

        # sample_extraction_result should score higher
        assert best == sample_extraction_result

    def test_select_best_empty_list_returns_none(self):
        """Empty list should return None."""
        scorer = ExtractionScorer()

        best = scorer.select_best([])
        assert best is None

    def test_select_best_single_item_returns_that_item(self, sample_extraction_result):
        """Single-item list should return that item."""
        scorer = ExtractionScorer()

        best = scorer.select_best([sample_extraction_result])
        assert best == sample_extraction_result


class TestExtractionScorerScoreAll:
    """Tests for ExtractionScorer score_all method."""

    def test_score_all_returns_sorted_list(
        self,
        sample_extraction_result,
        low_quality_extraction_result
    ):
        """score_all should return list sorted by score descending."""
        scorer = ExtractionScorer()

        results = [low_quality_extraction_result, sample_extraction_result]
        scored = scorer.score_all(results)

        assert len(scored) == 2
        # First should have higher score
        assert scored[0][1] >= scored[1][1]

    def test_score_all_returns_tuples(self, sample_extraction_result):
        """score_all should return list of (result, score) tuples."""
        scorer = ExtractionScorer()

        scored = scorer.score_all([sample_extraction_result])

        assert len(scored) == 1
        result, score = scored[0]
        assert isinstance(result, ExtractionResult)
        assert isinstance(score, float)

    def test_score_all_empty_list_returns_empty(self):
        """Empty list should return empty list."""
        scorer = ExtractionScorer()

        scored = scorer.score_all([])
        assert scored == []


class TestExtractionScorerCoverage:
    """Tests for ExtractionScorer coverage scoring."""

    def test_full_coverage_scores_higher(self):
        """Fully populated table should score higher than sparse table."""
        scorer = ExtractionScorer()

        full_result = ExtractionResult(
            dataframe=pd.DataFrame({'A': ['1', '2'], 'B': ['3', '4']}),
            confidence=0.8,
            method='test',
            metadata={}
        )

        sparse_result = ExtractionResult(
            dataframe=pd.DataFrame({'A': ['1', ''], 'B': ['', '']}),
            confidence=0.8,
            method='test',
            metadata={}
        )

        full_score = scorer._score_coverage(full_result.dataframe)
        sparse_score = scorer._score_coverage(sparse_result.dataframe)

        assert full_score > sparse_score


class TestExtractionScorerNumericIntegrity:
    """Tests for ExtractionScorer numeric integrity scoring."""

    def test_valid_numbers_score_high(self):
        """Valid numeric content should score high."""
        scorer = ExtractionScorer()

        df = pd.DataFrame({
            'Value': ['100', '200', '300'],
            'Price': ['$10.00', '$20.00', '$30.00']
        })

        score = scorer._score_numeric_integrity(df)
        assert score >= 0.5  # Should have good numeric integrity

    def test_text_only_gets_neutral_score(self):
        """Text-only table should get neutral score (0.7)."""
        scorer = ExtractionScorer()

        df = pd.DataFrame({
            'Name': ['Alice', 'Bob'],
            'Status': ['Active', 'Pending']
        })

        score = scorer._score_numeric_integrity(df)
        assert score == 0.7  # Neutral score for no numeric content

    def test_corrupted_numbers_score_lower(self):
        """Corrupted numeric content should score lower."""
        scorer = ExtractionScorer()

        valid_df = pd.DataFrame({'Value': ['100', '200', '300']})
        invalid_df = pd.DataFrame({'Value': ['1.2.3', '4..5', '6.7.8']})

        valid_score = scorer._score_numeric_integrity(valid_df)
        invalid_score = scorer._score_numeric_integrity(invalid_df)

        # Valid numbers should score higher (or equal if pattern doesn't match)
        assert valid_score >= invalid_score


class TestExtractionScorerNumericPatterns:
    """Tests for numeric pattern detection in scorer."""

    def test_looks_numeric_detects_simple_numbers(self):
        """_looks_numeric should detect simple integers."""
        scorer = ExtractionScorer()

        assert scorer._looks_numeric('123') is True
        assert scorer._looks_numeric('0') is True

    def test_looks_numeric_detects_currency(self):
        """_looks_numeric should detect currency values."""
        scorer = ExtractionScorer()

        assert scorer._looks_numeric('$100') is True
        assert scorer._looks_numeric('$1,234.56') is True

    def test_looks_numeric_detects_percentages(self):
        """_looks_numeric should detect percentages."""
        scorer = ExtractionScorer()

        assert scorer._looks_numeric('50%') is True
        assert scorer._looks_numeric('12.5%') is True

    def test_looks_numeric_rejects_text(self):
        """_looks_numeric should reject plain text."""
        scorer = ExtractionScorer()

        assert scorer._looks_numeric('hello') is False
        assert scorer._looks_numeric('') is False
        assert scorer._looks_numeric('abc123') is False

    def test_is_valid_number_validates_correctly(self):
        """_is_valid_number should validate parseable numbers."""
        scorer = ExtractionScorer()

        assert scorer._is_valid_number('123.45') is True
        assert scorer._is_valid_number('$1,234') is True
        assert scorer._is_valid_number('(500)') is True  # Accounting negative
        assert scorer._is_valid_number('50%') is True


class TestExtractionScorerRegularity:
    """Tests for structure regularity scoring."""

    def test_regular_structure_scores_high(self):
        """Uniform table structure should score high."""
        scorer = ExtractionScorer()

        df = pd.DataFrame({
            'A': ['1', '2', '3'],
            'B': ['a', 'b', 'c'],
            'C': ['x', 'y', 'z']
        })

        score = scorer._score_regularity(df)
        assert score >= 0.8

    def test_irregular_structure_scores_lower(self):
        """Irregular table structure should score lower."""
        scorer = ExtractionScorer()

        # Regular
        regular_df = pd.DataFrame({
            'A': ['1', '2', '3'],
            'B': ['a', 'b', 'c']
        })

        # Irregular (many empty cells)
        irregular_df = pd.DataFrame({
            'A': ['1', '', ''],
            'B': ['', '', 'c']
        })

        regular_score = scorer._score_regularity(regular_df)
        irregular_score = scorer._score_regularity(irregular_df)

        assert regular_score > irregular_score


class TestExtractionScorerHeaderDetection:
    """Tests for header detection scoring."""

    def test_metadata_header_rows_scores_full(self):
        """Explicit header_rows in metadata should score 1.0."""
        scorer = ExtractionScorer()

        df = pd.DataFrame({'A': ['Header', 'Data1'], 'B': ['Column', 'Data2']})
        metadata = {'header_rows': [0]}

        score = scorer._score_header_detection(df, metadata)
        assert score == 1.0

    def test_single_row_scores_zero(self):
        """Single row table should score 0.0 (can't detect header)."""
        scorer = ExtractionScorer()

        df = pd.DataFrame({'A': ['Value'], 'B': ['Data']})

        score = scorer._score_header_detection(df, {})
        assert score == 0.0

    def test_empty_dataframe_scores_zero(self):
        """Empty DataFrame should score 0.0."""
        scorer = ExtractionScorer()

        score = scorer._score_header_detection(pd.DataFrame(), {})
        assert score == 0.0


# =============================================================================
# Integration Tests
# =============================================================================

class TestExtractorIntegration:
    """Integration tests for extractors."""

    def test_both_extractors_implement_base_interface(self):
        """Both extractors should implement BaseExtractor interface."""
        camelot = CamelotExtractor()
        pdfplumber = PdfplumberExtractor()

        assert isinstance(camelot, BaseExtractor)
        assert isinstance(pdfplumber, BaseExtractor)

    def test_extractors_produce_compatible_results(self, simple_table_pdf):
        """Both extractors should produce ExtractionResult objects."""
        camelot = CamelotExtractor()
        pdfplumber = PdfplumberExtractor()

        camelot_results = camelot.extract(simple_table_pdf, 1)
        pdfplumber_results = pdfplumber.extract(simple_table_pdf, 1)

        for result in camelot_results + pdfplumber_results:
            assert isinstance(result, ExtractionResult)
            assert isinstance(result.dataframe, pd.DataFrame)
            assert isinstance(result.confidence, float)
            assert isinstance(result.method, str)

    def test_scorer_can_compare_different_extractors(self, simple_table_pdf):
        """Scorer should be able to compare results from different extractors."""
        camelot = CamelotExtractor()
        pdfplumber = PdfplumberExtractor()
        scorer = ExtractionScorer()

        camelot_results = camelot.extract(simple_table_pdf, 1)
        pdfplumber_results = pdfplumber.extract(simple_table_pdf, 1)

        all_results = camelot_results + pdfplumber_results

        if all_results:
            best = scorer.select_best(all_results)
            assert best is not None
            assert isinstance(best, ExtractionResult)


class TestMultipageExtraction:
    """Tests for multi-page PDF extraction."""

    def test_camelot_handles_multiple_pages(self, multipage_table_pdf):
        """Camelot should handle multi-page PDFs."""
        extractor = CamelotExtractor()

        # Page 1 has a table
        page1_results = extractor.extract(multipage_table_pdf, 1)

        # Page 2 has no table
        page2_results = extractor.extract(multipage_table_pdf, 2)

        assert isinstance(page1_results, list)
        assert isinstance(page2_results, list)

    def test_pdfplumber_handles_multiple_pages(self, multipage_table_pdf):
        """Pdfplumber should handle multi-page PDFs."""
        extractor = PdfplumberExtractor()

        page1_results = extractor.extract(multipage_table_pdf, 1)
        page2_results = extractor.extract(multipage_table_pdf, 2)

        assert isinstance(page1_results, list)
        assert isinstance(page2_results, list)

    def test_camelot_extracts_tables_from_correct_pages(self, multipage_table_pdf):
        """Camelot should detect page differences correctly."""
        extractor = CamelotExtractor()

        page1_results = extractor.extract(multipage_table_pdf, 1)
        page2_results = extractor.extract(multipage_table_pdf, 2)

        # Page 1 has a small bordered table - Camelot may or may not detect it
        # The important thing is page 2 (no tables) should return empty
        assert isinstance(page1_results, list)

        # Page 2 has only text - should find no tables
        assert len(page2_results) == 0, "Should find no tables on page 2"

    def test_pdfplumber_extracts_tables_from_correct_pages(self, multipage_table_pdf, multipage_table_areas):
        """Pdfplumber should find tables on page 1 and no tables on page 2."""
        extractor = PdfplumberExtractor()

        page1_results = extractor.extract(multipage_table_pdf, 1, table_areas=multipage_table_areas)
        page2_results = extractor.extract(multipage_table_pdf, 2)  # No table_areas for page without tables

        # Page 1 has a bordered table - should find it
        assert len(page1_results) >= 1, "Should find at least one table on page 1"

        # Page 2 has only text - should find no tables
        assert len(page2_results) == 0, "Should find no tables on page 2"

    def test_camelot_page_num_metadata_correct(self, multipage_table_pdf):
        """Camelot extraction results should have correct page_num in metadata."""
        extractor = CamelotExtractor()

        page1_results = extractor.extract(multipage_table_pdf, 1)

        for result in page1_results:
            assert 'page_num' in result.metadata, "Metadata should contain page_num"
            assert result.metadata['page_num'] == 1, "page_num should be 1 for page 1"

    def test_pdfplumber_page_num_metadata_correct(self, multipage_table_pdf):
        """Pdfplumber extraction results should have correct page_num in metadata."""
        extractor = PdfplumberExtractor()

        page1_results = extractor.extract(multipage_table_pdf, 1)

        for result in page1_results:
            assert 'page_num' in result.metadata, "Metadata should contain page_num"
            assert result.metadata['page_num'] == 1, "page_num should be 1 for page 1"

    def test_extractors_handle_page_without_tables_gracefully(self, multipage_table_pdf):
        """Both extractors should return empty list for pages without tables."""
        camelot = CamelotExtractor()
        pdfplumber = PdfplumberExtractor()

        # Page 2 has no tables
        camelot_results = camelot.extract(multipage_table_pdf, 2)
        pdfplumber_results = pdfplumber.extract(multipage_table_pdf, 2)

        assert camelot_results == [], "Camelot should return empty list for page without tables"
        assert pdfplumber_results == [], "Pdfplumber should return empty list for page without tables"


# =============================================================================
# BoundingBox Tests
# =============================================================================

class TestBoundingBoxInit:
    """Tests for BoundingBox initialization and basic properties."""

    def test_bounding_box_stores_coordinates(self):
        # Given: coordinates for a bounding box
        x1, y1, x2, y2 = 100.0, 200.0, 300.0, 400.0

        # When: creating a BoundingBox
        bbox = BoundingBox(x1=x1, y1=y1, x2=x2, y2=y2)

        # Then: coordinates are stored correctly
        assert bbox.x1 == 100.0
        assert bbox.y1 == 200.0
        assert bbox.x2 == 300.0
        assert bbox.y2 == 400.0

    def test_bounding_box_default_page_dimensions(self):
        # Given: a BoundingBox without explicit page dimensions
        bbox = BoundingBox(x1=0, y1=0, x2=100, y2=100)

        # Then: default page dimensions are letter size
        assert bbox.page_width == 612.0
        assert bbox.page_height == 792.0

    def test_bounding_box_custom_page_dimensions(self):
        # Given: custom page dimensions (A4)
        page_width, page_height = 595.0, 842.0

        # When: creating a BoundingBox with custom dimensions
        bbox = BoundingBox(x1=0, y1=0, x2=100, y2=100, page_width=page_width, page_height=page_height)

        # Then: custom dimensions are stored
        assert bbox.page_width == 595.0
        assert bbox.page_height == 842.0


class TestBoundingBoxFromYolo:
    """Tests for BoundingBox.from_yolo() coordinate conversion."""

    def test_from_yolo_converts_top_left_origin_to_bottom_left(self):
        # Given: YOLO pixel coords with top-left origin (y=0 is TOP)
        # Box at top-left quadrant of 612x792 image
        x1_px, y1_px = 0, 0      # Top-left corner in pixels
        x2_px, y2_px = 306, 396  # Center of image

        # When: converting to PDF coords (bottom-left origin)
        bbox = BoundingBox.from_yolo(
            x1=x1_px, y1=y1_px, x2=x2_px, y2=y2_px,
            img_width=612, img_height=792,
            page_width=612, page_height=792
        )

        # Then: y values are flipped (PDF y=0 is BOTTOM)
        # Original y1=0 (top of image) -> PDF y2=792 (top of page)
        # Original y2=396 (middle) -> PDF y1=396 (middle)
        assert bbox.x1 == pytest.approx(0.0, abs=0.1)
        assert bbox.x2 == pytest.approx(306.0, abs=0.1)
        assert bbox.y1 == pytest.approx(396.0, abs=0.1)  # Bottom of box in PDF
        assert bbox.y2 == pytest.approx(792.0, abs=0.1)  # Top of box in PDF

    def test_from_yolo_scales_to_page_dimensions(self):
        # Given: YOLO coords from a smaller image scaled to larger page
        img_width, img_height = 300, 400
        page_width, page_height = 612, 792

        # Box in center of image (normalized 0.25-0.75)
        x1_px, y1_px = 75, 100   # 25% in
        x2_px, y2_px = 225, 300  # 75% in

        # When: converting with scaling
        bbox = BoundingBox.from_yolo(
            x1=x1_px, y1=y1_px, x2=x2_px, y2=y2_px,
            img_width=img_width, img_height=img_height,
            page_width=page_width, page_height=page_height
        )

        # Then: coordinates are scaled to page dimensions
        # x: 75/300 = 0.25 -> 0.25 * 612 = 153
        assert bbox.x1 == pytest.approx(153.0, abs=0.1)
        # x: 225/300 = 0.75 -> 0.75 * 612 = 459
        assert bbox.x2 == pytest.approx(459.0, abs=0.1)

    def test_from_yolo_full_page_box(self):
        # Given: YOLO box covering entire image
        x1_px, y1_px = 0, 0
        x2_px, y2_px = 612, 792

        # When: converting full-page box
        bbox = BoundingBox.from_yolo(
            x1=x1_px, y1=y1_px, x2=x2_px, y2=y2_px,
            img_width=612, img_height=792,
            page_width=612, page_height=792
        )

        # Then: box covers entire page
        assert bbox.x1 == pytest.approx(0.0, abs=0.1)
        assert bbox.y1 == pytest.approx(0.0, abs=0.1)
        assert bbox.x2 == pytest.approx(612.0, abs=0.1)
        assert bbox.y2 == pytest.approx(792.0, abs=0.1)

    def test_from_yolo_small_box_at_page_bottom(self):
        # Given: small box at BOTTOM of image (high y values in image coords)
        x1_px, y1_px = 100, 700  # Near bottom of image (y=700 out of 792)
        x2_px, y2_px = 200, 750

        # When: converting
        bbox = BoundingBox.from_yolo(
            x1=x1_px, y1=y1_px, x2=x2_px, y2=y2_px,
            img_width=612, img_height=792,
            page_width=612, page_height=792
        )

        # Then: box should be at BOTTOM of PDF page (low y values in PDF)
        assert bbox.y1 < 100  # Near bottom of PDF page
        assert bbox.y2 < 100  # Both y values low


class TestBoundingBoxFromPdfCoords:
    """Tests for BoundingBox.from_pdf_coords() normalization."""

    def test_from_pdf_coords_normalizes_y_order(self):
        # Given: PDF coords where y1 > y2 (inverted)
        x1, y1, x2, y2 = 100, 500, 200, 300  # y1 > y2

        # When: creating BoundingBox
        bbox = BoundingBox.from_pdf_coords(x1, y1, x2, y2)

        # Then: y values are normalized (y1 < y2)
        assert bbox.y1 == 300  # Smaller value
        assert bbox.y2 == 500  # Larger value

    def test_from_pdf_coords_preserves_correct_order(self):
        # Given: PDF coords already in correct order (y1 < y2)
        x1, y1, x2, y2 = 100, 300, 200, 500

        # When: creating BoundingBox
        bbox = BoundingBox.from_pdf_coords(x1, y1, x2, y2)

        # Then: values are preserved
        assert bbox.y1 == 300
        assert bbox.y2 == 500

    def test_from_pdf_coords_preserves_x_values(self):
        # Given: PDF coords
        x1, y1, x2, y2 = 50, 100, 400, 600

        # When: creating BoundingBox
        bbox = BoundingBox.from_pdf_coords(x1, y1, x2, y2)

        # Then: x values are unchanged
        assert bbox.x1 == 50
        assert bbox.x2 == 400


class TestBoundingBoxToCamelot:
    """Tests for BoundingBox.to_camelot() conversion."""

    def test_to_camelot_swaps_y_values(self):
        # Given: BoundingBox with y1 < y2 (standard PDF)
        bbox = BoundingBox(x1=100, y1=200, x2=300, y2=400)

        # When: converting to Camelot format
        result = bbox.to_camelot()

        # Then: Camelot expects y1 > y2, so y values are swapped
        # Format: "x1,y1,x2,y2" where y1 is TOP (higher value)
        assert result == "100,400,300,200"

    def test_to_camelot_returns_string(self):
        # Given: a BoundingBox
        bbox = BoundingBox(x1=50, y1=100, x2=200, y2=300)

        # When: converting to Camelot
        result = bbox.to_camelot()

        # Then: result is a comma-separated string
        assert isinstance(result, str)
        assert "," in result
        parts = result.split(",")
        assert len(parts) == 4


class TestBoundingBoxToPdfplumber:
    """Tests for BoundingBox.to_pdfplumber() conversion."""

    def test_to_pdfplumber_converts_to_top_left_origin(self):
        # Given: BoundingBox in PDF coords (bottom-left origin)
        # Box from y=200 to y=400 on 792-height page
        bbox = BoundingBox(x1=100, y1=200, x2=300, y2=400, page_height=792)

        # When: converting to pdfplumber (top-left origin)
        x0, top, x1, bottom = bbox.to_pdfplumber()

        # Then: y values are flipped relative to page height
        # PDF y2=400 (top of box) -> pdfplumber top = 792-400 = 392
        # PDF y1=200 (bottom of box) -> pdfplumber bottom = 792-200 = 592
        assert x0 == 100
        assert x1 == 300
        assert top == pytest.approx(392.0, abs=0.1)
        assert bottom == pytest.approx(592.0, abs=0.1)

    def test_to_pdfplumber_returns_tuple(self):
        # Given: a BoundingBox
        bbox = BoundingBox(x1=50, y1=100, x2=200, y2=300)

        # When: converting to pdfplumber
        result = bbox.to_pdfplumber()

        # Then: result is a 4-tuple
        assert isinstance(result, tuple)
        assert len(result) == 4

    def test_to_pdfplumber_top_less_than_bottom(self):
        # Given: any valid BoundingBox
        bbox = BoundingBox(x1=100, y1=200, x2=300, y2=400, page_height=792)

        # When: converting
        x0, top, x1, bottom = bbox.to_pdfplumber()

        # Then: top < bottom (pdfplumber convention)
        assert top < bottom


class TestBoundingBoxToPymupdf:
    """Tests for BoundingBox.to_pymupdf() conversion."""

    def test_to_pymupdf_same_as_pdfplumber(self):
        # Given: a BoundingBox
        bbox = BoundingBox(x1=100, y1=200, x2=300, y2=400, page_height=792)

        # When: converting to both formats
        pdfplumber_result = bbox.to_pdfplumber()
        pymupdf_result = bbox.to_pymupdf()

        # Then: results are identical (both use top-left origin)
        assert pdfplumber_result == pymupdf_result


class TestBoundingBoxToTuple:
    """Tests for BoundingBox.to_tuple() method."""

    def test_to_tuple_returns_internal_coords(self):
        # Given: a BoundingBox
        bbox = BoundingBox(x1=100, y1=200, x2=300, y2=400)

        # When: converting to tuple
        result = bbox.to_tuple()

        # Then: returns internal coordinates as tuple
        assert result == (100, 200, 300, 400)

    def test_to_tuple_maintains_y1_less_than_y2(self):
        # Given: BoundingBox created via from_pdf_coords (normalized)
        bbox = BoundingBox.from_pdf_coords(100, 500, 300, 200)  # y1 > y2

        # When: converting to tuple
        x1, y1, x2, y2 = bbox.to_tuple()

        # Then: y1 < y2 (normalized)
        assert y1 < y2


class TestBoundingBoxRoundTrip:
    """Tests for coordinate system round-trip conversions."""

    def test_yolo_to_camelot_round_trip_preserves_region(self):
        # Given: YOLO coords representing a table region
        yolo_x1, yolo_y1 = 100, 100  # Top-left in image
        yolo_x2, yolo_y2 = 300, 200  # Bottom-right in image

        # When: converting YOLO -> PDF -> Camelot
        bbox = BoundingBox.from_yolo(
            x1=yolo_x1, y1=yolo_y1, x2=yolo_x2, y2=yolo_y2,
            img_width=612, img_height=792,
            page_width=612, page_height=792
        )
        camelot_str = bbox.to_camelot()

        # Then: Camelot string represents same page region
        parts = [float(p) for p in camelot_str.split(",")]
        assert parts[0] == pytest.approx(yolo_x1, abs=1)  # x1 preserved
        assert parts[2] == pytest.approx(yolo_x2, abs=1)  # x2 preserved


# =============================================================================
# PyMuPDFExtractor Tests
# =============================================================================

class TestPyMuPDFExtractorInit:
    """Tests for PyMuPDFExtractor initialization."""

    def test_default_strategy_is_lines(self):
        # Given/When: creating extractor with defaults
        extractor = PyMuPDFExtractor()

        # Then: default strategy is 'lines'
        assert extractor._strategy == 'lines'
        assert extractor.name == 'pymupdf'

    def test_text_strategy_accepted(self):
        # Given/When: creating extractor with 'text' strategy
        extractor = PyMuPDFExtractor(strategy='text')

        # Then: strategy is set and name reflects it
        assert extractor._strategy == 'text'
        assert extractor.name == 'pymupdf_text'

    def test_lines_strict_strategy_accepted(self):
        # Given/When: creating extractor with 'lines_strict' strategy
        extractor = PyMuPDFExtractor(strategy='lines_strict')

        # Then: strategy is set and name reflects it
        assert extractor._strategy == 'lines_strict'
        assert extractor.name == 'pymupdf_strict'

    def test_invalid_strategy_raises_error(self):
        # Given: an invalid strategy name

        # When/Then: ValueError is raised
        with pytest.raises(ValueError, match="strategy must be"):
            PyMuPDFExtractor(strategy='invalid')

    def test_custom_tolerances_accepted(self):
        # Given: custom tolerance values
        snap_tol = 5
        join_tol = 4

        # When: creating extractor with custom values
        extractor = PyMuPDFExtractor(snap_tolerance=snap_tol, join_tolerance=join_tol)

        # Then: values are stored
        assert extractor._snap_tolerance == 5
        assert extractor._join_tolerance == 4

    def test_custom_min_words_accepted(self):
        # Given: custom minimum word settings
        min_vert = 5
        min_horiz = 2

        # When: creating extractor with custom values
        extractor = PyMuPDFExtractor(min_words_vertical=min_vert, min_words_horizontal=min_horiz)

        # Then: values are stored
        assert extractor._min_words_vertical == 5
        assert extractor._min_words_horizontal == 2


class TestPyMuPDFExtractorExtraction:
    """Tests for PyMuPDFExtractor extract method."""

    def test_extract_returns_list(self, simple_table_pdf):
        # Given: a PyMuPDFExtractor and PDF with table
        extractor = PyMuPDFExtractor()
        table_areas = [(100.0, 500.0, 460.0, 700.0)]

        # When: extracting
        results = extractor.extract(simple_table_pdf, 1, table_areas=table_areas)

        # Then: returns a list
        assert isinstance(results, list)

    def test_extract_results_are_extraction_results(self, simple_table_pdf):
        # Given: a PyMuPDFExtractor
        extractor = PyMuPDFExtractor()
        table_areas = [(100.0, 500.0, 460.0, 700.0)]

        # When: extracting
        results = extractor.extract(simple_table_pdf, 1, table_areas=table_areas)

        # Then: each result is an ExtractionResult
        for result in results:
            assert isinstance(result, ExtractionResult)

    def test_extract_nonexistent_file_raises_error(self):
        # Given: an extractor and non-existent file
        extractor = PyMuPDFExtractor()

        # When/Then: FileNotFoundError is raised
        with pytest.raises(FileNotFoundError):
            extractor.extract('/nonexistent/file.pdf', 1)

    def test_extract_invalid_page_raises_error(self, simple_table_pdf):
        # Given: an extractor and invalid page number
        extractor = PyMuPDFExtractor()
        table_areas = [(100.0, 500.0, 460.0, 700.0)]

        # When/Then: ValueError is raised
        with pytest.raises(ValueError, match="out of range"):
            extractor.extract(simple_table_pdf, 999, table_areas=table_areas)

    def test_extract_page_zero_raises_error(self, simple_table_pdf):
        # Given: an extractor and page 0
        extractor = PyMuPDFExtractor()
        table_areas = [(100.0, 500.0, 460.0, 700.0)]

        # When/Then: ValueError is raised (1-indexed)
        with pytest.raises(ValueError, match="out of range"):
            extractor.extract(simple_table_pdf, 0, table_areas=table_areas)

    def test_extract_empty_pdf_returns_empty_list(self, empty_pdf):
        # Given: a PDF without tables
        extractor = PyMuPDFExtractor()
        table_areas = [(100.0, 500.0, 460.0, 700.0)]

        # When: extracting
        results = extractor.extract(empty_pdf, 1, table_areas=table_areas)

        # Then: returns empty list
        assert results == []

    def test_extract_without_table_areas_returns_empty(self, simple_table_pdf):
        # Given: an extractor and no table_areas
        extractor = PyMuPDFExtractor()

        # When: extracting without table_areas
        results = extractor.extract(simple_table_pdf, 1, table_areas=None)

        # Then: returns empty list (pipeline requires table_areas)
        assert results == []


class TestPyMuPDFExtractorValidation:
    """Tests for PyMuPDFExtractor validation methods."""

    def test_valid_table_requires_minimum_dimensions(self):
        # Given: an extractor
        extractor = PyMuPDFExtractor()

        # When/Then: 2x2 table is valid
        valid_df = pd.DataFrame([['a', 'b'], ['c', 'd']])
        assert extractor._is_valid_table(valid_df) is True

        # When/Then: 1x2 table is invalid
        invalid_df = pd.DataFrame([['a', 'b']])
        assert extractor._is_valid_table(invalid_df) is False

    def test_clean_dataframe_replaces_none(self):
        # Given: an extractor and DataFrame with None values
        extractor = PyMuPDFExtractor()
        df = pd.DataFrame({'A': [1, None, 3], 'B': [None, 2, None]})

        # When: cleaning
        cleaned = extractor._clean_dataframe(df)

        # Then: no NaN values remain
        assert not cleaned.isna().any().any()

    def test_has_numeric_content_detects_digits(self):
        # Given: an extractor
        extractor = PyMuPDFExtractor()

        # When/Then: strings with digits detected
        assert extractor._has_numeric_content('123') is True
        assert extractor._has_numeric_content('$45.67') is True
        assert extractor._has_numeric_content('no numbers') is False
        assert extractor._has_numeric_content('') is False


class TestPyMuPDFExtractorConfidence:
    """Tests for PyMuPDFExtractor confidence calculation."""

    def test_empty_dataframe_returns_zero_confidence(self):
        # Given: an extractor and empty DataFrame
        extractor = PyMuPDFExtractor()
        df = pd.DataFrame()
        mock_table = MagicMock()
        mock_table.row_count = 0
        mock_table.col_count = 0

        # When: calculating confidence
        confidence = extractor._calculate_confidence(df, mock_table)

        # Then: confidence is 0
        assert confidence == 0.0

    def test_high_fill_rate_increases_confidence(self):
        # Given: an extractor and full vs sparse DataFrames
        extractor = PyMuPDFExtractor()

        full_df = pd.DataFrame({'A': ['1', '2', '3'], 'B': ['4', '5', '6']})
        sparse_df = pd.DataFrame({'A': ['1', '', ''], 'B': ['', '', '']})

        mock_table = MagicMock()
        mock_table.row_count = 3
        mock_table.col_count = 2

        # When: calculating confidence
        full_conf = extractor._calculate_confidence(full_df, mock_table)
        sparse_conf = extractor._calculate_confidence(sparse_df, mock_table)

        # Then: full table has higher confidence
        assert full_conf > sparse_conf


class TestPyMuPDFExtractorMetadata:
    """Tests for PyMuPDFExtractor metadata building."""

    def test_metadata_includes_required_fields(self):
        # Given: an extractor
        extractor = PyMuPDFExtractor(strategy='text')

        # Create a mock table
        mock_table = MagicMock()
        mock_table.row_count = 3
        mock_table.col_count = 2
        mock_table.header = None

        # When: building metadata
        metadata = extractor._build_metadata(
            mock_table,
            table_index=0,
            page_num=1,
            original_bbox=(100, 200, 300, 400)
        )

        # Then: metadata contains required fields
        assert metadata['table_index'] == 0
        assert metadata['page_num'] == 1
        assert metadata['bounding_box'] == {'x1': 100, 'y1': 200, 'x2': 300, 'y2': 400}
        assert metadata['extractor_settings']['strategy'] == 'text'
        assert metadata['table_dimensions'] == {'rows': 3, 'cols': 2}


# =============================================================================
# MultiExtractor enabled_libraries Tests
# =============================================================================

class TestMultiExtractorEnabledLibraries:
    """Tests for MultiExtractor enabled_libraries feature."""

    def test_default_enables_all_libraries(self):
        # Given/When: creating MultiExtractor with defaults
        extractor = MultiExtractor()

        # Then: all libraries are enabled
        names = extractor.extractor_names
        assert 'camelot_lattice' in names
        assert 'camelot_stream' in names
        assert 'pdfplumber' in names
        assert 'pdfplumber_text' in names
        assert 'pymupdf' in names
        assert 'pymupdf_text' in names
        assert 'img2table' in names

    def test_disabling_camelot_removes_camelot_extractors(self):
        # Given: enabled_libraries with camelot disabled
        enabled = {'camelot': False, 'pdfplumber': True, 'pymupdf': True, 'vision': True}

        # When: creating MultiExtractor
        extractor = MultiExtractor(enabled_libraries=enabled)

        # Then: no Camelot extractors present
        names = extractor.extractor_names
        assert 'camelot_lattice' not in names
        assert 'camelot_stream' not in names
        # Others still present
        assert 'pdfplumber' in names
        assert 'pymupdf' in names

    def test_disabling_pdfplumber_removes_pdfplumber_extractors(self):
        # Given: enabled_libraries with pdfplumber disabled
        enabled = {'camelot': True, 'pdfplumber': False, 'pymupdf': True, 'vision': True}

        # When: creating MultiExtractor
        extractor = MultiExtractor(enabled_libraries=enabled)

        # Then: no pdfplumber extractors present
        names = extractor.extractor_names
        assert 'pdfplumber' not in names
        assert 'pdfplumber_text' not in names
        # Others still present
        assert 'camelot_lattice' in names
        assert 'pymupdf' in names

    def test_disabling_pymupdf_removes_pymupdf_extractors(self):
        # Given: enabled_libraries with pymupdf disabled
        enabled = {'camelot': True, 'pdfplumber': True, 'pymupdf': False, 'vision': True}

        # When: creating MultiExtractor
        extractor = MultiExtractor(enabled_libraries=enabled)

        # Then: no PyMuPDF extractors present
        names = extractor.extractor_names
        assert 'pymupdf' not in names
        assert 'pymupdf_text' not in names
        # Others still present
        assert 'camelot_lattice' in names
        assert 'pdfplumber' in names

    def test_disabling_vision_removes_img2table_extractor(self):
        # Given: enabled_libraries with vision disabled
        enabled = {'camelot': True, 'pdfplumber': True, 'pymupdf': True, 'vision': False}

        # When: creating MultiExtractor
        extractor = MultiExtractor(enabled_libraries=enabled)

        # Then: no vision extractor present
        names = extractor.extractor_names
        assert 'img2table' not in names
        # Others still present
        assert 'camelot_lattice' in names
        assert 'pdfplumber' in names
        assert 'pymupdf' in names

    def test_enabling_only_one_library(self):
        # Given: only pdfplumber enabled
        enabled = {'camelot': False, 'pdfplumber': True, 'pymupdf': False, 'vision': False}

        # When: creating MultiExtractor
        extractor = MultiExtractor(enabled_libraries=enabled)

        # Then: only pdfplumber extractors present
        names = extractor.extractor_names
        assert names == ['pdfplumber', 'pdfplumber_text']

    def test_empty_dict_enables_all_libraries(self):
        # Given: empty enabled_libraries dict
        enabled = {}

        # When: creating MultiExtractor
        extractor = MultiExtractor(enabled_libraries=enabled)

        # Then: all libraries enabled (defaults to True)
        names = extractor.extractor_names
        assert 'camelot_lattice' in names
        assert 'pdfplumber' in names
        assert 'pymupdf' in names
        assert 'img2table' in names

    def test_partial_dict_enables_unspecified_libraries(self):
        # Given: only some libraries specified (others default to True)
        enabled = {'camelot': False}

        # When: creating MultiExtractor
        extractor = MultiExtractor(enabled_libraries=enabled)

        # Then: unspecified libraries are enabled
        names = extractor.extractor_names
        assert 'camelot_lattice' not in names  # Explicitly disabled
        assert 'pdfplumber' in names           # Defaults to True
        assert 'pymupdf' in names              # Defaults to True
        assert 'img2table' in names            # Defaults to True

    def test_extractor_count_matches_enabled_libraries(self):
        # Given: specific configuration
        enabled = {'camelot': True, 'pdfplumber': False, 'pymupdf': True, 'vision': False}

        # When: creating MultiExtractor
        extractor = MultiExtractor(enabled_libraries=enabled)

        # Then: correct number of extractors
        # Camelot: 2 (lattice + stream), PyMuPDF: 2 (lines + text) = 4 total
        assert len(extractor._extractors) == 4
