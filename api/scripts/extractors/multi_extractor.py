"""
multi_extractor.py
    Multi-extractor pipeline for running multiple extraction backends
    and selecting the best result using scoring.

    Provides a unified interface for running Camelot and pdfplumber
    extractors in parallel with automatic best-result selection.
"""

import logging
from typing import List, Optional, Tuple

from .base import ExtractionResult
from .camelot_extractor import CamelotExtractor
from .pdfplumber_extractor import PdfplumberExtractor
from .scorer import ExtractionScorer


logger = logging.getLogger(__name__)


class MultiExtractor:
    """
    Runs multiple extraction backends and selects the best result.

    For born-digital PDFs, runs both Camelot (lattice + stream) and
    pdfplumber extractors, then uses ExtractionScorer to select
    the highest-quality result for each table.

    Attributes:
        scorer: ExtractionScorer instance for comparing results.
        extractors: List of extractor instances to run.
    """

    def __init__(self):
        """Initialize MultiExtractor with default extractors and scorer."""
        self._scorer = ExtractionScorer()

        # Initialize extractors
        self._extractors = [
            CamelotExtractor(flavor='lattice'),
            CamelotExtractor(flavor='stream'),
            PdfplumberExtractor(),
        ]

    @property
    def extractor_names(self) -> List[str]:
        """Return list of extractor names being used."""
        return [ext.name for ext in self._extractors]

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
