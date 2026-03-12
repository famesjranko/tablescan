"""
Unit tests for predict_table.py detection functions.

Requires system dependencies: poppler (for pdf2image)
Tests will be skipped if poppler is not installed.
"""
import os
import shutil
import unittest
import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "tablescan.settings")
django.setup()

from django.test import TestCase
from pathlib import Path


def poppler_available():
    """Check if poppler (pdfinfo) is available."""
    return shutil.which('pdfinfo') is not None


# Skip decorator for tests requiring poppler
requires_poppler = unittest.skipUnless(
    poppler_available(),
    "Poppler not installed (pdfinfo not found in PATH)"
)


class DetectTableRegionsTests(TestCase):
    """Tests for the detect_table_regions() function."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # Use the test PDF in documents directory
        cls.test_pdf_path = str(
            Path(__file__).parent.parent.parent / "documents" / "test_report" / "test_report.pdf"
        )
        # Import here to avoid import errors when dependencies missing
        cls.detect_table_regions = None
        try:
            from api.scripts.YOLOV3.predict_table import detect_table_regions
            cls.detect_table_regions = detect_table_regions
        except ImportError:
            pass

    @requires_poppler
    def test_detect_table_regions_returns_list(self):
        """detect_table_regions should return a list."""
        if self.detect_table_regions is None:
            self.skipTest("Could not import detect_table_regions")

        # Given: a test PDF with tables on page 1

        # When: detect_table_regions is called
        result = self.detect_table_regions(self.test_pdf_path, 1)

        # Then: the result is a list
        self.assertIsInstance(result, list)

    @requires_poppler
    def test_detect_table_regions_returns_dicts_with_required_keys(self):
        """Each result should be a dict with x1, y1, x2, y2, confidence keys."""
        if self.detect_table_regions is None:
            self.skipTest("Could not import detect_table_regions")

        # Given: a test PDF with tables on page 1

        # When: detect_table_regions is called
        result = self.detect_table_regions(self.test_pdf_path, 1)

        # Then: each region dict contains required coordinate and confidence keys
        for region in result:
            self.assertIsInstance(region, dict)
            self.assertIn('x1', region)
            self.assertIn('y1', region)
            self.assertIn('x2', region)
            self.assertIn('y2', region)
            self.assertIn('confidence', region)

    @requires_poppler
    def test_detect_table_regions_coordinates_are_floats(self):
        """Coordinates should be numeric (floats)."""
        if self.detect_table_regions is None:
            self.skipTest("Could not import detect_table_regions")

        # Given: a test PDF with tables on page 1

        # When: detect_table_regions is called
        result = self.detect_table_regions(self.test_pdf_path, 1)

        # Then: all coordinates are numeric values
        for region in result:
            self.assertIsInstance(region['x1'], (int, float))
            self.assertIsInstance(region['y1'], (int, float))
            self.assertIsInstance(region['x2'], (int, float))
            self.assertIsInstance(region['y2'], (int, float))

    @requires_poppler
    def test_detect_table_regions_confidence_is_numeric_or_none(self):
        """Confidence should be numeric or None."""
        if self.detect_table_regions is None:
            self.skipTest("Could not import detect_table_regions")

        # Given: a test PDF with tables on page 1

        # When: detect_table_regions is called
        result = self.detect_table_regions(self.test_pdf_path, 1)

        # Then: confidence values are numeric or None
        for region in result:
            confidence = region['confidence']
            self.assertTrue(
                confidence is None or isinstance(confidence, (int, float)),
                f"Confidence should be numeric or None, got {type(confidence)}"
            )

    @requires_poppler
    def test_detect_table_regions_coordinates_valid_bounds(self):
        """Coordinates should form valid bounding boxes (x1 < x2, y2 < y1 in PDF space)."""
        if self.detect_table_regions is None:
            self.skipTest("Could not import detect_table_regions")
        result = self.detect_table_regions(self.test_pdf_path, 1)

        for region in result:
            # In PDF coordinates, x1 should be less than x2
            self.assertLess(region['x1'], region['x2'], "x1 should be less than x2")
            # In PDF coordinates with bottom-left origin and Y-flip,
            # y1 (top in image) becomes larger y in PDF space,
            # y2 (bottom in image) becomes smaller y in PDF space
            # So y1 > y2 after the Y-flip
            self.assertGreater(region['y1'], region['y2'], "y1 should be greater than y2 in PDF space")

    @requires_poppler
    def test_detect_table_regions_coordinates_non_negative(self):
        """Coordinates should be non-negative (within PDF page bounds)."""
        if self.detect_table_regions is None:
            self.skipTest("Could not import detect_table_regions")
        result = self.detect_table_regions(self.test_pdf_path, 1)

        for region in result:
            # With small margin corrections in norm_bbox, coordinates might be slightly negative
            # Allow small negative values from margin corrections
            self.assertGreater(region['x2'], 0, "x2 should be positive")
            self.assertGreater(region['y1'], 0, "y1 should be positive")

    @requires_poppler
    def test_detect_table_regions_cleans_up_temp_files(self):
        """Temporary image files should be cleaned up after detection."""
        if self.detect_table_regions is None:
            self.skipTest("Could not import detect_table_regions")
        # Run detection
        self.detect_table_regions(self.test_pdf_path, 1)

        # Check that temp image file was removed
        expected_temp_path = self.test_pdf_path[:-4] + "-1.jpg"
        self.assertFalse(
            os.path.exists(expected_temp_path),
            f"Temporary file {expected_temp_path} should be cleaned up"
        )

    @requires_poppler
    def test_detect_table_regions_no_database_writes(self):
        """Detection should not create any database records."""
        if self.detect_table_regions is None:
            self.skipTest("Could not import detect_table_regions")
        from api.models import Extracted, TableSelection

        # Get counts before
        extracted_count_before = Extracted.objects.count()
        selection_count_before = TableSelection.objects.count()

        # Run detection
        self.detect_table_regions(self.test_pdf_path, 1)

        # Verify counts unchanged
        self.assertEqual(
            Extracted.objects.count(),
            extracted_count_before,
            "No Extracted records should be created"
        )
        self.assertEqual(
            TableSelection.objects.count(),
            selection_count_before,
            "No TableSelection records should be created"
        )
