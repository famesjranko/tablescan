"""
Extractors module for TableScan 2.0.

Provides pluggable table extraction backends with scoring and selection.
"""

from .base import BaseExtractor, ExtractionResult

__all__ = ['BaseExtractor', 'ExtractionResult']
