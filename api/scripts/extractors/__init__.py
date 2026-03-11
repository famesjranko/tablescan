"""
Extractors module for TableScan 2.0.

Provides pluggable table extraction backends with scoring and selection.
"""

from .base import BaseExtractor, ExtractionResult
from .camelot_extractor import CamelotExtractor
from .pdfplumber_extractor import PdfplumberExtractor
from .vision_extractor import VisionExtractor
from .scorer import ExtractionScorer
from .multi_extractor import MultiExtractor

__all__ = [
    'BaseExtractor',
    'ExtractionResult',
    'CamelotExtractor',
    'PdfplumberExtractor',
    'VisionExtractor',
    'ExtractionScorer',
    'MultiExtractor',
]
