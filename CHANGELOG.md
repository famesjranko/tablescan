# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Added

- **PyMuPDF Extractor** - New extraction backend using PyMuPDF's `find_tables()` method with 'lines', 'lines_strict', and 'text' strategies
- **Extraction Library Toggles** - Users can enable/disable extraction libraries (Camelot, pdfplumber, PyMuPDF, vision) via checkboxes in Advanced Extraction Options
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

- Detection boxes now clip to page boundaries
- Race condition in render timing for PDF pages resolved

### Security

- Added ownership checks to ReportDeleteView, TablePreviewView, DownloadAllCSVView
- All report-related views now verify `owner=request.user` before access
