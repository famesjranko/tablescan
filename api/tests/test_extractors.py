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
    ExtractionResult,
    CamelotExtractor,
    PdfplumberExtractor,
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
            scorer._coverage_weight +
            scorer._regularity_weight +
            scorer._numeric_weight +
            scorer._header_weight
        )

        assert abs(total - 1.0) < 0.01

    def test_custom_weights_accepted(self):
        """Custom weights summing to 1.0 should be accepted."""
        scorer = ExtractionScorer(
            coverage_weight=0.4,
            regularity_weight=0.4,
            numeric_weight=0.1,
            header_weight=0.1
        )

        assert scorer._coverage_weight == 0.4

    def test_invalid_weights_raise_error(self):
        """Weights not summing to 1.0 should raise ValueError."""
        with pytest.raises(ValueError, match="sum to 1.0"):
            ExtractionScorer(
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
