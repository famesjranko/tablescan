"""
base.py
    Base classes for table extraction backends.

    Defines the interface that all extractors must implement,
    plus the ExtractionResult dataclass for standardized output.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

import pandas as pd


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
