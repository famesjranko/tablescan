"""
base.py
    Base classes for table extraction backends.

    Defines the interface that all extractors must implement,
    plus the ExtractionResult dataclass for standardized output.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd


# Coordinate system constants
COORD_PDF_BOTTOM_LEFT = "pdf_bottom_left"  # PDF standard: origin bottom-left, y increases up
COORD_PDF_TOP_LEFT = "pdf_top_left"        # pdfplumber: origin top-left, y increases down
COORD_IMAGE = "image"                       # Pixel coords: origin top-left, y increases down
COORD_NORMALIZED = "normalized"             # 0-1 range, origin top-left


@dataclass
class BoundingBox:
    """
    Unified bounding box representation with coordinate system conversion.

    Internal representation uses PDF bottom-left coordinates (standard).
    x1, y1 = bottom-left corner (y1 is LOWER value)
    x2, y2 = top-right corner (y2 is HIGHER value)
    """
    x1: float
    y1: float  # Bottom (lower y in PDF coords)
    x2: float
    y2: float  # Top (higher y in PDF coords)
    page_width: float = 612.0
    page_height: float = 792.0

    @classmethod
    def from_yolo(
        cls,
        x1: float, y1: float, x2: float, y2: float,
        img_width: float, img_height: float,
        page_width: float, page_height: float
    ) -> "BoundingBox":
        """
        Create BoundingBox from YOLO pixel coordinates (top-left origin).

        Args:
            x1, y1: Top-left corner in pixels (y1 is TOP of box)
            x2, y2: Bottom-right corner in pixels (y2 is BOTTOM of box)
            img_width, img_height: Image dimensions in pixels
            page_width, page_height: PDF page dimensions

        Returns:
            BoundingBox in PDF bottom-left coordinates
        """
        # Normalize to 0-1
        x1_norm = x1 / img_width
        y1_norm = y1 / img_height  # TOP of box (small value)
        x2_norm = x2 / img_width
        y2_norm = y2 / img_height  # BOTTOM of box (large value)

        # Convert to PDF bottom-left coords
        pdf_x1 = x1_norm * page_width
        pdf_x2 = x2_norm * page_width
        # Flip y: image y=0 (top) -> PDF y=height (top)
        pdf_y1 = (1 - y2_norm) * page_height  # BOTTOM of box in PDF
        pdf_y2 = (1 - y1_norm) * page_height  # TOP of box in PDF

        return cls(
            x1=pdf_x1, y1=pdf_y1, x2=pdf_x2, y2=pdf_y2,
            page_width=page_width, page_height=page_height
        )

    @classmethod
    def from_pdf_coords(
        cls,
        x1: float, y1: float, x2: float, y2: float,
        page_width: float = 612.0, page_height: float = 792.0
    ) -> "BoundingBox":
        """
        Create from PDF coordinates where y1 might be > y2 (from bboxes_pdf).

        Normalizes so y1 < y2 (y1 = bottom, y2 = top).
        """
        # Ensure y1 < y2 (y1 = bottom)
        if y1 > y2:
            y1, y2 = y2, y1
        return cls(x1=x1, y1=y1, x2=x2, y2=y2, page_width=page_width, page_height=page_height)

    def to_camelot(self) -> str:
        """
        Convert to Camelot format: 'x1,y1,x2,y2'.

        Camelot expects y1 > y2 (y1=top, y2=bottom in PDF coords).
        This is the opposite of standard PDF bbox convention.
        """
        # Camelot wants y1 > y2, so swap our normalized y1/y2
        return f"{self.x1},{self.y2},{self.x2},{self.y1}"

    def to_pdfplumber(self) -> Tuple[float, float, float, float]:
        """
        Convert to pdfplumber format: (x0, top, x1, bottom) in top-left coords.

        Returns (x1, top, x2, bottom) where top < bottom.
        """
        # pdfplumber: y=0 is TOP of page
        top = self.page_height - self.y2   # PDF top (high y) -> plumber low y
        bottom = self.page_height - self.y1  # PDF bottom (low y) -> plumber high y
        return (self.x1, top, self.x2, bottom)

    def to_pymupdf(self) -> Tuple[float, float, float, float]:
        """
        Convert to PyMuPDF format: (x0, y0, x1, y1) in top-left coords.

        Same as pdfplumber - PyMuPDF uses top-left origin.
        """
        return self.to_pdfplumber()

    def to_tuple(self) -> Tuple[float, float, float, float]:
        """Return as tuple in internal PDF coords (y1 < y2)."""
        return (self.x1, self.y1, self.x2, self.y2)


@dataclass
class ExtractionResult:
    """
    Standardized result from a table extractor.

    Attributes:
        dataframe: Extracted table data as a pandas DataFrame.
        confidence: Confidence score from 0.0 to 1.0 indicating extraction quality.
        method: Name of the extraction method used (e.g., 'camelot_lattice', 'pdfplumber').
        metadata: Additional extraction metadata (bounding box, parse report, etc.).
    """
    dataframe: pd.DataFrame
    confidence: float
    method: str
    metadata: Dict[str, Any] = field(default_factory=dict)


class BaseExtractor(ABC):
    """
    Abstract base class for table extractors.

    All extractor implementations must inherit from this class
    and implement the extract() and name() methods.
    """

    @abstractmethod
    def extract(
        self,
        pdf_path: str,
        page_num: int,
        table_areas: Optional[list] = None
    ) -> list[ExtractionResult]:
        """
        Extract tables from a PDF page.

        Args:
            pdf_path: Path to the PDF file.
            page_num: Page number to extract from (1-indexed for Camelot compatibility).
            table_areas: List of bounding boxes [(x1, y1, x2, y2), ...] in PDF coordinates.
                         REQUIRED: Extractors expect regions from YOLO detection or manual selection.
                         If None/empty, extractors will log a warning and return empty list.

        Returns:
            List of ExtractionResult, one per detected table.
            Empty list if no tables found or table_areas not provided.

        Raises:
            FileNotFoundError: If PDF file doesn't exist.
            ValueError: If page_num is out of range.
        """
        pass

    @property
    @abstractmethod
    def name(self) -> str:
        """
        Return the unique name of this extractor.

        Returns:
            String identifier for this extractor (e.g., 'camelot', 'pdfplumber').
        """
        pass
