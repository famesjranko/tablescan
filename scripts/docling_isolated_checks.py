"""
docling_isolated_checks.py
    Isolated, dependency-light verification for DoclingExtractor.

    These checks exercise everything in DoclingExtractor that does NOT require
    the (heavy) docling dependency:
      - init / config / artifacts_path env precedence
      - extract() error + early-return control flow
      - validation, cleaning, numeric, confidence, metadata helpers
      - the _table_to_dataframe API-compat shim
      - that a real region extract surfaces a clean ImportError when docling
        is absent (proves the lazy-import / opt-in design)

    It is run by scripts/verify_docling_isolated.sh, which assembles a tiny
    `exti` package from the REAL source files (api/scripts/extractors/base.py +
    docling_extractor.py) and runs this module with pytest inside an ephemeral
    python:3.11-slim container with only pandas + pymupdf + pytest installed.

    Why this exists: it validates the extractor logic in seconds without
    building the full image (no torch / docling weights / Django / camelot) and
    without mutating the host. The full docling integration path (region crop ->
    Docling convert -> dataframe) is covered by the importorskip-guarded tests
    in api/tests/test_extractors.py, which run once docling is installed.

    Run via:  scripts/verify_docling_isolated.sh
"""

import os
import tempfile

import fitz
import pandas as pd
import pytest

from exti.base import BaseExtractor
from exti.docling_extractor import DoclingExtractor, _table_to_dataframe


@pytest.fixture
def simple_table_pdf():
    with tempfile.NamedTemporaryFile(suffix='.pdf', delete=False) as f:
        pdf_path = f.name
    doc = fitz.open()
    page = doc.new_page(width=612, height=792)
    shape = page.new_shape()
    x_start, y_start = 100, 200
    cell_width, cell_height = 120, 30
    rows, cols = 4, 3
    for i in range(rows + 1):
        y = y_start + i * cell_height
        shape.draw_line(fitz.Point(x_start, y), fitz.Point(x_start + cols * cell_width, y))
    for j in range(cols + 1):
        x = x_start + j * cell_width
        shape.draw_line(fitz.Point(x, y_start), fitz.Point(x, y_start + rows * cell_height))
    shape.finish(color=(0, 0, 0), width=0.5)
    shape.commit()
    data = [["Name", "Value", "Status"], ["A", "100", "X"], ["B", "200", "Y"], ["C", "300", "Z"]]
    for i, row in enumerate(data):
        for j, cell in enumerate(row):
            page.insert_text(fitz.Point(x_start + j * cell_width + 10, y_start + i * cell_height + 20),
                             cell, fontsize=10, fontname="helv")
    doc.save(pdf_path)
    doc.close()
    yield pdf_path
    if os.path.exists(pdf_path):
        os.unlink(pdf_path)


# --- init / config ---

def test_name_is_docling():
    assert DoclingExtractor().name == 'docling'

def test_is_base_extractor():
    assert isinstance(DoclingExtractor(), BaseExtractor)

def test_default_table_mode_accurate():
    assert DoclingExtractor()._table_mode == 'accurate'

def test_fast_mode_accepted():
    assert DoclingExtractor(table_mode='fast')._table_mode == 'fast'

def test_invalid_mode_raises():
    with pytest.raises(ValueError, match="table_mode"):
        DoclingExtractor(table_mode='nope')

def test_do_ocr_default_false():
    assert DoclingExtractor()._do_ocr is False

def test_artifacts_path_from_env(monkeypatch):
    monkeypatch.setenv('DOCLING_ARTIFACTS_PATH', '/opt/docling-models')
    assert DoclingExtractor()._artifacts_path == '/opt/docling-models'

def test_explicit_artifacts_overrides_env(monkeypatch):
    monkeypatch.setenv('DOCLING_ARTIFACTS_PATH', '/opt/docling-models')
    assert DoclingExtractor(artifacts_path='/custom')._artifacts_path == '/custom'

def test_artifacts_none_when_unset(monkeypatch):
    monkeypatch.delenv('DOCLING_ARTIFACTS_PATH', raising=False)
    assert DoclingExtractor()._artifacts_path is None


# --- extract() control flow (runs before any docling import) ---

def test_extract_nonexistent_file_raises():
    with pytest.raises(FileNotFoundError):
        DoclingExtractor().extract('/nope/file.pdf', 1)

def test_extract_no_table_areas_returns_empty(simple_table_pdf):
    assert DoclingExtractor().extract(simple_table_pdf, 1, table_areas=None) == []

