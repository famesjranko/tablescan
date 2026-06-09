"""
docling_extractor.py
    Docling (IBM) based table extraction backend.

    Wraps IBM's Docling DocumentConverter and its TableFormer structure model
    for high-accuracy table extraction. Mirrors the region-aware workflow of
    vision_extractor.py: each requested table_area is cropped to its own
    single-page PDF and run through Docling, which preserves the manual-
    selection and YOLO-review pipelines.

    Docling is opt-in (disabled by default in MultiExtractor) because the
    model is heavier than the text-based backends. The DocumentConverter is
    expensive to construct, so it is built once and cached as a lazy singleton
    keyed by pipeline configuration.
"""

import logging
import os
import tempfile
from typing import List, Optional

import fitz
import pandas as pd

from .base import BaseExtractor, ExtractionResult

logger = logging.getLogger(__name__)


# Lazy singleton cache of DocumentConverter instances, keyed by pipeline
# configuration. Building a converter loads the layout + TableFormer models,
# so we never want to do it per extract() call.
_CONVERTER_CACHE: dict = {}


def _build_converter(table_mode: str, do_ocr: bool, artifacts_path: Optional[str]):
    """
    Construct a Docling DocumentConverter for the given pipeline options.

    Imports docling lazily so the rest of the extractor module (and the
    MultiExtractor registration / toggle) works even when docling is not
    installed. Only this function requires the dependency.

    Args:
        table_mode: 'accurate' (TableFormerMode.ACCURATE) or 'fast'.
        do_ocr: Whether to run OCR. Off by default - cropped region PDFs keep
            their text layer, so OCR is unnecessary for born-digital PDFs.
        artifacts_path: Path to pre-downloaded model weights, or None to let
            Docling resolve/download them.

    Returns:
        A configured docling DocumentConverter.

    Raises:
        ImportError: If docling is not installed.
    """
    try:
        from docling.datamodel.base_models import InputFormat
        from docling.datamodel.pipeline_options import (
            PdfPipelineOptions,
            TableFormerMode,
        )
        from docling.document_converter import DocumentConverter, PdfFormatOption
    except ImportError as e:
        raise ImportError(
            "docling is required for DoclingExtractor. "
            "Install it with: pip install docling"
        ) from e

    if artifacts_path:
        pipeline_options = PdfPipelineOptions(artifacts_path=artifacts_path)
    else:
        pipeline_options = PdfPipelineOptions()

    pipeline_options.do_table_structure = True
    pipeline_options.do_ocr = do_ocr
    pipeline_options.table_structure_options.do_cell_matching = True
    pipeline_options.table_structure_options.mode = (
        TableFormerMode.ACCURATE if table_mode == 'accurate' else TableFormerMode.FAST
    )

    # Configure both PDF and image inputs with the same options so the
    # converter works regardless of how a region is cropped.
    format_options = {
        InputFormat.PDF: PdfFormatOption(pipeline_options=pipeline_options),
    }
    try:
        format_options[InputFormat.IMAGE] = PdfFormatOption(
            pipeline_options=pipeline_options
        )
    except Exception:
        # Older docling builds may not accept IMAGE here; PDF cropping is the
        # primary path, so this is non-fatal.
        pass

    logger.info(
        "[docling] Building DocumentConverter "
        f"(table_mode={table_mode}, do_ocr={do_ocr}, "
        f"artifacts_path={artifacts_path or 'auto'})"
    )
    return DocumentConverter(format_options=format_options)


def _table_to_dataframe(table, document) -> Optional[pd.DataFrame]:
    """
    Export a Docling table item to a pandas DataFrame across API versions.

    Newer docling expects the owning document to be passed
    (table.export_to_dataframe(doc=document)); older releases take no
    argument. Try the newer signature first, then fall back.

    Args:
        table: A docling TableItem.
        document: The owning DoclingDocument.

    Returns:
        The exported DataFrame, or None on failure.
    """
    try:
        return table.export_to_dataframe(doc=document)
    except TypeError:
        try:
            return table.export_to_dataframe()
        except Exception:
            return None
    except Exception:
        return None


