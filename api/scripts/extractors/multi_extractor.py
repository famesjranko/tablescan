"""
multi_extractor.py
    Multi-extractor pipeline for running multiple extraction backends
    and selecting the best result using scoring.

    Provides a unified interface for running Camelot, pdfplumber, and
    vision extractors with automatic best-result selection.
"""

import logging
from typing import Any, Callable, Dict, List, Optional, Tuple

from .base import ExtractionResult
from .camelot_extractor import CamelotExtractor
from .pdfplumber_extractor import PdfplumberExtractor
from .pymupdf_extractor import PyMuPDFExtractor
from .vision_extractor import VisionExtractor
from .scorer import ExtractionScorer


logger = logging.getLogger(__name__)


class MultiExtractor:
    """
    Runs multiple extraction backends and selects the best result.

    For born-digital PDFs, runs Camelot (lattice + stream), pdfplumber
    (default + explicit), and vision extractors, then uses ExtractionScorer
    to select the highest-quality result for each table.

    Attributes:
        scorer: ExtractionScorer instance for comparing results.
        extractors: List of extractor instances to run.
    """

    def __init__(self, enabled_libraries: dict = None):
        """
        Initialize MultiExtractor with extractors based on enabled libraries.

        Args:
            enabled_libraries: Dict of library toggles. Keys:
                - 'camelot': Enable Camelot lattice + stream extractors
                - 'pdfplumber': Enable pdfplumber lines + text extractors
                - 'pymupdf': Enable PyMuPDF lines + text extractors
                - 'vision': Enable img2table vision extractor
                All default to True if not specified.
        """
        if enabled_libraries is None:
            enabled_libraries = {'camelot': True, 'pdfplumber': True, 'pymupdf': True, 'vision': True}

        self._scorer = ExtractionScorer()
        self._extractors = []

        # - camelot_lattice: For tables with visible borders/gridlines
        # - camelot_stream: For borderless tables (whitespace analysis)
        if enabled_libraries.get('camelot', True):
            self._extractors.extend([
                CamelotExtractor(flavor='lattice'),
                CamelotExtractor(flavor='stream'),
            ])

        # - pdfplumber: Default 'lines' strategy (requires visible lines)
        # - pdfplumber_text: 'text' strategy for borderless tables (text alignment)
        if enabled_libraries.get('pdfplumber', True):
            self._extractors.extend([
                PdfplumberExtractor(),
                PdfplumberExtractor(
                    vertical_strategy='text',
                    horizontal_strategy='text'
                ),
            ])

        # - pymupdf: PyMuPDF 'lines' strategy (different algorithm than pdfplumber)
        # - pymupdf_text: PyMuPDF 'text' strategy for borderless tables
        if enabled_libraries.get('pymupdf', True):
            self._extractors.extend([
                PyMuPDFExtractor(strategy='lines'),
                PyMuPDFExtractor(strategy='text'),
            ])

        # - img2table: Vision-based extraction
        if enabled_libraries.get('vision', True):
            self._extractors.append(VisionExtractor())

        logger.info(f"[MultiExtractor] enabled_libraries={enabled_libraries}, extractors={self.extractor_names}")

    @property
    def extractor_names(self) -> List[str]:
        """Return list of extractor names being used."""
        return [ext.name for ext in self._extractors]

    def extract_all_with_scores(
        self,
        pdf_path: str,
        page_num: int,
        table_areas: Optional[list] = None,
        progress_callback: Optional[Callable[[str, int, int], None]] = None
    ) -> List[Dict[str, Any]]:
        """
        Run all extractors and return all results with scores and warnings.

        Unlike extract_best which returns only the best result, this method
        returns ALL extraction results from ALL extractors, each scored and
        annotated with quality warnings. This allows users to compare and
        select their preferred extraction method.

        Args:
            pdf_path: Path to the PDF file.
            page_num: Page number to extract from (1-indexed).
            table_areas: Optional list of bounding boxes.
            progress_callback: Optional callback(method_name, current_idx, total)
                called before each extractor runs, for progress reporting.

        Returns:
            List of result dictionaries sorted by score descending. Each dict:
            {
                'method': str,          # Extractor name
                'score': float,         # Quality score 0-1
                'confidence': float,    # Extractor's confidence
                'rows': int,            # Number of rows
                'cols': int,            # Number of columns
                'warnings': List[str],  # Quality warnings
                'dataframe': DataFrame, # Extracted data
                'metadata': dict,       # Extraction metadata
                'error': str,           # (only if extraction failed)
            }
        """
        results = []
        total_extractors = len(self._extractors)

        for i, extractor in enumerate(self._extractors):
            if progress_callback:
                progress_callback(extractor.name, i + 1, total_extractors)

            try:
                extractions = extractor.extract(pdf_path, page_num, table_areas)

                if not extractions:
                    # Extractor found no tables
                    logger.info(f"[MultiExtractor] {extractor.name}: no tables found")
                    results.append({
                        'method': extractor.name,
                        'score': 0,
                        'confidence': 0,
                        'rows': 0,
                        'cols': 0,
                        'warnings': ['No tables found'],
                        'dataframe': None,
                        'metadata': {},
                    })
                    continue

                for ext in extractions:
                    # Score RAW extraction - don't process headers here
                    # Header processing happens later for final display/export
                    score = self._scorer.score(ext)
                    warnings = self._scorer.generate_warnings(ext)

                    results.append({
                        'method': ext.method,
                        'score': score,
                        'confidence': ext.confidence,
                        'rows': len(ext.dataframe),
                        'cols': len(ext.dataframe.columns),
                        'warnings': warnings,
                        'dataframe': ext.dataframe,
                        'metadata': ext.metadata,
                    })

                logger.info(
                    f"[MultiExtractor] {extractor.name}: scored {len(extractions)} table(s)"
                )

            except Exception as e:
                logger.warning(
                    f"[MultiExtractor] {extractor.name} failed: {e}"
                )
                results.append({
                    'method': extractor.name,
                    'score': 0,
                    'confidence': 0,
                    'rows': 0,
                    'cols': 0,
                    'warnings': [],
                    'dataframe': None,
                    'metadata': {},
                    'error': str(e),
                })

        # Sort by score descending
        results.sort(key=lambda r: r.get('score', 0), reverse=True)

        return results

    def extract_all(
        self,
        pdf_path: str,
        page_num: int,
        table_areas: Optional[list] = None
    ) -> List[Tuple[str, List[ExtractionResult]]]:
        """
        Run all extractors and return results grouped by extractor.

        Args:
            pdf_path: Path to the PDF file.
            page_num: Page number to extract from (1-indexed).
            table_areas: Optional list of bounding boxes.

        Returns:
            List of (extractor_name, results) tuples.
            Each extractor may return multiple ExtractionResult (one per table).
            Extractors that fail return empty lists.
        """
        all_results = []

        for extractor in self._extractors:
            try:
                results = extractor.extract(pdf_path, page_num, table_areas)
                all_results.append((extractor.name, results))
                logger.info(
                    f"[MultiExtractor] {extractor.name}: found {len(results)} table(s)"
                )
            except Exception as e:
                # Graceful fallback - log error and continue with other extractors
                logger.warning(
                    f"[MultiExtractor] {extractor.name} failed: {e}"
                )
                all_results.append((extractor.name, []))

        return all_results

    def extract_best(
        self,
        pdf_path: str,
        page_num: int,
        table_areas: Optional[list] = None
    ) -> List[ExtractionResult]:
        """
        Run all extractors and return the best result for each table region.

        For each table found, compares results from all extractors and
        returns the highest-scoring one based on ExtractionScorer.

        Args:
            pdf_path: Path to the PDF file.
            page_num: Page number to extract from (1-indexed).
            table_areas: Optional list of bounding boxes.

        Returns:
            List of best ExtractionResult for each table found.
            Returns empty list if no tables found by any extractor.
        """
        # Run all extractors
        all_results = self.extract_all(pdf_path, page_num, table_areas)

        # Collect all non-empty results
        candidate_results: List[ExtractionResult] = []
        for extractor_name, results in all_results:
            candidate_results.extend(results)

        if not candidate_results:
            logger.info("[MultiExtractor] No tables found by any extractor")
            return []

        # Group results by approximate table position/index
        # For now, simply select best from all candidates
        # Future: could match tables by bounding box overlap

        # If only one result, return it
        if len(candidate_results) == 1:
            best = candidate_results[0]
            logger.info(
                f"[MultiExtractor] Single result from {best.method}, "
                f"confidence={best.confidence:.3f}"
            )
            return [best]

        # Multiple results - need to select best
        # Group by approximate table count (assume extractors find similar tables)
        # For simplicity: score all and pick top N where N = max tables found by any extractor
        max_tables = max(
            len(results) for _, results in all_results if results
        )

        # Score all results
        scored_results = self._scorer.score_all(candidate_results)

        # Take top N results (one per table slot)
        best_results = []
        for result, score in scored_results[:max_tables]:
            logger.info(
                f"[MultiExtractor] Selected {result.method} "
                f"(score={score:.4f}, confidence={result.confidence:.3f})"
            )
            best_results.append(result)

        return best_results

    def extract_with_comparison(
        self,
        pdf_path: str,
        page_num: int,
        table_areas: Optional[list] = None
    ) -> Tuple[List[ExtractionResult], dict]:
        """
        Run all extractors and return best results with comparison metadata.

        Similar to extract_best() but also returns metadata about
        what each extractor found and why the winner was selected.

        Args:
            pdf_path: Path to the PDF file.
            page_num: Page number to extract from (1-indexed).
            table_areas: Optional list of bounding boxes.

        Returns:
            Tuple of (best_results, comparison_metadata).
            comparison_metadata contains extractor stats and scores.
        """
        # Run all extractors
        all_results = self.extract_all(pdf_path, page_num, table_areas)

        # Build comparison metadata
        comparison = {
            'extractors_run': [],
            'total_candidates': 0,
            'selected_methods': [],
        }

        candidate_results: List[ExtractionResult] = []
        for extractor_name, results in all_results:
            extractor_info = {
                'name': extractor_name,
                'tables_found': len(results),
                'scores': [],
            }

            for result in results:
                score = self._scorer.score(result)
                extractor_info['scores'].append({
                    'confidence': result.confidence,
                    'computed_score': score,
                })
                candidate_results.append(result)

            comparison['extractors_run'].append(extractor_info)
            comparison['total_candidates'] += len(results)

        if not candidate_results:
            return [], comparison

        # Select best results
        max_tables = max(
            len(results) for _, results in all_results if results
        )

        scored_results = self._scorer.score_all(candidate_results)
        best_results = []

        for result, score in scored_results[:max_tables]:
            comparison['selected_methods'].append({
                'method': result.method,
                'score': score,
                'confidence': result.confidence,
            })
            best_results.append(result)

        return best_results, comparison
