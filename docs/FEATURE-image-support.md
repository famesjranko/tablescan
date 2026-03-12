# Feature Scope Document: Image File Support

**Version**: 1.0
**Date**: March 2026
**Author**: Technical Planning
**Status**: Draft
**Feature ID**: IMG-001

---

## 1. Executive Summary

Extend TableScan to accept image files (PNG, JPG, JPEG, TIFF, BMP, WEBP) in addition to PDFs for table extraction. The core extraction pipeline already includes OCR capabilities via `img2table` + `TesseractOCR` for scanned PDFs. This feature leverages that existing infrastructure to support direct image uploads.

**Key insight**: The `VisionExtractor` already converts PDF pages to images internally before processing. Supporting direct image uploads requires routing around the PDF-specific steps rather than building new extraction logic.

---

## 2. Current State Analysis

### 2.1 Existing Architecture

```
                                    CURRENT FLOW
                                    ============

PDF Upload
    |
    v
[UploadView] -----> Validates: magic number (%PDF-), file size
    |
    v
[Report Model] ---> document: FileField, f_type: "pdf"
    |
    v
[table_extract.extract()] ---> Multiprocessing pool
    |
    v
[process_page_with_routing()] ---> Per-page processing
    |
    +---> [PageClassifier] ---> Classifies: born_digital | scanned | mixed
    |
    +---> Routes based on classification:
          |
          +---> Born-Digital: DirectExtractor (Camelot, pdfplumber)
          |
          +---> Scanned/Mixed: VisionExtractor (img2table + Tesseract)
                    |
                    v
               [img2table.PDF] ---> Converts PDF page to image internally
                    |
                    v
               [TesseractOCR] ---> Extracts text from image
                    |
                    v
               [Table Detection] ---> Returns DataFrames
```

### 2.2 Key Components

#### 2.2.1 File Upload & Validation (api/views.py:53-72, 296-380)

```python
# Current validation
def validate_pdf(file) -> Tuple[bool, str]:
    # Check file size
    if file.size > MAX_UPLOAD_SIZE:
        return False, "File too large"

    # Check magic number (PDF signature)
    first_bytes = file.read(5)
    file.seek(0)
    if first_bytes != b'%PDF-':
        return False, "Invalid PDF file"

    return True, ""
```

**Limitation**: Only accepts PDF files via magic number check.

#### 2.2.2 Report Model (api/models.py:75-142)

```python
class Report(models.Model):
    name = models.CharField(max_length=100)
    document = models.FileField(upload_to=MyStorage())
    f_type = models.CharField(max_length=10)  # Currently always "pdf"
    total_pages = models.IntegerField(default=0)
    start_page = models.IntegerField(default=1)
    end_page = models.IntegerField(default=-1)
    # ... extraction workflow fields
```

**Limitation**: Schema assumes multi-page documents (total_pages, start_page, end_page).

#### 2.2.3 VisionExtractor (api/scripts/extractors/vision_extractor.py:57-141)

```python
def extract(self, pdf_path: str, page_num: int, table_areas=None):
    from img2table.document import PDF  # <-- PDF-specific
    from img2table.ocr import TesseractOCR

    doc = PDF(pdf_path, pages=[page_num - 1])  # <-- PDF-specific
    ocr = TesseractOCR(n_threads=1, lang="eng")

    extracted_tables = doc.extract_tables(
        ocr=ocr,
        implicit_rows=True,
        borderless_tables=True,
        min_confidence=50
    )
    # ... process results
```

**Opportunity**: `img2table` library has `Image` class that works identically to `PDF` class.

#### 2.2.4 Page Classification (api/scripts/page_classifier.py)

```python
class PageClassifier:
    def classify(self, pdf_path: str, page_num: int) -> PageClassification:
        # Uses PyMuPDF (fitz) to analyze PDF structure
        doc = fitz.open(pdf_path)
        page = doc[page_num]
        # ... analyzes text coverage, images
```

