"""
scorer.py
    Scoring and ranking system for table extraction results.

    Compares extraction results from multiple backends and selects
    the highest-quality output based on cell coverage, structure
    regularity, and numeric integrity metrics.
"""

import re
from typing import List, Optional

import pandas as pd

from .base import ExtractionResult


class ExtractionScorer:
    """
    Scores and ranks table extraction results.

    Evaluates extraction quality using multiple metrics:
    - Extractor confidence: the extractor's own confidence score (most important)
    - Cell coverage: percentage of non-empty cells
    - Structure regularity: consistency of row/column structure
    - Numeric integrity: validity of numeric values
    - Header detection: confidence in header row identification

    All scores are normalized to 0-1 range.

    Attributes:
        confidence_weight: Weight for extractor confidence (default 0.35).
        coverage_weight: Weight for cell coverage score (default 0.20).
        regularity_weight: Weight for structure regularity score (default 0.15).
        numeric_weight: Weight for numeric integrity score (default 0.10).
        header_weight: Weight for header detection score (default 0.20).
    """

    # Regex patterns for numeric detection
    _NUMBER_PATTERN = re.compile(
        r'^[\s$€£¥]?[-+]?[\d,]+\.?\d*%?[\s]?$|'  # Simple numbers with currency/percent
        r'^[\s$€£¥]?\([\d,]+\.?\d*\)[\s]?$|'     # Parenthetical negatives (accounting)
        r'^[-+]?[\d,]+\.?\d*[eE][-+]?\d+$'        # Scientific notation
    )

    def __init__(
        self,
        confidence_weight: float = 0.35,
        coverage_weight: float = 0.20,
        regularity_weight: float = 0.15,
        numeric_weight: float = 0.10,
        header_weight: float = 0.20
    ):
        """
        Initialize ExtractionScorer with custom weights.

        Args:
            confidence_weight: Weight for extractor's own confidence score.
            coverage_weight: Weight for cell coverage score.
            regularity_weight: Weight for structure regularity score.
            numeric_weight: Weight for numeric integrity score.
            header_weight: Weight for header detection score.

        Raises:
            ValueError: If weights don't sum to 1.0 (within tolerance).
        """
        total = confidence_weight + coverage_weight + regularity_weight + numeric_weight + header_weight
        if abs(total - 1.0) > 0.01:
            raise ValueError(f"Weights must sum to 1.0, got {total}")

        self._confidence_weight = confidence_weight
        self._coverage_weight = coverage_weight
        self._regularity_weight = regularity_weight
        self._numeric_weight = numeric_weight
        self._header_weight = header_weight

    def score(
        self,
        result: ExtractionResult,
        page_text: Optional[str] = None
    ) -> float:
        """
        Score extraction quality on 0-1 scale.

        Combines multiple quality metrics using weighted average:
        - coverage_score: % of cells with content
        - regularity_score: consistency of row/column counts
        - numeric_score: parseable numbers are valid
        - header_score: header detection confidence

        Args:
            result: ExtractionResult to score.
            page_text: Optional full page text for coverage comparison.
                       If provided, coverage is measured against page text.
                       If None, coverage is measured as non-empty cell ratio.

        Returns:
            Float score from 0.0 to 1.0.
        """
        df = result.dataframe

        if df.empty:
            return 0.0

        # Calculate individual scores
        confidence = result.confidence if result.confidence is not None else 0.5
        coverage = self._score_coverage(df, page_text)
        regularity = self._score_regularity(df)
        numeric = self._score_numeric_integrity(df)
        header = self._score_header_detection(df, result.metadata)

        # Weighted combination (confidence is most important)
        final_score = (
            self._confidence_weight * confidence +
            self._coverage_weight * coverage +
            self._regularity_weight * regularity +
            self._numeric_weight * numeric +
            self._header_weight * header
        )

        return round(final_score, 4)

    def select_best(
        self,
        results: List[ExtractionResult],
        page_text: Optional[str] = None
    ) -> Optional[ExtractionResult]:
        """
        Return highest-scoring ExtractionResult.

        Args:
            results: List of ExtractionResult to compare.
            page_text: Optional full page text for coverage scoring.

        Returns:
            ExtractionResult with highest score, or None if results is empty.
        """
        if not results:
            return None

        if len(results) == 1:
            return results[0]

        # Score all results and find best
        scored = [(result, self.score(result, page_text)) for result in results]
        scored.sort(key=lambda x: x[1], reverse=True)

        return scored[0][0]

    def score_all(
        self,
        results: List[ExtractionResult],
        page_text: Optional[str] = None
    ) -> List[tuple]:
        """
        Score all results and return sorted list.

        Args:
            results: List of ExtractionResult to score.
            page_text: Optional full page text for coverage scoring.

        Returns:
            List of (ExtractionResult, score) tuples sorted by score descending.
        """
        if not results:
            return []

        scored = [(result, self.score(result, page_text)) for result in results]
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored

    def generate_warnings(
        self,
        result: ExtractionResult,
        page_text: Optional[str] = None
    ) -> List[str]:
        """
        Generate human-readable warnings for extraction quality issues.

        Analyzes the extraction result and returns a list of warnings
        for quality issues that users should be aware of.

        Args:
            result: ExtractionResult to analyze.
            page_text: Optional full page text for coverage comparison.

        Returns:
            List of warning strings. Empty list if no issues.
        """
        warnings = []
        df = result.dataframe

        if df.empty:
            return ["Empty table - no data extracted"]

        # Check cell coverage
        coverage = self._score_coverage(df, page_text)
        if coverage < 0.5:
            warnings.append(f"Low cell coverage ({int(coverage * 100)}%)")
        elif coverage < 0.7:
            warnings.append(f"Moderate cell coverage ({int(coverage * 100)}%)")

        # Check structure regularity
        regularity = self._score_regularity(df)
        if regularity < 0.5:
            warnings.append("Irregular row structure")
        elif regularity < 0.7:
            warnings.append("Some row structure inconsistency")

        # Check numeric integrity
        numeric_score = self._score_numeric_integrity(df)
        if numeric_score < 0.6:
            warnings.append("Numeric parsing issues detected")
        elif numeric_score < 0.8:
            warnings.append("Some numeric values may be incorrectly parsed")

        # Check header detection
        header_score = self._score_header_detection(df, result.metadata)
        if header_score < 0.4:
            warnings.append("Header row may not be correctly identified")

        # Check table dimensions
        rows, cols = df.shape
        if rows < 3:
            warnings.append(f"Only {rows} rows extracted")
        if cols < 2:
            warnings.append(f"Only {cols} column(s) extracted")

        # Check if many cells are empty
        total_cells = df.size
        non_empty = sum(
            (df[col].astype(str).str.strip() != '').sum()
            for col in df.columns
        )
        empty_ratio = 1 - (non_empty / total_cells) if total_cells > 0 else 1
        if empty_ratio > 0.5:
            warnings.append(f"Many empty cells ({int(empty_ratio * 100)}%)")

        return warnings

    def _score_coverage(
        self,
        df: pd.DataFrame,
        page_text: Optional[str] = None
    ) -> float:
        """
        Score cell coverage (percentage of non-empty cells).

        If page_text is provided, also considers how much of the page text
        appears in the extracted table.

        Args:
            df: Extracted DataFrame.
            page_text: Optional full page text.

        Returns:
            Coverage score from 0.0 to 1.0.
        """
        total_cells = df.size
        if total_cells == 0:
            return 0.0

        # Count non-empty cells
        non_empty = 0
        for col in df.columns:
            non_empty += (df[col].astype(str).str.strip() != '').sum()

        cell_fill_ratio = non_empty / total_cells

        # If page text provided, measure text capture
        if page_text and page_text.strip():
            # Get all text from table
            table_text = ' '.join(
                str(cell) for row in df.values for cell in row if cell
            )
            table_words = set(table_text.lower().split())
            page_words = set(page_text.lower().split())

            if page_words:
                # Measure overlap (table words present in page)
                overlap = len(table_words & page_words)
                text_capture = overlap / len(page_words) if page_words else 0.0
                # Combine cell fill (more reliable) with text capture (scaled up
                # since tables typically contain only a fraction of page text)
                return 0.7 * cell_fill_ratio + 0.3 * min(text_capture * 2, 1.0)

        return cell_fill_ratio

    def _score_regularity(self, df: pd.DataFrame) -> float:
        """
        Score structure regularity (consistency of row/column structure).

        Evaluates:
        - Column count consistency across rows
        - Cell content length variance (lower is better)
        - Empty cell distribution (uniform is better than clustered)

        Args:
            df: Extracted DataFrame.

        Returns:
            Regularity score from 0.0 to 1.0.
        """
        if df.empty:
            return 0.0

        rows, cols = df.shape

        # Factor 1: Minimum viable structure (at least 2x2)
        structure_score = 1.0 if rows >= 2 and cols >= 2 else 0.5

        # Factor 2: Column fill consistency
        # Check if columns have similar fill rates
        col_fill_rates = []
        for col in df.columns:
            non_empty = (df[col].astype(str).str.strip() != '').sum()
            col_fill_rates.append(non_empty / rows if rows > 0 else 0.0)

        if col_fill_rates:
            max_fill = max(col_fill_rates)
            min_fill = min(col_fill_rates)
            col_consistency = min_fill / max_fill if max_fill > 0 else 0.0
        else:
            col_consistency = 0.0

        # Factor 3: Row fill consistency (vectorized for performance)
        non_empty_per_row = (df.astype(str).apply(lambda col: col.str.strip() != '')).sum(axis=1)
        row_fill_rates = (non_empty_per_row / cols).tolist() if cols > 0 else []

        if row_fill_rates:
            max_fill = max(row_fill_rates)
            min_fill = min(row_fill_rates)
            row_consistency = min_fill / max_fill if max_fill > 0 else 0.0
        else:
            row_consistency = 0.0

        # Combine factors: structure_score is binary (less granular), so weighted
        # lower; row/col consistency are equally important continuous metrics
        regularity = (
            0.2 * structure_score +
            0.4 * col_consistency +
            0.4 * row_consistency
        )

        return round(regularity, 4)

    def _score_numeric_integrity(self, df: pd.DataFrame) -> float:
        """
        Score numeric integrity (valid parseable numbers).

        Checks that cells containing numeric-looking content
        are actually valid numbers (not corrupted or truncated).

        Args:
            df: Extracted DataFrame.

        Returns:
            Numeric integrity score from 0.0 to 1.0.
        """
        if df.empty:
            return 0.0

        valid_numeric = 0
        total_numeric_looking = 0

        for col in df.columns:
            for value in df[col]:
                cell_str = str(value).strip()
                if not cell_str:
                    continue

                # Check if cell looks numeric
                if self._looks_numeric(cell_str):
                    total_numeric_looking += 1
                    # Validate it's actually parseable
                    if self._is_valid_number(cell_str):
                        valid_numeric += 1

        # If no numeric content found, give neutral score
        if total_numeric_looking == 0:
            return 0.7  # Neutral - table may be text-only

        integrity = valid_numeric / total_numeric_looking
        return round(integrity, 4)

    def _score_header_detection(
        self,
        df: pd.DataFrame,
        metadata: dict
    ) -> float:
        """
        Score header detection confidence based on RAW first row quality.

        Evaluates whether the first row looks like a clean header:
        - Non-empty values
        - Unique values (no duplicates)
        - Text content (not numeric)
        - Reasonable length

        Args:
            df: Extracted DataFrame (raw, before header processing).
            metadata: Extraction metadata dictionary.

        Returns:
            Header detection score from 0.0 to 1.0.
        """
        if df.empty or len(df) < 2:
            return 0.0

        # Analyze the raw first row
        first_row = df.iloc[0]
        first_row_values = [str(cell).strip() for cell in first_row]

        # Filter out empty/nan values
        non_empty = [v for v in first_row_values if v and v.lower() != 'nan']

        if not first_row_values:
            return 0.0

        # Score 1: Fill rate - what % of first row cells have content
        fill_ratio = len(non_empty) / len(first_row_values)
        fill_score = fill_ratio

        # Score 2: Uniqueness - no duplicate header values
        unique_values = set(non_empty)
        uniqueness_score = len(unique_values) / len(non_empty) if non_empty else 0

        # Score 3: Text vs numeric - headers should be mostly text
        numeric_count = sum(1 for v in non_empty if self._looks_numeric(v))
        text_ratio = 1 - (numeric_count / len(non_empty)) if non_empty else 0
        text_score = text_ratio

        # Score 4: Length - header cells shouldn't be too long (data-like)
        avg_len = sum(len(v) for v in non_empty) / len(non_empty) if non_empty else 0
        # Optimal header length is 5-30 chars. Penalize very short (<3) or long (>50)
        if avg_len < 3:
            length_score = 0.5
        elif avg_len <= 30:
            length_score = 1.0
        elif avg_len <= 50:
            length_score = 0.8
        else:
            length_score = max(0.3, 1.0 - (avg_len - 50) / 100)

        # Combine scores with weights
        # Fill and uniqueness most important - they indicate clean extraction
        header_score = (
            0.35 * fill_score +
            0.35 * uniqueness_score +
            0.20 * text_score +
            0.10 * length_score
        )

        return round(header_score, 4)

    def _looks_numeric(self, value: str) -> bool:
        """
        Check if a string looks like it contains numeric content.

        Args:
            value: String to check.

        Returns:
            True if string appears to contain numbers.
        """
        if not value:
            return False

        # Quick check for any digits
        if not any(c.isdigit() for c in value):
            return False

        # Match against numeric patterns
        return bool(self._NUMBER_PATTERN.match(value.strip()))

    def _is_valid_number(self, value: str) -> bool:
        """
        Validate that a numeric-looking string is actually parseable.

        Args:
            value: String to validate.

        Returns:
            True if string can be parsed as a number.
        """
        if not value:
            return False

        # Clean the value
        cleaned = value.strip()

        # Remove common currency symbols and formatting
        cleaned = re.sub(r'[$€£¥,\s]', '', cleaned)

        # Handle accounting format (negative in parentheses)
        if cleaned.startswith('(') and cleaned.endswith(')'):
            cleaned = '-' + cleaned[1:-1]

        # Remove percentage sign
        cleaned = cleaned.rstrip('%')

        # Try to parse
        try:
            float(cleaned)
            return True
        except ValueError:
            return False
