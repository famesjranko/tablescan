"""
pymupdf_extractor.py
    PyMuPDF-based table extraction backend.

    Wraps PyMuPDF's find_tables() method for PDF table extraction.
    Available since PyMuPDF 1.23.0, provides a different algorithm
    than Camelot/pdfplumber for comparative extraction.
"""

import logging
import os
from typing import List, Optional

import fitz
import pandas as pd

from .base import BaseExtractor, ExtractionResult

logger = logging.getLogger(__name__)


class PyMuPDFExtractor(BaseExtractor):
    """
    Table extractor using PyMuPDF's find_tables() method.

    PyMuPDF provides built-in table detection that uses a different
    algorithm than Camelot or pdfplumber. Supports multiple detection
    strategies and can export directly to pandas DataFrames.

    Attributes:
        strategy: Detection strategy ('lines', 'lines_strict', or 'text').
        snap_tolerance: Tolerance for snapping edges (points). Defaults to 3.
        join_tolerance: Tolerance for joining lines (points). Defaults to 3.
        min_words_vertical: Minimum words for vertical text alignment. Defaults to 3.
        min_words_horizontal: Minimum words for horizontal text alignment. Defaults to 1.
    """

    def __init__(
        self,
        strategy: str = 'lines',
        snap_tolerance: int = 3,
        join_tolerance: int = 3,
        min_words_vertical: int = 3,
        min_words_horizontal: int = 1
    ):
        """
        Initialize PyMuPDFExtractor.

        Args:
            strategy: Detection strategy ('lines', 'lines_strict', or 'text').
                - 'lines': Use visible lines to detect table structure.
                - 'lines_strict': Stricter line detection.
                - 'text': Use text alignment for borderless tables.
            snap_tolerance: Tolerance for snapping table edges.
            join_tolerance: Tolerance for joining lines.
            min_words_vertical: Minimum words for vertical alignment.
            min_words_horizontal: Minimum words for horizontal alignment.

        Raises:
            ValueError: If strategy is not valid.
        """
        valid_strategies = ('lines', 'lines_strict', 'text')
        if strategy not in valid_strategies:
            raise ValueError(
                f"strategy must be one of {valid_strategies}, got '{strategy}'"
            )

        self._strategy = strategy
        self._snap_tolerance = snap_tolerance
        self._join_tolerance = join_tolerance
        self._min_words_vertical = min_words_vertical
        self._min_words_horizontal = min_words_horizontal

    @property
    def name(self) -> str:
        """Return the unique name of this extractor."""
        if self._strategy == 'text':
            return "pymupdf_text"
        elif self._strategy == 'lines_strict':
            return "pymupdf_strict"
        return "pymupdf"

    def extract(
        self,
        pdf_path: str,
        page_num: int,
        table_areas: Optional[List[tuple]] = None
    ) -> List[ExtractionResult]:
        """
        Extract tables from a PDF page using PyMuPDF find_tables().

        Args:
            pdf_path: Path to the PDF file.
            page_num: Page number to extract from (1-indexed).
            table_areas: Optional list of bounding boxes [(x1, y1, x2, y2), ...].
                         Coordinates are in PDF coordinate space (origin at bottom-left).
                         If None, returns empty list (table_areas required by pipeline).

        Returns:
            List of ExtractionResult, one per detected table.
            Empty list if no tables found.

        Raises:
            FileNotFoundError: If PDF file doesn't exist.
            ValueError: If page_num is out of range.
        """
        if not os.path.isfile(pdf_path):
            raise FileNotFoundError(f"PDF file not found: {pdf_path}")

        results = []

        try:
            with fitz.open(pdf_path) as doc:
                if page_num < 1 or page_num > len(doc):
                    raise ValueError(
                        f"Page {page_num} is out of range for {pdf_path} "
                        f"(has {len(doc)} pages)"
                    )

                page = doc[page_num - 1]

                if not table_areas:
                    logger.warning(
                        f"[{self.name}] No table_areas provided - pipeline error, skipping"
                    )
                    return []

                for i, (x1, y1, x2, y2) in enumerate(table_areas):
                    region_results = self._extract_from_region(
                        page, x1, y1, x2, y2, i, page_num
                    )
                    results.extend(region_results)

        except ValueError:
            raise
        except Exception as e:
            logger.warning(f"[{self.name}] Extraction failed for page {page_num}: {e}")
            return []

        return results

    def _extract_from_region(
        self,
        page: fitz.Page,
        x1: float,
        y1: float,
        x2: float,
        y2: float,
        region_index: int,
        page_num: int
    ) -> List[ExtractionResult]:
        """
        Extract tables from a specific region of the page.

        Args:
            page: PyMuPDF Page object.
            x1, y1, x2, y2: Bounding box in PDF coordinates (bottom-left origin).
            region_index: Index of this region.
            page_num: Page number (1-indexed).

        Returns:
            List of ExtractionResult from this region.
        """
        results = []

        # Convert PDF coordinates (origin bottom-left, Y up)
        # to PyMuPDF coordinates (origin top-left, Y down)
        page_height = page.rect.height
        mupdf_y0 = page_height - y1  # PDF y1 (top) → mupdf top
        mupdf_y1 = page_height - y2  # PDF y2 (bottom) → mupdf bottom

        # Ensure correct ordering (y0 should be smaller)
        if mupdf_y0 > mupdf_y1:
            mupdf_y0, mupdf_y1 = mupdf_y1, mupdf_y0

        clip = fitz.Rect(x1, mupdf_y0, x2, mupdf_y1)

        try:
            table_finder = page.find_tables(
                clip=clip,
                strategy=self._strategy,
                snap_tolerance=self._snap_tolerance,
                join_tolerance=self._join_tolerance,
                min_words_vertical=self._min_words_vertical,
                min_words_horizontal=self._min_words_horizontal,
            )

            for j, table in enumerate(table_finder.tables):
                result = self._process_table(
                    table,
                    table_index=region_index * 100 + j,
                    page_num=page_num,
                    original_bbox=(x1, y1, x2, y2)
                )
                if result:
                    results.append(result)

        except Exception as e:
            logger.warning(
                f"[{self.name}] Region {region_index} extraction failed: {e}"
            )

        return results

    def _process_table(
        self,
        table,
        table_index: int,
        page_num: int,
        original_bbox: tuple
    ) -> Optional[ExtractionResult]:
        """
        Process a PyMuPDF Table into ExtractionResult.

        Args:
            table: PyMuPDF Table object.
            table_index: Index of this table.
            page_num: Page number (1-indexed).
            original_bbox: Original bounding box in PDF coordinates.

        Returns:
            ExtractionResult or None if table is invalid.
        """
        try:
            df = table.to_pandas()

            if df is None or df.empty:
                return None

            if not self._is_valid_table(df):
                return None

            df = self._clean_dataframe(df)
            confidence = self._calculate_confidence(df, table)
            metadata = self._build_metadata(table, table_index, page_num, original_bbox)

            return ExtractionResult(
                dataframe=df,
                confidence=confidence,
                method=self.name,
                metadata=metadata
            )

        except Exception as e:
            logger.debug(f"[{self.name}] Failed to process table: {e}")
            return None

    def _is_valid_table(self, df: pd.DataFrame) -> bool:
        """
        Validate that a table has meaningful content.

        A valid table must have at least 2 rows and 2 columns.

        Args:
            df: DataFrame to validate.

        Returns:
            True if table is valid, False otherwise.
        """
        return len(df) >= 2 and len(df.columns) >= 2

    def _clean_dataframe(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Clean extracted DataFrame.

        - Replaces None/NaN values with empty strings
        - Strips whitespace from cells
        - Resets index

        Args:
            df: Raw DataFrame from PyMuPDF.

        Returns:
            Cleaned DataFrame.
        """
        df = df.copy()
        df = df.fillna('')
        df = df.map(lambda x: str(x).strip() if x is not None else '')
        df = df.reset_index(drop=True)
        return df

    def _calculate_confidence(self, df: pd.DataFrame, table) -> float:
        """
        Calculate confidence score based on table detection quality.

        Factors considered:
        - Cell fill rate: percentage of non-empty cells
        - Structure regularity: consistent dimensions
        - Numeric content: presence of numeric data

        Args:
            df: Cleaned DataFrame.
            table: PyMuPDF Table object.

        Returns:
            Confidence score from 0.0 to 1.0.
        """
        if df.empty:
            return 0.0

        # Factor 1: Cell fill rate
        total_cells = df.size
        non_empty_cells = (df != '').sum().sum()
        fill_rate = non_empty_cells / total_cells if total_cells > 0 else 0.0

        # Factor 2: Structure regularity (PyMuPDF tables are always regular)
        regularity = 1.0

        # Factor 3: Numeric content presence
        numeric_count = 0
        for col in df.columns:
            numeric_count += df[col].apply(self._has_numeric_content).sum()
        numeric_ratio = numeric_count / total_cells if total_cells > 0 else 0.0

        # Factor 4: Row/column count bonus (larger tables more likely to be real)
        size_bonus = min((table.row_count * table.col_count) / 20, 0.2)

        confidence = (
            0.4 * fill_rate +
            0.2 * regularity +
            0.2 * min(numeric_ratio * 2, 1.0) +
            size_bonus
        )

        return round(min(confidence, 1.0), 3)

    def _has_numeric_content(self, value: str) -> bool:
        """
        Check if a string contains numeric content.

        Args:
            value: String to check.

        Returns:
            True if string contains digits, False otherwise.
        """
        if not value:
            return False
        return any(c.isdigit() for c in str(value))

    def _build_metadata(
        self,
        table,
        table_index: int,
        page_num: int,
        original_bbox: tuple
    ) -> dict:
        """
        Build metadata dictionary.

        Args:
            table: PyMuPDF Table object.
            table_index: Index of this table.
            page_num: Page number (1-indexed).
            original_bbox: Original bounding box in PDF coordinates.

        Returns:
            Metadata dictionary.
        """
        x1, y1, x2, y2 = original_bbox

        metadata = {
            'table_index': table_index,
            'page_num': page_num,
            'bounding_box': {
                'x1': x1,
                'y1': y1,
                'x2': x2,
                'y2': y2
            },
            'extractor_settings': {
                'strategy': self._strategy,
                'snap_tolerance': self._snap_tolerance,
                'join_tolerance': self._join_tolerance,
            },
            'table_dimensions': {
                'rows': table.row_count,
                'cols': table.col_count,
            }
        }

        # Add header info if available
        try:
            if table.header and table.header.names:
                metadata['header_detected'] = True
                metadata['header_names'] = list(table.header.names)
        except Exception:
            metadata['header_detected'] = False

        return metadata