**Limitation**: Requires PDF file, uses page number indexing.

#### 2.2.5 Extraction Orchestrator (api/scripts/table_extract.py:646-943)

```python
def extract(file_path: str, start_page: int, end_page: int, ...):
    # PDF-specific validation
    if not file_name.endswith(".pdf"):
        raise AttributeError("not a pdf!")

    # Get page count (PDF-specific)
    total_pages = get_num_pages(file_path)  # Uses PyPDF2

    # Multiprocessing per page
    for num in range(start_at, end_at + 1):
        pool.apply_async(process_page_with_routing, ...)
```

**Limitation**: Hardcoded PDF assumption throughout.

### 2.3 Dependencies Already Present

| Package | Version | Capability |
|---------|---------|------------|
| img2table | >=1.2.0 | `PDF` and `Image` document classes |
| tesseract-ocr | system | OCR engine (already integrated) |
| Pillow | >=9.0 | Image loading/manipulation |
| pdf2image | >=1.16 | PDF to image conversion (existing) |

### 2.4 img2table Image Support (Already Available)

```python
# Current (PDF)
from img2table.document import PDF
doc = PDF(pdf_path, pages=[0])

# Available (Image) - same interface!
from img2table.document import Image
doc = Image(image_path)  # or Image(src=bytes_or_path)

# Extraction works identically
tables = doc.extract_tables(ocr=ocr, implicit_rows=True, ...)
```

---

## 3. Proposed Feature

### 3.1 User Story

**As a** user with tabular data in image format (screenshots, scanned single pages, photos of documents),
**I want to** upload images directly without converting to PDF first,
**So that** I can extract tables with the same quality as PDF extraction.

### 3.2 Supported Formats

| Format | Extension | MIME Type | Priority |
|--------|-----------|-----------|----------|
| PNG | .png | image/png | P0 |
| JPEG | .jpg, .jpeg | image/jpeg | P0 |
| TIFF | .tif, .tiff | image/tiff | P1 |
| BMP | .bmp | image/bmp | P2 |
| WebP | .webp | image/webp | P2 |

### 3.3 Functional Requirements

#### FR-IMG-1: File Upload

| ID | Requirement | Priority |
|----|-------------|----------|
| FR-IMG-1.1 | System SHALL accept image files (PNG, JPEG) via existing upload endpoint | P0 |
| FR-IMG-1.2 | System SHALL validate image files using magic number detection | P0 |
| FR-IMG-1.3 | System SHALL enforce same file size limits as PDFs | P0 |
| FR-IMG-1.4 | System SHALL store images in same document structure as PDFs | P0 |

#### FR-IMG-2: Extraction Routing

| ID | Requirement | Priority |
|----|-------------|----------|
| FR-IMG-2.1 | Image files SHALL route directly to VisionExtractor | P0 |
| FR-IMG-2.2 | Image files SHALL skip PageClassifier (not applicable) | P0 |
| FR-IMG-2.3 | Image files SHALL skip PDF-specific processing (page count, etc.) | P0 |
| FR-IMG-2.4 | System SHALL treat each image as a single "page" | P0 |

#### FR-IMG-3: Extraction

| ID | Requirement | Priority |
|----|-------------|----------|
| FR-IMG-3.1 | VisionExtractor SHALL support both PDF and Image document types | P0 |
| FR-IMG-3.2 | Image extraction SHALL use same OCR pipeline (TesseractOCR) | P0 |
| FR-IMG-3.3 | Image extraction SHALL produce same output formats (CSV, JSON, XLSX) | P0 |
| FR-IMG-3.4 | Image extraction SHALL populate same metadata fields | P0 |

#### FR-IMG-4: API Compatibility