class DoclingExtractor(BaseExtractor):
    """
    Table extractor using IBM Docling's DocumentConverter + TableFormer.

    Docling benchmarks well above the classic line/whitespace backends on
    complex tables. For each requested region it crops a single-page PDF
    (preserving the text layer to avoid OCR on born-digital PDFs) and runs
    Docling's table-structure pipeline, returning one ExtractionResult per
    detected table.

    Attributes:
        table_mode: TableFormer mode, 'accurate' (default) or 'fast'.
        do_ocr: Whether to enable OCR (default False).
        artifacts_path: Path to pre-downloaded model weights. Falls back to
            the DOCLING_ARTIFACTS_PATH environment variable, then to Docling's
            default resolution.
    """

    def __init__(
        self,
        table_mode: str = 'accurate',
        do_ocr: bool = False,
        artifacts_path: Optional[str] = None,
    ):
        """
        Initialize DoclingExtractor.

        Note: this does NOT import docling or load any models. The converter
        is built lazily on first extract() call so the extractor can be
        registered and toggled without the dependency present.

        Args:
            table_mode: 'accurate' or 'fast'. Defaults to 'accurate'.
            do_ocr: Enable OCR. Defaults to False (region PDFs keep text).
            artifacts_path: Optional path to pre-downloaded model weights.

        Raises:
            ValueError: If table_mode is not 'accurate' or 'fast'.
        """
        valid_modes = ('accurate', 'fast')
        if table_mode not in valid_modes:
            raise ValueError(
                f"table_mode must be one of {valid_modes}, got '{table_mode}'"
            )

        self._table_mode = table_mode
        self._do_ocr = do_ocr
        self._artifacts_path = (
            artifacts_path
            or os.environ.get('DOCLING_ARTIFACTS_PATH')
            or None
        )

    @property
    def name(self) -> str:
        """Return the unique name of this extractor."""
        return "docling"

    def _get_converter(self):
        """Return the cached DocumentConverter for this config, building once."""
        key = (self._table_mode, self._do_ocr, self._artifacts_path)
        converter = _CONVERTER_CACHE.get(key)
        if converter is None:
            converter = _build_converter(
                self._table_mode, self._do_ocr, self._artifacts_path
            )
            _CONVERTER_CACHE[key] = converter
        return converter

    def extract(
        self,
        pdf_path: str,
        page_num: int,
        table_areas: Optional[List[tuple]] = None
    ) -> List[ExtractionResult]:
        """
        Extract tables from a PDF page using Docling.

        Args:
            pdf_path: Path to the PDF file.
            page_num: Page number to extract from (1-indexed).
            table_areas: List of bounding boxes [(x1, y1, x2, y2), ...] in PDF
                coordinates (origin bottom-left). Required by the pipeline; if
                None/empty a warning is logged and an empty list returned.

        Returns:
            List of ExtractionResult, one per detected table. Empty list if no
            tables found or table_areas not provided.

        Raises:
            FileNotFoundError: If PDF file doesn't exist.
            ValueError: If page_num is out of range.
        """
        if not os.path.isfile(pdf_path):
            raise FileNotFoundError(f"PDF file not found: {pdf_path}")

        results: List[ExtractionResult] = []

        try:
            with fitz.open(pdf_path) as doc:
                if page_num < 1 or page_num > len(doc):
                    raise ValueError(
                        f"Page {page_num} is out of range for {pdf_path} "
                        f"(has {len(doc)} pages)"
                    )

                if not table_areas:
                    logger.warning(
                        f"[{self.name}] No table_areas provided - pipeline error, skipping"
                    )
                    return []

                # Build (or reuse) the converter once before looping regions.
                converter = self._get_converter()

                for i, (x1, y1, x2, y2) in enumerate(table_areas):
                    region_results = self._extract_from_region(
                        doc, page_num, x1, y1, x2, y2, i, converter
                    )
                    results.extend(region_results)

        except (ValueError, FileNotFoundError):
            raise
        except ImportError:
            # docling not installed - surface as a clean failure to the caller
            raise
        except Exception as e:
            logger.warning(f"[{self.name}] Extraction failed for page {page_num}: {e}")
            return []

        return results

    def _extract_from_region(
        self,
        src_doc: fitz.Document,
        page_num: int,
        x1: float,
        y1: float,
        x2: float,
        y2: float,
        region_index: int,
        converter,
    ) -> List[ExtractionResult]:
        """
        Crop a region to its own single-page PDF and run Docling on it.

        Cropping with show_pdf_page preserves the source text layer (vector
        content), so born-digital PDFs are extracted without OCR.

        Args:
            src_doc: Open source fitz Document.
            page_num: Page number (1-indexed).
            x1, y1, x2, y2: Bounding box in PDF coordinates (bottom-left origin).
            region_index: Index of this region.
            converter: A docling DocumentConverter.

        Returns:
            List of ExtractionResult from this region.
        """
        results: List[ExtractionResult] = []

        page = src_doc[page_num - 1]
        page_height = page.rect.height

        # Convert PDF coordinates (origin bottom-left, Y up) to PyMuPDF
        # coordinates (origin top-left, Y down), mirroring PyMuPDFExtractor.
        mupdf_y0 = page_height - y1
        mupdf_y1 = page_height - y2
        if mupdf_y0 > mupdf_y1:
            mupdf_y0, mupdf_y1 = mupdf_y1, mupdf_y0

        # Pad slightly so table borders are not clipped, then clamp to page.
        padding = 5
        clip = fitz.Rect(
            max(page.rect.x0, x1 - padding),
            max(page.rect.y0, mupdf_y0 - padding),
            min(page.rect.x1, x2 + padding),
            min(page.rect.y1, mupdf_y1 + padding),
        )

        if clip.width <= 0 or clip.height <= 0:
            logger.warning(
                f"[{self.name}] Region {region_index} has invalid clip, skipping"
            )
            return results

        tmp_path = None
        out_doc = None
        try:
            out_doc = fitz.open()
            new_page = out_doc.new_page(width=clip.width, height=clip.height)
            new_page.show_pdf_page(new_page.rect, src_doc, page_num - 1, clip=clip)

            with tempfile.NamedTemporaryFile(suffix='.pdf', delete=False) as tmp:
                tmp_path = tmp.name
            out_doc.save(tmp_path)
            out_doc.close()
            out_doc = None

            conv_result = converter.convert(tmp_path)
            document = conv_result.document
            tables = getattr(document, 'tables', None) or []

            for j, table in enumerate(tables):
                result = self._process_table(
                    table,
                    document,
                    table_index=region_index * 100 + j,
                    page_num=page_num,
                    original_bbox=(x1, y1, x2, y2),
                )
                if result:
                    results.append(result)

        except Exception as e:
            logger.warning(
                f"[{self.name}] Region {region_index} extraction failed: {e}"
            )
        finally:
            if out_doc is not None:
                try:
                    out_doc.close()
                except Exception:
                    pass
            if tmp_path:
                try:
                    os.unlink(tmp_path)
                except Exception:
                    pass

        return results

    def _process_table(
        self,
        table,
        document,
        table_index: int,
        page_num: int,
        original_bbox: tuple,
    ) -> Optional[ExtractionResult]:
        """
        Process a Docling table item into an ExtractionResult.

        Args:
            table: Docling TableItem.
            document: The owning DoclingDocument.
            table_index: Index of this table.
            page_num: Page number (1-indexed).
            original_bbox: Original bounding box in PDF coordinates.

        Returns:
            ExtractionResult or None if table is invalid.
        """
        try:
            df = _table_to_dataframe(table, document)

            if df is None or df.empty:
                return None

            if not self._is_valid_table(df):
                return None

            df = self._clean_dataframe(df)
            confidence = self._calculate_confidence(df)
            metadata = self._build_metadata(df, table_index, page_num, original_bbox)

            return ExtractionResult(
                dataframe=df,
                confidence=confidence,
                method=self.name,
                metadata=metadata,
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
            df: Raw DataFrame from Docling.

        Returns:
            Cleaned DataFrame.
        """
        df = df.copy()
        df = df.fillna('')
        df = df.map(lambda x: str(x).strip() if x is not None else '')
        df = df.reset_index(drop=True)
        return df

    def _calculate_confidence(self, df: pd.DataFrame) -> float:
        """
        Calculate a confidence score based on table quality.

        Docling's TableFormer is strong, so this leans on structural signals:
        cell fill rate, numeric content presence, and a size bonus.

        Args:
            df: Cleaned DataFrame.

        Returns:
            Confidence score from 0.0 to 1.0.
        """
        if df.empty:
            return 0.0

        # Factor 1: Cell fill rate
        total_cells = df.size
        non_empty_cells = (df != '').sum().sum()
        fill_rate = non_empty_cells / total_cells if total_cells > 0 else 0.0

        # Factor 2: Structure regularity (Docling tables are always rectangular)
        regularity = 1.0

        # Factor 3: Numeric content presence
        numeric_count = 0
        for col in df.columns:
            numeric_count += df[col].apply(self._has_numeric_content).sum()
        numeric_ratio = numeric_count / total_cells if total_cells > 0 else 0.0

        # Factor 4: Size bonus (larger tables more likely to be real)
        rows, cols = df.shape
        size_bonus = min((rows * cols) / 20, 0.2)

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
        df: pd.DataFrame,
        table_index: int,
        page_num: int,
        original_bbox: tuple,
    ) -> dict:
        """
        Build metadata dictionary.

        Args:
            df: Cleaned DataFrame.
            table_index: Index of this table.
            page_num: Page number (1-indexed).
            original_bbox: Original bounding box in PDF coordinates.

        Returns:
            Metadata dictionary.
        """
        x1, y1, x2, y2 = original_bbox

        return {
            'table_index': table_index,
            'page_num': page_num,
            'bounding_box': {
                'x1': x1,
                'y1': y1,
                'x2': x2,
                'y2': y2,
            },
            'extractor_settings': {
                'table_mode': self._table_mode,
                'do_ocr': self._do_ocr,
            },
            'table_dimensions': {
                'rows': len(df),
                'cols': len(df.columns),
            },
        }
