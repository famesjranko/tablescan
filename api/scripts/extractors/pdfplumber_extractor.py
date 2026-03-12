"""
pdfplumber_extractor.py
    pdfplumber-based table extraction backend.

    Wraps pdfplumber library for PDF table extraction,
    optimized for born-digital PDFs with text-based table structures.
"""

import logging
import os
from typing import List, Optional

import pandas as pd
import pdfplumber

from .base import BaseExtractor, ExtractionResult

logger = logging.getLogger(__name__)


class PdfplumberExtractor(BaseExtractor):
    """
    Table extractor using pdfplumber library.

    pdfplumber is particularly effective for born-digital PDFs where
    text is embedded rather than scanned. It uses text positioning
    and optional line detection to identify table structures.

    Attributes:
        vertical_strategy: Strategy for detecting vertical lines ('lines', 'lines_strict', 'text', 'explicit').
        horizontal_strategy: Strategy for detecting horizontal lines ('lines', 'lines_strict', 'text', 'explicit').
        snap_tolerance: Tolerance for snapping table edges (pixels). Defaults to 3.
        join_tolerance: Tolerance for joining lines (pixels). Defaults to 3.
        edge_min_length: Minimum length for detected edges. Defaults to 3.
        min_words_vertical: Minimum words to consider for vertical text alignment. Defaults to 3.
        min_words_horizontal: Minimum words to consider for horizontal text alignment. Defaults to 1.
    """

    def __init__(
        self,
        vertical_strategy: str = 'lines',
        horizontal_strategy: str = 'lines',
        snap_tolerance: int = 3,
        join_tolerance: int = 3,
        edge_min_length: int = 3,
        min_words_vertical: int = 3,
        min_words_horizontal: int = 1
    ):
        """
        Initialize PdfplumberExtractor.

        Args:
            vertical_strategy: Strategy for vertical line detection.
            horizontal_strategy: Strategy for horizontal line detection.
            snap_tolerance: Tolerance for snapping table edges.
            join_tolerance: Tolerance for joining lines.
            edge_min_length: Minimum edge length to consider.
            min_words_vertical: Minimum words for vertical alignment.
            min_words_horizontal: Minimum words for horizontal alignment.
        """
        self._vertical_strategy = vertical_strategy
        self._horizontal_strategy = horizontal_strategy
        self._snap_tolerance = snap_tolerance
        self._join_tolerance = join_tolerance
        self._edge_min_length = edge_min_length
        self._min_words_vertical = min_words_vertical
        self._min_words_horizontal = min_words_horizontal

    @property
    def name(self) -> str:
        """Return the unique name of this extractor."""
        return "pdfplumber"

    def extract(
        self,
        pdf_path: str,
        page_num: int,
        table_areas: Optional[List[tuple]] = None
    ) -> List[ExtractionResult]:
        """
        Extract tables from a PDF page using pdfplumber.

        Args:
            pdf_path: Path to the PDF file.
            page_num: Page number to extract from (1-indexed for consistency with Camelot).
            table_areas: Optional list of bounding boxes [(x1, y1, x2, y2), ...].
                         If provided, only tables within these areas are extracted.
                         If None, pdfplumber will auto-detect table regions.

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

        results = []

        try:
            with pdfplumber.open(pdf_path) as pdf:
                # Validate page number (pdfplumber uses 0-indexed pages)
                if page_num < 1 or page_num > len(pdf.pages):
                    raise ValueError(
                        f"Page {page_num} is out of range for {pdf_path} "
                        f"(has {len(pdf.pages)} pages)"
                    )

                page = pdf.pages[page_num - 1]  # Convert to 0-indexed

                # Build table settings
                table_settings = self._build_table_settings()

                # Extract tables
                if table_areas:
                    # Extract from specific areas
                    for i, (x1, y1, x2, y2) in enumerate(table_areas):
                        # Convert from PDF coordinates (origin bottom-left, y increases up)
                        # to pdfplumber coordinates (origin top-left, y increases down)
                        # PDF y1 = top (higher value) → plumber top (lower value)
                        # PDF y2 = bottom (lower value) → plumber bottom (higher value)
                        page_height = page.height
                        plumber_top = page_height - y1
                        plumber_bottom = page_height - y2
                        plumber_bbox = (x1, plumber_top, x2, plumber_bottom)
                        cropped = page.within_bbox(plumber_bbox)
                        tables = cropped.extract_tables(table_settings)

                        for j, table_data in enumerate(tables):
                            result = self._process_table(
                                table_data, page, i * 100 + j, page_num,
                                bbox=(x1, y1, x2, y2)
                            )
                            if result:
                                results.append(result)
                else:
                    # Auto-detect tables
                    tables = page.find_tables(table_settings)

                    for i, table in enumerate(tables):
                        table_data = table.extract()
                        bbox = table.bbox if hasattr(table, 'bbox') else None
                        result = self._process_table(
                            table_data, page, i, page_num, bbox=bbox
                        )
                        if result:
                            results.append(result)

        except ValueError:
            # Re-raise ValueError for page out of range
            raise
        except Exception as e:
            # Return empty list for other extraction failures
            # Log at DEBUG level for troubleshooting (MultiExtractor logs at INFO/WARNING)
            logger.debug(f"[PdfplumberExtractor] Extraction failed for {pdf_path} page {page_num}: {e}")
            return []

        return results

    def _build_table_settings(self) -> dict:
        """
        Build pdfplumber table settings dictionary.

        Returns:
            Dictionary of table extraction settings.
        """
        return {
            "vertical_strategy": self._vertical_strategy,
            "horizontal_strategy": self._horizontal_strategy,
            "snap_tolerance": self._snap_tolerance,
            "join_tolerance": self._join_tolerance,
            "edge_min_length": self._edge_min_length,
            "min_words_vertical": self._min_words_vertical,
            "min_words_horizontal": self._min_words_horizontal,
        }

    def _process_table(
        self,
        table_data: List[List],
        page,
        table_index: int,
        page_num: int,
        bbox: Optional[tuple] = None
    ) -> Optional[ExtractionResult]:
        """
        Process raw table data into ExtractionResult.

        Args:
            table_data: Raw table data from pdfplumber (list of rows).
            page: pdfplumber Page object.
            table_index: Index of this table on the page.
            page_num: Page number (1-indexed).
            bbox: Optional bounding box of the table.

        Returns:
            ExtractionResult or None if table is invalid.
        """
        if not table_data:
            return None

        # Convert to DataFrame
        df = pd.DataFrame(table_data)

        # Validate table has meaningful content
        if not self._is_valid_table(df):
            return None

        # Clean the dataframe
        df = self._clean_dataframe(df)

        # Calculate confidence score
        confidence = self._calculate_confidence(df, table_data)

        # Build metadata
        metadata = self._build_metadata(table_index, page_num, bbox, page)

        return ExtractionResult(
            dataframe=df,
            confidence=confidence,
            method=self.name,
            metadata=metadata
        )

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

        - Replaces None values with empty strings
        - Strips whitespace from cells
        - Resets index

        Args:
            df: Raw DataFrame from pdfplumber.

        Returns:
            Cleaned DataFrame.
        """
        df = df.copy()
        # Replace None with empty string
        df = df.fillna('')
        # Convert all cells to string and strip whitespace
        # Use map() instead of applymap() for pandas 2.0+ compatibility
        df = df.map(lambda x: str(x).strip() if x is not None else '')
        df = df.reset_index(drop=True)
        return df

    def _calculate_confidence(
        self,
        df: pd.DataFrame,
        raw_data: List[List]
    ) -> float:
        """
        Calculate confidence score based on table detection quality.

        Factors considered:
        - Cell fill rate: percentage of non-empty cells
        - Structure regularity: consistency of row lengths
        - Numeric content: presence of numeric data (indicates structured data)

        Args:
            df: Cleaned DataFrame.
            raw_data: Raw table data from pdfplumber.

        Returns:
            Confidence score from 0.0 to 1.0.
        """
        if df.empty:
            return 0.0

        # Factor 1: Cell fill rate (non-empty cells / total cells)
        total_cells = df.size
        non_empty_cells = (df != '').sum().sum()
        fill_rate = non_empty_cells / total_cells if total_cells > 0 else 0.0

        # Factor 2: Structure regularity (consistent row lengths)
        if raw_data:
            row_lengths = [len(row) for row in raw_data if row]
            if row_lengths:
                max_len = max(row_lengths)
                min_len = min(row_lengths)
                regularity = min_len / max_len if max_len > 0 else 0.0
            else:
                regularity = 0.0
        else:
            regularity = 1.0

        # Factor 3: Numeric content presence (indicates structured data)
        numeric_count = 0
        for col in df.columns:
            # Count cells that contain numeric content
            numeric_count += df[col].apply(self._has_numeric_content).sum()
        numeric_ratio = numeric_count / total_cells if total_cells > 0 else 0.0

        # Weighted combination of factors
        # Fill rate is most important, followed by structure, then numeric content
        confidence = (
            0.5 * fill_rate +
            0.3 * regularity +
            0.2 * min(numeric_ratio * 2, 1.0)  # Boost numeric ratio, cap at 1.0
        )

        return round(confidence, 3)

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
        table_index: int,
        page_num: int,
        bbox: Optional[tuple],
        page
    ) -> dict:
        """
        Build metadata dictionary.

        Args:
            table_index: Index of this table on the page.
            page_num: Page number (1-indexed).
            bbox: Optional bounding box of the table.
            page: pdfplumber Page object.

        Returns:
            Metadata dictionary.
        """
        metadata = {
            'table_index': table_index,
            'page_num': page_num,
            'extractor_settings': {
                'vertical_strategy': self._vertical_strategy,
                'horizontal_strategy': self._horizontal_strategy,
            }
        }

        if bbox:
            x1, y1, x2, y2 = bbox
            metadata['bounding_box'] = {
                'x1': x1,
                'y1': y1,
                'x2': x2,
                'y2': y2
            }

        # Add page dimensions
        if page:
            metadata['page_dimensions'] = {
                'width': page.width,
                'height': page.height
            }

        return metadata