| ID | Requirement | Priority |
|----|-------------|----------|
| FR-IMG-4.1 | Existing PDF upload API SHALL continue working unchanged | P0 |
| FR-IMG-4.2 | Report API responses SHALL indicate file type | P1 |
| FR-IMG-4.3 | Image reports SHALL have total_pages = 1 | P0 |
| FR-IMG-4.4 | start_page/end_page SHALL be ignored for images | P1 |

### 3.4 Non-Functional Requirements

| ID | Requirement | Target |
|----|-------------|--------|
| NFR-IMG-1 | Image extraction processing time | <5 seconds per image |
| NFR-IMG-2 | Maximum image dimensions | 10000x10000 pixels |
| NFR-IMG-3 | Memory usage per image | <500MB |
| NFR-IMG-4 | Extraction accuracy on clean images | >90% cell accuracy |

---

## 4. Technical Design

### 4.1 Target Architecture

```
                                    TARGET FLOW
                                    ===========

File Upload (PDF or Image)
    |
    v
[UploadView] -----> Validates based on file type:
    |                 - PDF: magic number (%PDF-)
    |                 - Image: magic number (PNG/JPEG/etc)
    v
[Report Model] ---> document: FileField
    |               f_type: "pdf" | "png" | "jpg" | "tiff" | ...
    |               source_type: "pdf" | "image"  (NEW)
    v
[extract() or extract_image()] ---> Routes by source_type
    |
    +---> PDF Path (existing):
    |         |
    |         v
    |     [process_page_with_routing()] per page
    |         |
    |         +---> PageClassifier
    |         +---> DirectExtractor or VisionExtractor
    |
    +---> Image Path (NEW):
              |
              v
          [process_image()] ---> Single image processing
              |
              v
          [VisionExtractor.extract_from_image()] ---> img2table.Image
              |
              v
          [TesseractOCR] ---> Table detection & OCR
              |
              v
          [Same output pipeline: CSV, JSON, XLSX, DB records]
```

### 4.2 Component Changes

#### 4.2.1 File Type Detection Module (NEW)

**File**: `api/scripts/file_detector.py`

```python
from enum import Enum
from dataclasses import dataclass
from typing import BinaryIO, Tuple
import struct

class SourceType(Enum):
    PDF = "pdf"
    IMAGE = "image"
    UNKNOWN = "unknown"

class ImageFormat(Enum):
    PNG = "png"
    JPEG = "jpg"
    TIFF = "tiff"
    BMP = "bmp"
    WEBP = "webp"

@dataclass
class FileTypeResult:
    source_type: SourceType
    format: str  # "pdf", "png", "jpg", etc.
    mime_type: str
    is_valid: bool
    error: str = ""

# Magic number signatures
SIGNATURES = {
    b'%PDF-': ('pdf', 'application/pdf', SourceType.PDF),
    b'\x89PNG\r\n\x1a\n': ('png', 'image/png', SourceType.IMAGE),
    b'\xff\xd8\xff': ('jpg', 'image/jpeg', SourceType.IMAGE),
    b'II*\x00': ('tiff', 'image/tiff', SourceType.IMAGE),  # Little-endian TIFF
    b'MM\x00*': ('tiff', 'image/tiff', SourceType.IMAGE),  # Big-endian TIFF
    b'BM': ('bmp', 'image/bmp', SourceType.IMAGE),
    b'RIFF': ('webp', 'image/webp', SourceType.IMAGE),  # WebP (check WEBP after)
}

def detect_file_type(file: BinaryIO) -> FileTypeResult:
    """
    Detect file type from magic number.

    Args:
        file: File-like object positioned at start

    Returns:
        FileTypeResult with type information
    """
    header = file.read(12)
    file.seek(0)

    for signature, (fmt, mime, source_type) in SIGNATURES.items():
        if header.startswith(signature):
            # Special case: WebP needs additional check
            if fmt == 'webp' and header[8:12] != b'WEBP':
                continue
            return FileTypeResult(
                source_type=source_type,
                format=fmt,
                mime_type=mime,
                is_valid=True
            )

    return FileTypeResult(
        source_type=SourceType.UNKNOWN,
        format="",
        mime_type="",
        is_valid=False,
        error="Unsupported file format"
    )
```

