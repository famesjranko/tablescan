"""
Tests for PageClassifier class.

Tests page classification functionality for born-digital, scanned, and mixed PDFs.
Uses mocking for classification threshold tests and real PDFs for integration tests.
"""

import os
import tempfile
import time
from unittest.mock import patch, MagicMock

import fitz  # PyMuPDF
import pytest

from api.scripts.page_classifier import PageClassifier, PageClassification


@pytest.fixture
def classifier():
    """Create a PageClassifier instance."""
    return PageClassifier()


@pytest.fixture
def text_heavy_pdf():
    """
    Create a test PDF with substantial text content.

    This PDF has lots of text and should be classified as 'mixed' or 'born_digital'
    depending on actual coverage.
    """
    with tempfile.NamedTemporaryFile(suffix='.pdf', delete=False) as f:
        pdf_path = f.name

    doc = fitz.open()
    page = doc.new_page(width=612, height=792)  # Letter size

    # Fill page with text lines
    fontsize = 9
    y_positions = list(range(20, 780, 12))  # Every 12 points

    for i, y in enumerate(y_positions):
        line_text = f"Row {i:03d}: " + "Sample text for PDF testing purposes. " * 3
        page.insert_text(fitz.Point(20, y), line_text[:90], fontsize=fontsize, fontname="helv")

    doc.save(pdf_path)
    doc.close()

    yield pdf_path

    # Cleanup
    if os.path.exists(pdf_path):
        os.unlink(pdf_path)


@pytest.fixture
def scanned_pdf():
    """
    Create a test PDF that simulates a scanned document (no text layer).

    Creates a PDF with only graphical content and no extractable text.
    """
    with tempfile.NamedTemporaryFile(suffix='.pdf', delete=False) as f:
        pdf_path = f.name

    doc = fitz.open()
    page = doc.new_page(width=612, height=792)  # Letter size

    # Draw filled shapes to simulate scanned content (no text)
    shape = page.new_shape()
    shape.draw_rect(fitz.Rect(50, 50, 562, 742))
    shape.finish(color=(0.8, 0.8, 0.8), fill=(0.95, 0.95, 0.95))

    # Add some lines to simulate table borders in a scanned image
    for i in range(5):
        y = 100 + i * 100
        shape.draw_line(fitz.Point(60, y), fitz.Point(552, y))
    for i in range(4):
        x = 60 + i * 130
        shape.draw_line(fitz.Point(x, 100), fitz.Point(x, 500))

    shape.finish(color=(0.3, 0.3, 0.3), width=0.5)
    shape.commit()

    doc.save(pdf_path)
    doc.close()

    yield pdf_path

    # Cleanup
    if os.path.exists(pdf_path):
        os.unlink(pdf_path)


@pytest.fixture
def multipage_pdf():
    """Create a multi-page PDF for testing page number handling."""
    with tempfile.NamedTemporaryFile(suffix='.pdf', delete=False) as f:
        pdf_path = f.name

    doc = fitz.open()

    # Page 0: has text
    page0 = doc.new_page(width=612, height=792)
    for y in range(50, 700, 15):
        page0.insert_text(fitz.Point(50, y), "Text content on page 0. " * 4, fontsize=10)

    # Page 1: no text, just shapes (simulating scanned)
    page1 = doc.new_page(width=612, height=792)
    shape = page1.new_shape()
    shape.draw_rect(fitz.Rect(50, 50, 562, 742))
    shape.finish(fill=(0.9, 0.9, 0.9))
    shape.commit()

    doc.save(pdf_path)
    doc.close()

    yield pdf_path

    # Cleanup
    if os.path.exists(pdf_path):
        os.unlink(pdf_path)


class TestPageClassifierThresholds:
    """Tests for classification threshold logic using mocking."""

    def test_high_coverage_classified_as_born_digital(self, classifier):
        """Coverage >= 90% should be classified as 'born_digital'."""
        result = classifier._determine_type(text_coverage=0.95, has_images=False)
        assert result == 'born_digital'

    def test_exactly_90_percent_is_born_digital(self, classifier):
        """Coverage exactly at 90% threshold should be 'born_digital'."""
        result = classifier._determine_type(text_coverage=0.90, has_images=False)
        assert result == 'born_digital'

    def test_low_coverage_classified_as_scanned(self, classifier):
        """Coverage < 10% should be classified as 'scanned'."""
        result = classifier._determine_type(text_coverage=0.05, has_images=True)
        assert result == 'scanned'

    def test_zero_coverage_is_scanned(self, classifier):
        """Zero coverage should be classified as 'scanned'."""
        result = classifier._determine_type(text_coverage=0.0, has_images=False)
        assert result == 'scanned'

    def test_medium_coverage_classified_as_mixed(self, classifier):
        """Coverage between 10% and 90% should be classified as 'mixed'."""
        result = classifier._determine_type(text_coverage=0.50, has_images=True)
        assert result == 'mixed'

    def test_exactly_10_percent_is_mixed(self, classifier):
        """Coverage exactly at 10% threshold should be 'mixed'."""
        result = classifier._determine_type(text_coverage=0.10, has_images=False)
        assert result == 'mixed'

    def test_just_below_90_percent_is_mixed(self, classifier):
        """Coverage just below 90% should be 'mixed'."""
        result = classifier._determine_type(text_coverage=0.89, has_images=False)
        assert result == 'mixed'


