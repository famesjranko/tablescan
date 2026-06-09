"""
Unit tests for api/scripts/header_processor.py helpers.

header_processor only depends on pandas/numpy/re, so these run without Django
or the heavy extractor stack.
"""

import pandas as pd
import pytest

from api.scripts.header_processor import uniquify_column_names


class TestUniquifyColumnNames:
    """Tests for uniquify_column_names() — guards the to_json(orient='columns')
    export against duplicate column labels produced by multi-row header merges
    (regression for the duplicate-column crash surfaced in the #16 review)."""

    def test_unique_columns_returned_unchanged(self):
        # Given: a frame whose labels are already unique
        df = pd.DataFrame([[1, 2, 3]], columns=["a", "b", "c"])

        # When/Then: returned object is the same instance (no copy)
        assert uniquify_column_names(df) is df

    def test_duplicate_labels_are_suffixed(self):
        # Given: a multi-row header merge produced two identical labels
        df = pd.DataFrame([["10", "20"]], columns=["Region > Total", "Region > Total"])

        # When: uniquifying
        out = uniquify_column_names(df)

        # Then: duplicates get a .1 suffix; data is preserved
        assert list(out.columns) == ["Region > Total", "Region > Total.1"]
        assert out.values.tolist() == [["10", "20"]]

    def test_uniquified_frame_serializes_as_columns_json(self):
        # Given: duplicate columns that crash to_json(orient='columns')
        df = pd.DataFrame([["10", "20"]], columns=["Total", "Total"])
        with pytest.raises(ValueError):
            df.to_json(orient="columns")

        # When/Then: after uniquifying, the export succeeds
        out = uniquify_column_names(df)
        json_str = out.to_json(orient="columns")  # must not raise
        assert "Total" in json_str and "Total.1" in json_str

    def test_synthesized_suffix_collision_is_resolved(self):
        # Given: a synthesized name ("Total.1") already exists among originals
        df = pd.DataFrame([[1, 2, 3]], columns=["Total", "Total", "Total.1"])

        # When: uniquifying
        out = uniquify_column_names(df)

        # Then: all labels are unique (collision-safe loop)
        assert len(set(out.columns)) == 3
        assert "Total" in out.columns

    def test_does_not_mutate_input(self):
        # Given: a frame with duplicate labels
        df = pd.DataFrame([["x", "y"]], columns=["Dup", "Dup"])

        # When: uniquifying
        uniquify_column_names(df)

        # Then: the original frame is untouched
        assert list(df.columns) == ["Dup", "Dup"]
