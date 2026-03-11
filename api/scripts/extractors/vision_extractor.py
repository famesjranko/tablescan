"""
vision_extractor.py
    Vision-based table extraction using img2table.

    Wraps img2table library for detecting and extracting tables
    from image-based (scanned) PDF pages. Works on CPU without GPU.
"""

import logging
import os
from typing import List, Optional

import pandas as pd

from .base import BaseExtractor, ExtractionResult

logger = logging.getLogger(__name__)


class VisionExtractor(BaseExtractor):
    """
    Table extractor using img2table library.

    img2table uses computer vision algorithms to detect tables in images
    and PDFs. It's particularly effective for scanned PDFs where text-based
    extractors struggle. Operates entirely on CPU.

    Attributes:
        implicit_rows: Whether to detect implicit rows (rows without explicit lines).
        borderless_tables: Whether to detect borderless tables.
        min_confidence: Minimum confidence threshold for table detection.
    """

    def __init__(
        self,
        implicit_rows: bool = True,
        borderless_tables: bool = True,
        min_confidence: float = 0.5
    ):
        """
        Initialize VisionExtractor.

        Args:
            implicit_rows: Enable detection of implicit rows (default True).
            borderless_tables: Enable detection of borderless tables (default True).
            min_confidence: Minimum confidence for keeping detected tables (0.0-1.0).
        """
        self._implicit_rows = implicit_rows
        self._borderless_tables = borderless_tables
        self._min_confidence = min_confidence

    @property
    def name(self) -> str:
        """Return the unique name of this extractor."""
        return "img2table"

    def extract(
        self,
        pdf_path: str,
        page_num: int,
        table_areas: Optional[List[tuple]] = None
    ) -> List[ExtractionResult]:
        """
        Extract tables from a PDF page using img2table vision detection.

        Args:
            pdf_path: Path to the PDF file.
            page_num: Page number to extract from (1-indexed for consistency).
            table_areas: Optional list of bounding boxes [(x1, y1, x2, y2), ...].
                         Note: img2table auto-detects tables, so this is used
                         only for filtering results to specific regions.

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

        # Lazy import to avoid loading img2table unless needed
        try:
            from img2table.document import PDF
            from img2table.ocr import TesseractOCR
        except ImportError as e:
            raise ImportError(
                "img2table is required for VisionExtractor. "
                "Install it with: pip install img2table"
            ) from e

        results = []

        try:
            # Initialize PDF document with img2table
            # pages parameter is 0-indexed in img2table
            doc = PDF(pdf_path, pages=[page_num - 1])

            # Initialize OCR (Tesseract for CPU-based extraction)
            # OCR is optional - can be None if only detection is needed
            ocr = None
            try:
                ocr = TesseractOCR(n_threads=1, lang="eng")
            except Exception:
                # Tesseract not available, continue without OCR
                # img2table can still detect tables, just won't extract text
                pass

            # Extract tables
            extracted_tables = doc.extract_tables(
                ocr=ocr,
                implicit_rows=self._implicit_rows,
                borderless_tables=self._borderless_tables,
                min_confidence=int(self._min_confidence * 100)  # img2table uses 0-100
            )

            # Get tables for the requested page (0-indexed in result)
            page_tables = extracted_tables.get(page_num - 1, [])

            for i, table in enumerate(page_tables):
                # Filter by table_areas if provided
                if table_areas and not self._table_in_areas(table, table_areas):
                    continue

                result = self._process_table(table, i, page_num)
                if result:
                    results.append(result)

        except ValueError:
            # Re-raise ValueError for page out of range
            raise
        except Exception as e:
            # Return empty list for other extraction failures
            # Log at DEBUG level for troubleshooting (MultiExtractor logs at INFO/WARNING)
            logger.debug(f"[VisionExtractor] Extraction failed for {pdf_path} page {page_num}: {e}")
            return []

        return results

    def _table_in_areas(self, table, areas: List[tuple]) -> bool:
        """
        Check if table overlaps with any of the specified areas.

        Args:
            table: img2table ExtractedTable object.
            areas: List of bounding boxes [(x1, y1, x2, y2), ...].

        Returns:
            True if table overlaps with any area, False otherwise.
        """
        try:
            # Get table bounding box
            bbox = table.bbox
            if not bbox:
                return True  # If no bbox, include table

            tx1, ty1, tx2, ty2 = bbox.x1, bbox.y1, bbox.x2, bbox.y2

            for (ax1, ay1, ax2, ay2) in areas:
                # Check for overlap
                if not (tx2 < ax1 or tx1 > ax2 or ty2 < ay1 or ty1 > ay2):
                    return True
            return False
        except Exception:
            # On error, include the table
            return True

    def _process_table(
        self,
        table,
        table_index: int,
        page_num: int
    ) -> Optional[ExtractionResult]:
        """
        Process an img2table ExtractedTable into ExtractionResult.

        Args:
            table: img2table ExtractedTable object.
            table_index: Index of this table on the page.
            page_num: Page number (1-indexed).

        Returns:
            ExtractionResult or None if table is invalid.
        """
        try:
            # Get DataFrame from table
            df = table.df

            if df is None or df.empty:
                return None

            # Validate table has meaningful content
            if not self._is_valid_table(df):
                return None

            # Clean the dataframe
            df = self._clean_dataframe(df)

            # Calculate confidence score
            confidence = self._calculate_confidence(df, table)

            # Build metadata
            metadata = self._build_metadata(table, table_index, page_num)

            return ExtractionResult(
                dataframe=df,
                confidence=confidence,
                method=self.name,
                metadata=metadata
            )
        except Exception:
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

        - Replaces None values with empty strings
        - Strips whitespace from cells
        - Resets index

        Args:
            df: Raw DataFrame from img2table.

        Returns:
            Cleaned DataFrame.
        """
        df = df.copy()
        # Replace None with empty string
        df = df.fillna('')
        # Convert all cells to string and strip whitespace
        df = df.map(lambda x: str(x).strip() if x is not None else '')
        df = df.reset_index(drop=True)
        return df

    def _calculate_confidence(self, df: pd.DataFrame, table) -> float:
        """
        Calculate confidence score based on table detection quality.

        Factors considered:
        - Table's own confidence score from img2table
        - Cell fill rate: percentage of non-empty cells
        - Structure regularity: consistent dimensions

        Args:
            df: Cleaned DataFrame.
            table: img2table ExtractedTable object.

        Returns:
            Confidence score from 0.0 to 1.0.
        """
        if df.empty:
            return 0.0

        # Factor 1: img2table's confidence (if available)
        try:
            table_confidence = getattr(table, 'confidence', None)
            if table_confidence is not None:
                # img2table uses 0-100 scale
                base_confidence = table_confidence / 100.0
            else:
                base_confidence = 0.7  # Default if not available
        except Exception:
            base_confidence = 0.7

        # Factor 2: Cell fill rate (non-empty cells / total cells)
        total_cells = df.size
        non_empty_cells = (df != '').sum().sum()
        fill_rate = non_empty_cells / total_cells if total_cells > 0 else 0.0

        # Factor 3: Has reasonable dimensions
        rows, cols = df.shape
        dimension_score = 1.0 if (rows >= 2 and cols >= 2) else 0.5

        # Weighted combination
        confidence = (
            0.4 * base_confidence +
            0.4 * fill_rate +
            0.2 * dimension_score
        )

        return round(min(confidence, 1.0), 3)

    def _build_metadata(
        self,
        table,
        table_index: int,
        page_num: int
    ) -> dict:
        """
        Build metadata dictionary.

        Args:
            table: img2table ExtractedTable object.
            table_index: Index of this table on the page.
            page_num: Page number (1-indexed).

        Returns:
            Metadata dictionary.
        """
        metadata = {
            'table_index': table_index,
            'page_num': page_num,
            'extractor_settings': {
                'implicit_rows': self._implicit_rows,
                'borderless_tables': self._borderless_tables,
                'min_confidence': self._min_confidence,
            }
        }

        # Add bounding box if available
        # Convert to Python int to avoid numpy int64 JSON serialization issues
        try:
            bbox = table.bbox
            if bbox:
                metadata['bounding_box'] = {
                    'x1': int(bbox.x1),
                    'y1': int(bbox.y1),
                    'x2': int(bbox.x2),
                    'y2': int(bbox.y2)
                }
        except Exception:
            pass

        # Add title if detected
        try:
            title = getattr(table, 'title', None)
            if title:
                metadata['title'] = title
        except Exception:
            pass

        return metadata
