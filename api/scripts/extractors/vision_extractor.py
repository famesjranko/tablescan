"""
vision_extractor.py
    Vision-based table extraction using img2table.

    Wraps img2table library for detecting and extracting tables
    from image-based (scanned) PDF pages. Works on CPU without GPU.
"""

import logging
import os
import tempfile
from typing import List, Optional

import pandas as pd
from pdf2image import convert_from_path
from PIL import Image

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
            # table_areas is required - we always extract from specific regions
            if not table_areas:
                logger.warning(f"[{self.name}] No table_areas provided - pipeline error, skipping")
                return []

            # Initialize OCR (Tesseract for CPU-based extraction)
            ocr = None
            try:
                ocr = TesseractOCR(n_threads=1, lang="eng")
            except Exception:
                # Tesseract not available, continue without OCR
                pass

            # Extract from specific regions by cropping images
            results = self._extract_from_regions(
                pdf_path, page_num, table_areas, ocr
            )

        except ValueError:
            # Re-raise ValueError for page out of range
            raise
        except Exception as e:
            # Return empty list for other extraction failures
            logger.warning(f"[img2table] Extraction failed for page {page_num}: {e}")
            return []

        return results

    def _extract_from_regions(
        self,
        pdf_path: str,
        page_num: int,
        table_areas: List[tuple],
        ocr
    ) -> List[ExtractionResult]:
        """
        Extract tables from specific regions by cropping the page image.

        Converts PDF page to image, crops to each region, and runs
        img2table on the cropped images for more accurate extraction.

        Args:
            pdf_path: Path to PDF file.
            page_num: Page number (1-indexed).
            table_areas: List of bounding boxes in PDF coords [(x1, y1, x2, y2), ...].
            ocr: TesseractOCR instance or None.

        Returns:
            List of ExtractionResult from all regions.
        """
        from img2table.document import Image as Img2TableImage

        results = []

        # Convert PDF page to image (300 DPI for good quality)
        images = convert_from_path(
            pdf_path,
            first_page=page_num,
            last_page=page_num,
            dpi=300
        )

        if not images:
            return results

        page_image = images[0]
        img_width, img_height = page_image.size

        # Get PDF page dimensions for coordinate conversion
        # PDF coordinates: origin bottom-left, units in points (1/72 inch)
        # Image coordinates: origin top-left, units in pixels
        import fitz
        with fitz.open(pdf_path) as pdf_doc:
            pdf_page = pdf_doc[page_num - 1]
            pdf_width = pdf_page.rect.width
            pdf_height = pdf_page.rect.height

        # Scale factors
        scale_x = img_width / pdf_width
        scale_y = img_height / pdf_height

        for i, (x1, y1, x2, y2) in enumerate(table_areas):
            try:
                # Convert PDF coords to image pixels
                # PDF: y1 is top (higher value), y2 is bottom (lower value)
                # Image: y=0 is top, y increases downward
                img_x1 = int(x1 * scale_x)
                img_x2 = int(x2 * scale_x)
                # Flip Y: PDF y1 (top) -> image top, PDF y2 (bottom) -> image bottom
                img_y1 = int((pdf_height - y1) * scale_y)  # PDF top -> image top
                img_y2 = int((pdf_height - y2) * scale_y)  # PDF bottom -> image bottom

                # Ensure correct ordering (img_y1 should be smaller for PIL crop)
                if img_y1 > img_y2:
                    img_y1, img_y2 = img_y2, img_y1

                # Add small padding (5 pixels) to avoid cutting off edges
                padding = 5
                img_x1 = max(0, img_x1 - padding)
                img_y1 = max(0, img_y1 - padding)
                img_x2 = min(img_width, img_x2 + padding)
                img_y2 = min(img_height, img_y2 + padding)

                # Crop image to region
                cropped = page_image.crop((img_x1, img_y1, img_x2, img_y2))

                # Save cropped image temporarily and run img2table
                with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as tmp:
                    cropped.save(tmp.name, 'PNG')
                    tmp_path = tmp.name

                try:
                    doc = Img2TableImage(tmp_path)
                    extracted_tables = doc.extract_tables(
                        ocr=ocr,
                        implicit_rows=self._implicit_rows,
                        borderless_tables=self._borderless_tables,
                        min_confidence=int(self._min_confidence * 100)
                    )

                    # img2table.Image returns list directly, not dict
                    for j, table in enumerate(extracted_tables):
                        result = self._process_table(table, i * 100 + j, page_num)
                        if result:
                            # Update bbox to reflect original PDF coordinates
                            if result.metadata.get('bounding_box'):
                                result.metadata['bounding_box'] = {
                                    'x1': x1, 'y1': y1, 'x2': x2, 'y2': y2
                                }
                            results.append(result)

                finally:
                    # Clean up temp file
                    try:
                        os.unlink(tmp_path)
                    except Exception:
                        pass

            except Exception as e:
                logger.warning(f"[img2table] Region {i} extraction failed: {e}")
                continue

        return results

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
