"""
camelot_extractor.py
    Camelot-based table extraction backend.

    Wraps Camelot library for PDF table extraction,
    supporting both 'lattice' (bordered tables) and 'stream' (borderless tables) modes.
"""

import logging
import os
from pathlib import Path
from typing import List, Optional

import pandas as pd
from camelot import io as camelot

from .base import BaseExtractor, ExtractionResult

logger = logging.getLogger(__name__)


class CamelotExtractor(BaseExtractor):
    """
    Table extractor using Camelot library.

    Supports two extraction flavors:
    - 'lattice': For tables with visible borders/gridlines
    - 'stream': For tables without visible borders (uses whitespace analysis)

    Attributes:
        flavor: Extraction mode ('lattice' or 'stream'). Defaults to 'lattice'.
        backend: PDF rendering backend ('poppler' or 'ghostscript'). Defaults to 'poppler'.
        row_tol: Row tolerance for stream mode (pixels). Defaults to 2.
        strip_text: Characters to strip from cell text. Defaults to '\\n'.
    """

    def __init__(
        self,
        flavor: str = 'lattice',
        backend: str = 'poppler',
        row_tol: int = 2,
        strip_text: str = '\n'
    ):
        """
        Initialize CamelotExtractor.

        Args:
            flavor: Extraction mode ('lattice' or 'stream').
            backend: PDF rendering backend ('poppler' or 'ghostscript').
            row_tol: Row tolerance for stream mode (pixels between rows).
            strip_text: Characters to strip from extracted cell text.

        Raises:
            ValueError: If flavor is not 'lattice' or 'stream'.
        """
        if flavor not in ('lattice', 'stream'):
            raise ValueError(f"flavor must be 'lattice' or 'stream', got '{flavor}'")

        self._flavor = flavor
        self._backend = backend
        self._row_tol = row_tol
        self._strip_text = strip_text

    @property
    def name(self) -> str:
        """Return the unique name of this extractor."""
        return f"camelot_{self._flavor}"

    @property
    def flavor(self) -> str:
        """Return the Camelot flavor being used."""
        return self._flavor

    def extract(
        self,
        pdf_path: str,
        page_num: int,
        table_areas: Optional[List[tuple]] = None
    ) -> List[ExtractionResult]:
        """
        Extract tables from a PDF page using Camelot.

        Args:
            pdf_path: Path to the PDF file.
            page_num: Page number to extract from (1-indexed).
            table_areas: Optional list of bounding boxes [(x1, y1, x2, y2), ...].
                         Coordinates are in PDF coordinate space (origin at bottom-left).
                         If None, Camelot will auto-detect table regions.

        Returns:
            List of ExtractionResult, one per detected table.
            Empty list if no tables found.

        Raises:
            FileNotFoundError: If PDF file doesn't exist.
            ValueError: If page_num is out of range.
        """
        # Validate PDF file exists
        if not os.path.isfile(pdf_path):
            raise FileNotFoundError(f"PDF file not found: {pdf_path}")

        # Build Camelot arguments
        kwargs = {
            'filepath': pdf_path,
            'pages': str(page_num),
            'flavor': self._flavor,
            'backend': self._backend,
        }

        # Add flavor-specific options
        if self._flavor == 'stream':
            kwargs['row_tol'] = self._row_tol

        if self._strip_text:
            kwargs['strip_text'] = self._strip_text

        # Convert table_areas to Camelot format if provided
        if table_areas:
            # Camelot expects comma-separated strings: ["x1,y1,x2,y2", ...]
            camelot_areas = [
                f"{x1},{y1},{x2},{y2}" for (x1, y1, x2, y2) in table_areas
            ]
            kwargs['table_areas'] = camelot_areas

        # Run Camelot extraction
        try:
            tables = camelot.read_pdf(**kwargs)
        except Exception as e:
            # Page number out of range or other Camelot errors
            if "page" in str(e).lower() and "out" in str(e).lower():
                raise ValueError(f"Page {page_num} is out of range for {pdf_path}")
            # Return empty list for extraction failures (no tables found is not an error)
            # Log at DEBUG level for troubleshooting (MultiExtractor logs at INFO/WARNING)
            logger.debug(f"[CamelotExtractor] Extraction failed for {pdf_path} page {page_num}: {e}")
            return []

        # Convert Camelot tables to ExtractionResult
        results = []
        for i, table in enumerate(tables):
            # Validate table has meaningful content
            if not self._is_valid_table(table.df):
                continue

            # Get confidence from parsing report
            confidence = self._get_confidence(table)

            # Clean the dataframe
            df = self._clean_dataframe(table.df)

            # Extract metadata
            metadata = self._build_metadata(table, i, page_num)

            result = ExtractionResult(
                dataframe=df,
                confidence=confidence,
                method=self.name,
                metadata=metadata
            )
            results.append(result)

        return results

    def _is_valid_table(self, df: pd.DataFrame) -> bool:
        """
        Validate that a table has meaningful content.

        A valid table must have at least 2 rows and 2 columns.
        This filters out noise and non-tabular content.

        Args:
            df: DataFrame to validate.

        Returns:
            True if table is valid, False otherwise.
        """
        return len(df) >= 2 and len(df.columns) >= 2

    def _get_confidence(self, table) -> float:
        """
        Extract confidence score from Camelot table.

        Camelot provides an 'accuracy' metric in the parsing report,
        which measures how well the table structure was detected.

        Args:
            table: Camelot Table object.

        Returns:
            Confidence score from 0.0 to 1.0.
        """
        if hasattr(table, 'parsing_report') and table.parsing_report:
            accuracy = table.parsing_report.get('accuracy', 0)
            # Camelot accuracy is 0-100, normalize to 0-1
            return accuracy / 100.0
        return 0.0

    def _clean_dataframe(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Clean extracted DataFrame.

        - Replaces NaN values with empty strings
        - Resets index

        Args:
            df: Raw DataFrame from Camelot.

        Returns:
            Cleaned DataFrame.
        """
        df = df.copy()
        df = df.fillna('')
        df = df.reset_index(drop=True)
        return df

    def _build_metadata(self, table, table_index: int, page_num: int) -> dict:
        """
        Build metadata dictionary from Camelot table.

        Args:
            table: Camelot Table object.
            table_index: Index of this table on the page.
            page_num: Page number.

        Returns:
            Metadata dictionary with parsing details.
        """
        metadata = {
            'table_index': table_index,
            'page_num': page_num,
            'flavor': self._flavor,
        }

        # Add parsing report if available
        if hasattr(table, 'parsing_report') and table.parsing_report:
            metadata['parsing_report'] = table.parsing_report

        # Add bounding box if available
        if hasattr(table, '_bbox') and table._bbox:
            x1, y1, x2, y2 = table._bbox
            metadata['bounding_box'] = {
                'x1': x1,
                'y1': y1,
                'x2': x2,
                'y2': y2
            }

        return metadata