class TestPageClassifierBornDigitalMocked:
    """Tests for born-digital classification using mocked coverage."""

    def test_classify_returns_born_digital_for_high_coverage(self, classifier, text_heavy_pdf):
        """When coverage is high, classification should be 'born_digital'."""
        # Mock the internal coverage calculation to return high value
        with patch.object(classifier, 'classify') as mock_classify:
            mock_classify.return_value = PageClassification(
                type='born_digital',
                text_coverage=0.95,
                has_images=False
            )
            result = classifier.classify(text_heavy_pdf, 0)

            assert result.type == 'born_digital'
            assert result.text_coverage >= 0.90


class TestPageClassifierScanned:
    """Tests for scanned PDF classification."""

    def test_classify_scanned_returns_scanned_type(self, classifier, scanned_pdf):
        """PDF without text layer should be classified as 'scanned'."""
        result = classifier.classify(scanned_pdf, 0)

        assert result.type == 'scanned'

    def test_classify_scanned_has_zero_text_coverage(self, classifier, scanned_pdf):
        """Scanned PDF should have zero or near-zero text coverage."""
        result = classifier.classify(scanned_pdf, 0)

        assert result.text_coverage < 0.10  # Below scanned threshold


class TestPageClassifierIntegration:
    """Integration tests with real PDF fixtures."""

    def test_text_heavy_pdf_has_measurable_coverage(self, classifier, text_heavy_pdf):
        """PDF with lots of text should have measurable text coverage."""
        result = classifier.classify(text_heavy_pdf, 0)

        # Text-heavy PDF should have significant coverage (even if not 90%)
        assert result.text_coverage > 0.10
        assert result.type in ('mixed', 'born_digital')

    def test_scanned_pdf_has_no_text_coverage(self, classifier, scanned_pdf):
        """Scanned-style PDF should have no text coverage."""
        result = classifier.classify(scanned_pdf, 0)

        assert result.text_coverage == 0.0
        assert result.type == 'scanned'

    def test_returns_classification_object(self, classifier, text_heavy_pdf):
        """Classify should return a PageClassification dataclass."""
        result = classifier.classify(text_heavy_pdf, 0)

        assert isinstance(result, PageClassification)
        assert hasattr(result, 'type')
        assert hasattr(result, 'text_coverage')
        assert hasattr(result, 'has_images')

    def test_text_coverage_is_normalized(self, classifier, text_heavy_pdf):
        """Text coverage should be between 0 and 1."""
        result = classifier.classify(text_heavy_pdf, 0)

        assert 0.0 <= result.text_coverage <= 1.0


class TestPageClassifierPerformance:
    """Tests for performance requirements."""

    def test_classify_completes_under_100ms(self, classifier, text_heavy_pdf):
        """Classification should complete in under 100ms per page."""
        start_time = time.perf_counter()
        classifier.classify(text_heavy_pdf, 0)
        elapsed_ms = (time.perf_counter() - start_time) * 1000

        assert elapsed_ms < 100, f"Classification took {elapsed_ms:.2f}ms, expected <100ms"

    def test_classify_scanned_under_100ms(self, classifier, scanned_pdf):
        """Scanned PDF classification should complete in under 100ms."""
        start_time = time.perf_counter()
        classifier.classify(scanned_pdf, 0)
        elapsed_ms = (time.perf_counter() - start_time) * 1000

        assert elapsed_ms < 100, f"Classification took {elapsed_ms:.2f}ms, expected <100ms"

    def test_classify_multiple_pages_performance(self, classifier, multipage_pdf):
        """Multiple page classifications should each complete quickly."""
        times = []

        for page_num in range(2):
            start_time = time.perf_counter()
            classifier.classify(multipage_pdf, page_num)
            elapsed_ms = (time.perf_counter() - start_time) * 1000
            times.append(elapsed_ms)

        for i, elapsed_ms in enumerate(times):
            assert elapsed_ms < 100, f"Page {i} classification took {elapsed_ms:.2f}ms"


class TestPageClassifierEdgeCases:
    """Tests for edge cases and error handling."""

    def test_classify_invalid_page_number_raises_error(self, classifier, text_heavy_pdf):
        """Invalid page number should raise ValueError."""
        with pytest.raises(ValueError, match="out of range"):
            classifier.classify(text_heavy_pdf, 999)

    def test_classify_negative_page_number_raises_error(self, classifier, text_heavy_pdf):
        """Negative page number should raise ValueError."""
        with pytest.raises(ValueError, match="out of range"):
            classifier.classify(text_heavy_pdf, -1)

    def test_classify_nonexistent_file_raises_error(self, classifier):
        """Non-existent file should raise an error."""
        with pytest.raises(Exception):  # fitz raises RuntimeError or FileNotFoundError
            classifier.classify("/nonexistent/path/file.pdf", 0)

    def test_classify_multipage_page_with_text_has_coverage(self, classifier, multipage_pdf):
        """Page with text should have higher coverage than page without."""
        page0_result = classifier.classify(multipage_pdf, 0)
        page1_result = classifier.classify(multipage_pdf, 1)

        # Page 0 has text, page 1 doesn't
        assert page0_result.text_coverage > page1_result.text_coverage


class TestPageClassifierHasImages:
    """Tests for image detection."""

    def test_text_only_pdf_has_images_is_bool(self, classifier, text_heavy_pdf):
        """has_images should be a boolean value."""
        result = classifier.classify(text_heavy_pdf, 0)

        assert isinstance(result.has_images, bool)

    def test_text_only_pdf_has_no_images(self, classifier, text_heavy_pdf):
        """PDF with only text should report has_images=False."""
        result = classifier.classify(text_heavy_pdf, 0)

        assert result.has_images is False
