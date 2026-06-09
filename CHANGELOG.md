# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Added

- **Docling Extractor (IBM)** - New opt-in extraction backend using IBM Docling's `DocumentConverter` + TableFormer for high-accuracy table structure recognition. Region-aware (crops each `table_area` to a single-page PDF, preserving the text layer), loads the converter once as a lazy singleton, and plugs into the existing scorer/variants/UI with no scoring or persistence changes. Disabled by default; model weights are pre-baked into the Docker image at build time. ([#7](https://github.com/famesjranko/tablescan/issues/7))
- **Docling Toggle** - `use_docling` upload-form checkbox ("experimental") threaded through views → tasks → `MultiExtractor` (`enabled_libraries['docling']`, default off)
- **Persisted library toggles** - `Report.enabled_libraries` (JSONField) stores the chosen extraction libraries at upload time so the **review** and **manual** flows (extraction via `extract_from_selections`) honor the same toggles — including opt-in Docling — instead of silently using defaults
- **Isolated Docling Verification** - `scripts/verify_docling_isolated.sh` runs the extractor's logic checks in an ephemeral container (pandas + pymupdf only), with no full image build and no host changes
- **PyMuPDF Extractor** - New extraction backend using PyMuPDF's `find_tables()` method with 'lines', 'lines_strict', and 'text' strategies
- **Extraction Library Toggles** - Users can enable/disable extraction libraries (Camelot, pdfplumber, PyMuPDF, vision, Docling) via checkboxes in Advanced Extraction Options
- **Multi-Extractor Pipeline** - Runs multiple extraction backends in parallel and selects best result using `ExtractionScorer`
- **BoundingBox Coordinate System** - Unified coordinate conversion between YOLO, PDF, Camelot, pdfplumber, and PyMuPDF formats
- **Book Viewer** - Interactive PDF viewer with page-by-page navigation and zoom controls
- **Manual Table Selection** - Draw table regions directly on PDF pages using click-and-drag
- **Review Workflow** - Approve or reject YOLO-detected tables before extraction
- **Multiple Extraction Modes**:
  - `auto` - Immediate extraction using YOLO detection
  - `review` - YOLO detection with approval step before extraction
  - `manual` - User-drawn selections only, no automatic detection
- **TableSelection Model** - Tracks table regions with source (yolo/manual) and status (pending/approved/rejected)
- **Selection API Endpoints**:
  - `GET/POST /api/reports/{id}/selections/` - List and create selections
  - `PATCH/DELETE /api/reports/{id}/selections/{sel_id}/` - Update or remove selections
- **Detection Task** - `detect_tables_for_review` creates pending TableSelection records from YOLO
- **Extraction from Selections** - `extract_from_selections` extracts only approved regions
- **Undo Support** - Revert approved/rejected selections back to pending status
- **Detection Box Visibility Toggle** - Show/hide YOLO detection overlays in Book Viewer

### Changed

- Upload flow now supports extraction mode selection
- Report model includes `extraction_mode` and `extraction_status` fields

### Fixed

- Migration drift: recorded the `"auto"` choice on `TableSelection.source` that was added to the model without a migration (`0012_alter_tableselection_source`), so `makemigrations --check` passes clean
- Detection boxes now clip to page boundaries
- Race condition in render timing for PDF pages resolved

### Security

- Added ownership checks to ReportDeleteView, TablePreviewView, DownloadAllCSVView
- All report-related views now verify `owner=request.user` before access
