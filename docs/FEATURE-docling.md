# FEATURE: Docling (IBM) Table-Extraction Backend

## Overview

Add **Docling (IBM)** as an additional, opt-in table-extraction backend in the
multi-extractor pipeline.

**Status**: Implemented (opt-in; benchmark/consolidation pending)
**Created**: 2026-06-09
**Related Issue**: [#7 — \[Epic\] Add Docling (IBM) as a table-extraction backend](https://github.com/famesjranko/tablescan/issues/7)
**Sub-issues**: #8 (deps + model pre-bake), #9 (extractor), #10 (registration/toggle), #11 (API threading), #12 (upload form), #13 (tests), #14 (benchmark go/no-go)

---

## Why

- Docling is open-source (Apache-2.0), self-hostable, and benchmarks ~97.9% cell
  accuracy on complex tables — well above the classic line/whitespace backends.
- Self-hosting means **no per-page API fee**: it targets extraction **quality**
  and **COGS** together, and enables a privacy/on-prem angle.
- It is the cheapest test of the "swap our own inference for a best-in-class
  backend" thesis — **additive and reversible**.

---

## Architecture

Docling slots into the existing pluggable extractor architecture as a new
`BaseExtractor` (`api/scripts/extractors/docling_extractor.py`). It mirrors the
region-aware workflow of `vision_extractor.py`:

```
table_areas (YOLO / manual selection, PDF coords)
  └── for each region:
        crop region → single-page PDF via PyMuPDF show_pdf_page
          (preserves the text layer, so born-digital PDFs need no OCR)
            └── DocumentConverter.convert(region_pdf)
                  └── document.tables → table.export_to_dataframe()
                        └── ExtractionResult(dataframe, confidence, method='docling', metadata)
```

Because the scorer, the variants cache, and the switch-method UI all key off
`ExtractionResult` + `method` name, Docling appears automatically as a scored,
selectable variant with **no changes** to scoring, persistence, or the
book-viewer frontend.

### Key design points (and epic gotchas)

- **Lazy singleton converter.** `DocumentConverter` (layout + TableFormer
  models) is built **once** and cached per pipeline config in a module-level
  cache — never per `extract()` call.
- **Lazy import.** `docling` is imported only inside the converter-builder, so
  the extractor module, package import, and `MultiExtractor` registration/toggle
  all work even when docling is not installed. A real region extract without
  docling raises a clean `ImportError`.
- **Pre-baked model weights.** The Dockerfile runs `docling-tools models
  download -o /opt/docling-models` at build time and sets
  `DOCLING_ARTIFACTS_PATH=/opt/docling-models`, avoiding a multi-hundred-MB
  cold-start download at runtime. The extractor also reads
  `DOCLING_ARTIFACTS_PATH` and passes it as `artifacts_path` for offline load.
- **torch/transformers.** Docling builds on the existing CPU-only torch already
  installed in the image; `requirements.txt` pins `docling>=2.0.0,<3.0.0`.

---

## Opt-in toggle

Docling is **off by default** (unlike the other backends, which default on):

| Layer | Key | Default |
|-------|-----|---------|
| Upload form | `use_docling` checkbox ("experimental") | unchecked |
| `views.py` | `request.POST.get('use_docling', 'off')` | off |
| tasks / `table_extract` defaults | `enabled_libraries['docling']` | `False` |
| `MultiExtractor` | `enabled_libraries.get('docling', False)` | `False` |

Enabling it adds a single `DoclingExtractor()` (name `docling`) to the pipeline.

---

## Testing

- **Unit + control-flow tests:** `api/tests/test_extractors.py`
  - `TestMultiExtractorDoclingToggle` — opt-in registration behavior
  - `TestDoclingExtractor*` — init/config, `extract()` error paths,
    validation/confidence/metadata helpers, `_table_to_dataframe` shim
  - Integration tests that actually run Docling are guarded with
    `pytest.importorskip("docling")` and run once docling is installed.
- **Isolated logic check (no full build, host-safe):**
  ```bash
  scripts/verify_docling_isolated.sh
  ```
  Runs `scripts/docling_isolated_checks.py` in an ephemeral `python:3.11-slim`
  container with only pandas + pymupdf + pytest — no torch, no docling weights,
  no Django/camelot, and no changes to the host.

---

## Scope / non-goals

- **In scope:** Docling as an opt-in backend behind a toggle, with tests and a
  head-to-head comparison pass.
- **Not in scope (follow-up, pending benchmark — #14):** making Docling the
  default, or removing weaker/heavier backends to cut compute.

## Benchmark go/no-go (#14)

Before promoting Docling to default or retiring other backends, run a
head-to-head on real PDFs (born-digital + scanned) measuring cell accuracy,
wall-clock per page, and image size impact. Capture the decision here.

| Metric | Docling | Best existing backend | Notes |
|--------|---------|-----------------------|-------|
| Cell accuracy (complex) | _TBD_ | _TBD_ | |
| Wall-clock / page | _TBD_ | _TBD_ | |
| Image size delta | _TBD_ | n/a | model weights |

**Decision:** _pending_