#### 4.2.2 Model Changes (api/models.py)

```python
class SourceType(models.TextChoices):
    PDF = 'pdf', 'PDF Document'
    IMAGE = 'image', 'Image File'

class Report(models.Model):
    # Existing fields...
    name = models.CharField(max_length=100)
    document = models.FileField(upload_to=MyStorage())
    f_type = models.CharField(max_length=10)  # file extension: pdf, png, jpg

    # NEW field
    source_type = models.CharField(
        max_length=10,
        choices=SourceType.choices,
        default=SourceType.PDF
    )

    # Existing page fields - interpreted differently for images
    total_pages = models.IntegerField(default=0)  # Always 1 for images
    start_page = models.IntegerField(default=1)   # Always 1 for images
    end_page = models.IntegerField(default=-1)    # Always 1 for images

    @property
    def is_image(self) -> bool:
        return self.source_type == SourceType.IMAGE

    @property
    def is_pdf(self) -> bool:
        return self.source_type == SourceType.PDF
```

#### 4.2.3 Upload View Changes (api/views.py)

```python
from api.scripts.file_detector import detect_file_type, SourceType

def validate_upload(file) -> Tuple[bool, str, FileTypeResult]:
    """
    Validate uploaded file (PDF or image).

    Returns:
        Tuple of (is_valid, error_message, file_type_result)
    """
    # Check file size
    if file.size > MAX_UPLOAD_SIZE:
        return False, f"File exceeds maximum size of {MAX_UPLOAD_SIZE} bytes", None

    # Detect file type
    file_type = detect_file_type(file)

    if not file_type.is_valid:
        return False, file_type.error, file_type

    if file_type.source_type == SourceType.UNKNOWN:
        return False, "Unsupported file format. Accepted: PDF, PNG, JPEG, TIFF, BMP, WebP", file_type

    return True, "", file_type

class UploadView(APIView):
    def post(self, request):
        # Validate file
        is_valid, error, file_type = validate_upload(request.FILES['document'])
        if not is_valid:
            return Response({'error': error}, status=400)

        # Create report with source_type
        serializer = ReportSerializer(data=request.data)
        if serializer.is_valid():
            report = serializer.save(
                owner=request.user,
                source_type=file_type.source_type.value,
                f_type=file_type.format
            )

            # Queue appropriate extraction task
            if file_type.source_type == SourceType.IMAGE:
                extract_image_task.delay(report.id, report.document.path)
            else:
                extract_tables_task.delay(report.id, report.document.path, ...)

            return Response(ReportSerializer(report).data, status=201)
```

#### 4.2.4 VisionExtractor Enhancement (api/scripts/extractors/vision_extractor.py)