def test_extract_invalid_page_raises(simple_table_pdf):
    with pytest.raises(ValueError, match="out of range"):
        DoclingExtractor().extract(simple_table_pdf, 999, table_areas=[(100.0, 500.0, 460.0, 700.0)])

def test_extract_page_zero_raises(simple_table_pdf):
    with pytest.raises(ValueError, match="out of range"):
        DoclingExtractor().extract(simple_table_pdf, 0, table_areas=[(100.0, 500.0, 460.0, 700.0)])

def test_extract_missing_docling_raises_importerror(simple_table_pdf):
    # docling is NOT installed in the isolated container, so a real region
    # extract must surface a clean ImportError (proves lazy-import design).
    with pytest.raises(ImportError):
        DoclingExtractor().extract(simple_table_pdf, 1, table_areas=[(100.0, 500.0, 460.0, 700.0)])


# --- helpers ---

def test_is_valid_table():
    ext = DoclingExtractor()
    assert ext._is_valid_table(pd.DataFrame([['a', 'b'], ['c', 'd']])) is True
    assert ext._is_valid_table(pd.DataFrame([['a', 'b']])) is False

def test_clean_dataframe_replaces_none():
    cleaned = DoclingExtractor()._clean_dataframe(pd.DataFrame({'A': [1, None], 'B': [None, 2]}))
    assert not cleaned.isna().any().any()

def test_clean_dataframe_pushes_multiindex_header_to_row0():
    cols = pd.MultiIndex.from_tuples([('Group', 'a'), ('Group', 'b')])
    cleaned = DoclingExtractor()._clean_dataframe(pd.DataFrame([[1, 2], [3, 4]], columns=cols))
    assert not isinstance(cleaned.columns, pd.MultiIndex)
    assert list(cleaned.columns) == [0, 1]
    assert list(cleaned.iloc[0]) == ['Group a', 'Group b']

def test_duplicate_spanning_headers_do_not_crash_scoring():
    # Duplicate collapsed labels must not crash scoring (regression: silent drop)
    ext = DoclingExtractor()
    cols = pd.MultiIndex.from_tuples([('Amount', ''), ('Amount', ''), ('Year', '2023')])
    cleaned = ext._clean_dataframe(pd.DataFrame([['10', '20', '2023'], ['30', '40', '2024']], columns=cols))
    assert list(cleaned.iloc[0]) == ['Amount', 'Amount', 'Year 2023']
    conf = ext._calculate_confidence(cleaned)
    assert isinstance(conf, float) and 0.0 <= conf <= 1.0

def test_has_numeric_content():
    ext = DoclingExtractor()
    assert ext._has_numeric_content('123') is True
    assert ext._has_numeric_content('$4.5') is True
    assert ext._has_numeric_content('text') is False
    assert ext._has_numeric_content('') is False

def test_confidence_empty_is_zero():
    assert DoclingExtractor()._calculate_confidence(pd.DataFrame()) == 0.0

def test_confidence_in_range():
    df = pd.DataFrame([['Name', 'Value'], ['A', '100'], ['B', '200']])
    c = DoclingExtractor()._calculate_confidence(df)
    assert isinstance(c, float) and 0.0 <= c <= 1.0

def test_build_metadata():
    md = DoclingExtractor()._build_metadata(
        pd.DataFrame([['a', 'b'], ['c', 'd']]), table_index=5, page_num=2, original_bbox=(10, 20, 110, 220))
    assert md['table_index'] == 5
    assert md['page_num'] == 2
    assert md['bounding_box'] == {'x1': 10, 'y1': 20, 'x2': 110, 'y2': 220}
    assert md['extractor_settings'] == {'table_mode': 'accurate', 'do_ocr': False}
    assert md['table_dimensions'] == {'rows': 2, 'cols': 2}


# --- _table_to_dataframe compat shim ---

def test_shim_prefers_doc_kwarg():
    class NewApi:
        def export_to_dataframe(self, doc=None):
            assert doc is not None
            return pd.DataFrame([['a', 'b']])
    out = _table_to_dataframe(NewApi(), document=object())
    assert out is not None and list(out.iloc[0]) == ['a', 'b']

def test_shim_falls_back_to_noarg():
    class OldApi:
        def export_to_dataframe(self):
            return pd.DataFrame([['x', 'y']])
    out = _table_to_dataframe(OldApi(), document=object())
    assert out is not None and list(out.iloc[0]) == ['x', 'y']

def test_shim_returns_none_on_error():
    class Broken:
        def export_to_dataframe(self, doc=None):
            raise RuntimeError("boom")
    assert _table_to_dataframe(Broken(), document=object()) is None
