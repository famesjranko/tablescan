"""
page_classifier.py
    Classify PDF pages as born-digital, scanned, or mixed using PyMuPDF.

    Born-digital: >90% of page content is extractable text
    Scanned: <10% extractable text, primarily image content
    Mixed: 10-90% extractable text, or text quality issues detected
"""

from dataclasses import dataclass
from typing import Literal

import fitz  # PyMuPDF


PageType = Literal['born_digital', 'scanned', 'mixed']


@dataclass
class PageClassification:
    """Result of page classification analysis."""
    type: PageType
    text_coverage: float  # 0-1, ratio of text area to page area
    has_images: bool


class PageClassifier:
    """
    Classify PDF pages based on text layer presence and quality.

    Uses PyMuPDF to extract text blocks and calculate coverage ratio
    to determine if a page is born-digital, scanned, or mixed.
    """

    # Thresholds for classification
    BORN_DIGITAL_THRESHOLD = 0.90  # >90% text coverage
    SCANNED_THRESHOLD = 0.10       # <10% text coverage

    def classify(self, pdf_path: str, page_num: int) -> PageClassification:
        """
        Classify a single PDF page.

        Args:
            pdf_path: Path to the PDF file
            page_num: Page number (0-indexed)

        Returns:
            PageClassification with type, text_coverage, and has_images

        Raises:
            FileNotFoundError: If PDF file doesn't exist
            ValueError: If page_num is out of range
        """
        doc = fitz.open(pdf_path)

        try:
            if page_num < 0 or page_num >= len(doc):
                raise ValueError(f"Page {page_num} out of range (0-{len(doc)-1})")

            page = doc[page_num]

            # Get page dimensions
            page_rect = page.rect
            page_area = page_rect.width * page_rect.height

            if page_area == 0:
                return PageClassification(
                    type='scanned',
                    text_coverage=0.0,
                    has_images=False
                )

            # Extract text blocks with position info
            text_blocks = page.get_text("blocks")

            # Calculate total text area
            text_area = 0.0
            for block in text_blocks:
                # Block format: (x0, y0, x1, y1, "text", block_no, block_type)
                # block_type: 0 = text, 1 = image
                if len(block) >= 7 and block[6] == 0:  # Text block
                    x0, y0, x1, y1 = block[:4]
                    block_area = (x1 - x0) * (y1 - y0)
                    text_area += block_area

            # Check for images
            image_list = page.get_images(full=True)
            has_images = len(image_list) > 0

            # Calculate text coverage ratio
            text_coverage = min(text_area / page_area, 1.0)

            # Classify based on thresholds
            page_type = self._determine_type(text_coverage, has_images)

            return PageClassification(
                type=page_type,
                text_coverage=text_coverage,
                has_images=has_images
            )
        finally:
            doc.close()

    def _determine_type(self, text_coverage: float, has_images: bool) -> PageType:
        """
        Determine page type based on text coverage and image presence.

        Args:
            text_coverage: Ratio of text area to page area (0-1)
            has_images: Whether page contains images

        Returns:
            Page type classification
        """
        if text_coverage >= self.BORN_DIGITAL_THRESHOLD:
            return 'born_digital'
        elif text_coverage < self.SCANNED_THRESHOLD:
            return 'scanned'
        else:
            return 'mixed'