```python
from typing import Union
from pathlib import Path

class VisionExtractor(BaseExtractor):
    """
    Table extractor using img2table library.
    Supports both PDF pages and standalone images.
    """

    def extract(
        self,
        pdf_path: str,
        page_num: int,
        table_areas: Optional[List[tuple]] = None
    ) -> List[ExtractionResult]:
        """Extract tables from a PDF page (existing method)."""
        from img2table.document import PDF
        return self._extract_internal(PDF(pdf_path, pages=[page_num - 1]), page_num, table_areas)

    def extract_from_image(
        self,
        image_path: str,
        table_areas: Optional[List[tuple]] = None
    ) -> List[ExtractionResult]:
        """
        Extract tables from a standalone image file.

        NEW METHOD for image support.

        Args:
            image_path: Path to image file (PNG, JPEG, TIFF, etc.)
            table_areas: Optional bounding boxes to constrain extraction

        Returns:
            List of ExtractionResult, one per detected table
        """
        from img2table.document import Image

        if not Path(image_path).is_file():
            raise FileNotFoundError(f"Image file not found: {image_path}")

        return self._extract_internal(Image(image_path), page_num=1, table_areas=table_areas)

    def _extract_internal(
        self,
        doc: Union["PDF", "Image"],  # img2table document
        page_num: int,
        table_areas: Optional[List[tuple]] = None
    ) -> List[ExtractionResult]:
        """
        Internal extraction logic shared between PDF and Image.

        Args:
            doc: img2table PDF or Image document
            page_num: Page number (1 for images)
            table_areas: Optional bounding boxes
        """
        from img2table.ocr import TesseractOCR

        # Initialize OCR
        ocr = None
        try:
            ocr = TesseractOCR(n_threads=1, lang="eng")
        except Exception:
            pass  # Continue without OCR if unavailable

        # Extract tables
        extracted_tables = doc.extract_tables(
            ocr=ocr,
            implicit_rows=self._implicit_rows,
            borderless_tables=self._borderless_tables,
            min_confidence=int(self._min_confidence * 100)
        )

        # For PDF: result is dict keyed by page index
        # For Image: result is dict with key 0 (single "page")
        page_key = page_num - 1 if isinstance(extracted_tables, dict) else 0
        page_tables = extracted_tables.get(page_key, []) if isinstance(extracted_tables, dict) else extracted_tables

        results = []
        for i, table in enumerate(page_tables):
            if table_areas and not self._table_in_areas(table, table_areas):
                continue
            result = self._process_table(table, i, page_num)
            if result:
                results.append(result)

        return results
```

#### 4.2.5 Image Extraction Orchestrator (NEW)

**File**: `api/scripts/image_extract.py`

```python
"""
image_extract.py
    Orchestrator for image file table extraction.

    Simplified version of table_extract.py for single-image processing.
    No multiprocessing needed (single image = single unit of work).
"""

from pathlib import Path, PurePath
from typing import Dict, Any, Optional, Callable

from api.models import Report, Extracted
from api.scripts.logging import Logging
from api.scripts.extractors import VisionExtractor, ExtractionScorer
from api.scripts.extractors.base import ExtractionResult
from api.scripts.YOLOV3.predict_table import (
    build_structure_json, tableValidate, save_extraction_results
)
from api.scripts.header_processor import process_table_headers, strip_empty_rows_and_cols


def extract_image(
    file_path: str,
    report_id: int,
    progress_callback: Optional[Callable[[int, str], None]] = None
) -> Dict[str, Any]:
    """
    Extract tables from an image file.

    Simplified orchestrator for single-image extraction.
    Uses VisionExtractor (img2table + Tesseract) for detection and OCR.

    Args:
        file_path: Path to image file
        report_id: Database Report ID
        progress_callback: Optional progress update callback

    Returns:
        dict with extraction results

    Raises:
        FileNotFoundError: If image file doesn't exist
        Report.DoesNotExist: If report_id invalid
    """
    log = Logging()

    # Get report
    report_db = Report.objects.get(id=report_id)

    # Validate file exists
    if not Path(file_path).is_file():
        report_db.extraction_status = 'failed'
        report_db.save()
        raise FileNotFoundError(f"Image file not found: {file_path}")

    log.output('INFO', f'Starting image extraction: {Path(file_path).name}')

    # Update report for image
    report_db.total_pages = 1
    report_db.start_page = 1
    report_db.end_page = 1
    report_db.extraction_status = 'extracting'
    report_db.save()

    if progress_callback:
        progress_callback(20, "Running OCR and table detection...")

    # Setup output directories
    full_working_dir = Path(file_path).parent
    extract_dir = {
        "csv": PurePath(full_working_dir, "csv"),
        "json": PurePath(full_working_dir, "json"),
        "xlsx": PurePath(full_working_dir, "xlsx"),
    }

    for dir_path in extract_dir.values():
        Path(dir_path).mkdir(parents=True, exist_ok=True)

    # Initialize extractor and scorer
    vision_extractor = VisionExtractor(
        implicit_rows=True,
        borderless_tables=True,
        min_confidence=0.5
    )
    scorer = ExtractionScorer()

    # Extract tables
    try:
        results = vision_extractor.extract_from_image(file_path)
        log.output('INFO', f'VisionExtractor found {len(results)} table(s)')
    except Exception as e:
        log.output('ERROR', f'Extraction failed: {e}')
        report_db.extraction_status = 'failed'
        report_db.save()
        raise

    if progress_callback:
        progress_callback(60, "Processing extracted tables...")

    # Score and sort results
    scored_results = scorer.score_all(results)

    # Process and validate
    processed_results = []
    for result, score in scored_results:
        df = result.dataframe.copy()
        df = df.fillna("")
        df = strip_empty_rows_and_cols(df)

        if not tableValidate(df):
            continue

        header_spans = []
        df, header_spans = process_table_headers(df, merge_headers=True)

        # Enrich metadata
        metadata = dict(result.metadata) if result.metadata else {}
        metadata['structure_json'] = build_structure_json(df, metadata)
        metadata['header_spans'] = header_spans
        metadata['computed_score'] = score

        processed_results.append(ExtractionResult(
            dataframe=df,
            confidence=result.confidence,
            method=result.method,
            metadata=metadata
        ))

    if progress_callback:
        progress_callback(80, "Saving results...")

    # Save results
    save_extraction_results(
        results=processed_results,
        file_path=file_path,
        page_num=1,
        report_db=report_db,
        extract_dir=extract_dir,
        page_type='image'
    )

    # Update report status
    report_db.extraction_status = 'completed'
    report_db.save()

    log.output('INFO', f'Image extraction complete: {len(processed_results)} table(s)')

    if progress_callback:
        progress_callback(100, "Complete")

    return {
        "report_id": report_db.id,
        "file_name": Path(file_path).name,
        "source_type": "image",
        "tables_found": len(processed_results),
    }
```

#### 4.2.6 Celery Task for Images (api/tasks.py)

```python
@shared_task(bind=True)
def extract_image_task(self, report_id: int, file_path: str):
    """
    Async task for image extraction.

    Simpler than extract_tables_task since images are single units.
    """
    from api.scripts.image_extract import extract_image

    start_time = time.time()

    try:
        report = Report.objects.get(id=report_id)
    except Report.DoesNotExist:
        return {'status': 'skipped', 'reason': 'Report not found'}

    def progress_callback(percent, message):
        self.update_state(
            state='PROGRESS',
            meta={'percent': percent, 'message': message}
        )

    try:
        result = extract_image(
            file_path=file_path,
            report_id=report_id,
            progress_callback=progress_callback
        )

        duration = time.time() - start_time
        return {
            'status': 'completed',
            'report_id': report_id,
            'duration': f'{duration:.1f}s',
            'result': result
        }
    except Exception as e:
        logger.exception(f"Image extraction failed for report {report_id}")
        return {
            'status': 'failed',
            'report_id': report_id,
            'error': str(e)
        }
```

### 4.3 Database Migration

```python
# Migration: add source_type field to Report

from django.db import migrations, models

class Migration(migrations.Migration):
    dependencies = [
        ('api', 'XXXX_previous_migration'),
    ]

    operations = [
        migrations.AddField(
            model_name='report',
            name='source_type',
            field=models.CharField(
                choices=[('pdf', 'PDF Document'), ('image', 'Image File')],
                default='pdf',
                max_length=10,
            ),
        ),
    ]
```

### 4.4 Updated Extracted Model page_type Enum

```python
class PageType(models.TextChoices):
    BORN_DIGITAL = 'born_digital', 'Born Digital'
    SCANNED = 'scanned', 'Scanned'
    MIXED = 'mixed', 'Mixed'
    IMAGE = 'image', 'Image'  # NEW
```

---

## 5. API Changes

### 5.1 Upload Endpoint (No Change to URL)

**Endpoint**: `POST /api/upload/`

**Request**: Multipart form data (unchanged)

```
Content-Type: multipart/form-data
document: <file>  # Now accepts PDF or image
```

**Response**: Extended with source_type

```json
{
    "id": 123,
    "name": "financial_table",
    "document": "/documents/financial_table/table.png",
    "f_type": "png",
    "source_type": "image",
    "total_pages": 1,
    "extraction_status": "extracting",
    "created_at": "2026-03-12T10:30:00Z"
}
```

### 5.2 Report Detail (Extended)

**Endpoint**: `GET /api/reports/{id}/`

```json
{
    "id": 123,
    "name": "financial_table",
    "source_type": "image",
    "f_type": "png",
    "total_pages": 1,
    "extraction_status": "completed",
    "extracted": [
        {
            "id": 456,
            "page_num": 1,
            "table_num": 0,
            "page_type": "image",
            "extraction_method": "img2table",
            "confidence_score": 0.87,
            "file": "/documents/financial_table/csv/table-1-table-0.csv"
        }
    ]
}
```

### 5.3 Backwards Compatibility

| Aspect | Compatibility |
|--------|---------------|
| Existing PDF uploads | Unchanged |
| Existing API responses | Additive fields only |
| Existing extracted data | Unaffected |
| start_page/end_page params | Ignored for images |
| extraction_mode (manual/review) | Supported for images |

---

## 6. File Structure Changes

```
api/
├── scripts/
│   ├── file_detector.py          # NEW: File type detection
│   ├── image_extract.py          # NEW: Image extraction orchestrator
│   ├── table_extract.py          # MODIFY: Add source_type check
│   ├── page_classifier.py        # UNCHANGED
│   └── extractors/
│       ├── vision_extractor.py   # MODIFY: Add extract_from_image()
│       └── ...
├── models.py                     # MODIFY: Add source_type field
├── views.py                      # MODIFY: File type detection
├── tasks.py                      # MODIFY: Add extract_image_task
└── serializers.py               # MODIFY: Include source_type
```

---

## 7. Testing Strategy

### 7.1 Unit Tests

| Test | File | Coverage |
|------|------|----------|
| File type detection | test_file_detector.py | Magic numbers for all formats |
| VisionExtractor.extract_from_image() | test_vision_extractor.py | PNG, JPEG extraction |
| Image extraction orchestrator | test_image_extract.py | Full pipeline |

### 7.2 Integration Tests

| Test | Description |
|------|-------------|
| Upload PNG via API | Verify file accepted, task queued |
| Upload JPEG via API | Verify file accepted, task queued |
| End-to-end image extraction | Upload image, wait for completion, verify CSV output |
| Mixed uploads | Upload PDF then image, verify both work |

### 7.3 Test Images

Create test fixtures:
- `tests/fixtures/simple_table.png` - 3x3 table, clear borders
- `tests/fixtures/complex_table.png` - Merged cells, headers
- `tests/fixtures/borderless_table.png` - No visible grid
- `tests/fixtures/photo_table.jpg` - Photo of printed table
- `tests/fixtures/screenshot_table.png` - Screenshot with table

### 7.4 Accuracy Benchmarks

| Image Type | Target Accuracy |
|------------|-----------------|
| Clean screenshot | >95% |
| Scanned document | >85% |
| Photo of document | >75% |
| Borderless table | >80% |

---

## 8. Implementation Phases

### Phase 1: Foundation (2-3 days)

- [ ] Create `file_detector.py` with magic number detection
- [ ] Add `source_type` field to Report model
- [ ] Create database migration
- [ ] Unit tests for file detection

**Definition of Done**: File type detection works for all target formats.

### Phase 2: Extractor Enhancement (2-3 days)

- [ ] Add `extract_from_image()` to VisionExtractor
- [ ] Refactor internal extraction logic for code reuse
- [ ] Create `image_extract.py` orchestrator
- [ ] Unit tests for image extraction

**Definition of Done**: VisionExtractor successfully extracts from PNG/JPEG files.

### Phase 3: API Integration (2-3 days)

- [ ] Update `UploadView` with file type detection
- [ ] Create `extract_image_task` Celery task
- [ ] Update serializers with `source_type`
- [ ] Integration tests for upload flow

**Definition of Done**: Images can be uploaded via API and extraction completes.

### Phase 4: Polish & Edge Cases (1-2 days)

- [ ] Handle large images (resize if needed)
- [ ] Handle corrupted images gracefully
- [ ] Update frontend (if applicable)
- [ ] Documentation updates
- [ ] End-to-end testing

**Definition of Done**: Feature is production-ready.

---

## 9. Risks and Mitigations

| Risk | Probability | Impact | Mitigation |
|------|-------------|--------|------------|
| Tesseract not installed | Medium | High | Check at startup, clear error message |
| Large images cause OOM | Medium | Medium | Add image size limits, resize before processing |
| Low accuracy on photos | High | Medium | Document limitations, suggest preprocessing |
| img2table API changes | Low | Medium | Pin version, add compatibility layer |
| Mixed usage of source_type | Low | Low | Clear API documentation |

---

## 10. Future Considerations

Items deferred from this implementation:

- **Batch image upload**: Upload multiple images as single report
- **Image preprocessing**: Auto-rotate, deskew, contrast enhancement
- **OCR language selection**: Support for non-English tables
- **Image-specific manual selection UI**: Adapted book viewer for images
- **URL image fetch**: Extract tables from image URLs
- **Clipboard paste**: Extract from pasted screenshots

---

## 11. Success Metrics

| Metric | Target | Measurement |
|--------|--------|-------------|
| Image upload success rate | >99% | Monitoring |
| Image extraction success rate | >90% | Task completion logs |
| Extraction accuracy (clean images) | >90% | Manual review sample |
| Processing time per image | <5 seconds | Task duration logs |
| No PDF regression | 0 failures | Existing test suite |

---

## 12. Appendix

### A. Magic Number Reference

| Format | Bytes (hex) | Bytes (string) |
|--------|-------------|----------------|
| PDF | 25 50 44 46 2D | %PDF- |
| PNG | 89 50 4E 47 0D 0A 1A 0A | .PNG.... |
| JPEG | FF D8 FF | ... |
| TIFF (LE) | 49 49 2A 00 | II*. |
| TIFF (BE) | 4D 4D 00 2A | MM.* |
| BMP | 42 4D | BM |
| WebP | 52 49 46 46 ... 57 45 42 50 | RIFF...WEBP |

### B. img2table Document Classes

```python
# PDF document
from img2table.document import PDF
pdf_doc = PDF(src="path/to/file.pdf", pages=[0, 1, 2])

# Image document
from img2table.document import Image
img_doc = Image(src="path/to/image.png")
# or
img_doc = Image(src=image_bytes)
# or
from PIL import Image as PILImage
pil_img = PILImage.open("path/to/image.png")
img_doc = Image(src=pil_img)

# Both use same extraction interface
tables = doc.extract_tables(
    ocr=TesseractOCR(),
    implicit_rows=True,
    borderless_tables=True,
    min_confidence=50
)
```

### C. Related Files Reference

| Component | File Path |
|-----------|-----------|
| Current upload validation | api/views.py:53-72 |
| Report model | api/models.py:75-142 |
| VisionExtractor | api/scripts/extractors/vision_extractor.py |
| Table extract orchestrator | api/scripts/table_extract.py |
| Celery tasks | api/tasks.py |
| Serializers | api/serializers.py |
