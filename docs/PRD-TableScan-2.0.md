# TableScan 2.0: Product Requirements Document

**Version**: 1.0
**Date**: March 2026
**Author**: Technical Planning
**Status**: Draft

---

## 1. Executive Summary

TableScan is a PDF table extraction tool built in 2022 using YOLO v3 for table detection and Camelot for data extraction. This PRD defines requirements for modernizing the system to improve accuracy, reliability, and performance for extracting tables from financial annual reports and similar complex documents.

**Key upgrade**: Replace single-path extraction with intelligent routing based on PDF type, add multi-extractor scoring for accuracy, and upgrade detection models for scanned documents.

---

## 2. Problem Statement

### 2.1 Current Pain Points

| Problem | Impact | Root Cause |
|---------|--------|------------|
| Slow processing | 300+ page reports take too long | Every page converted to JPG even when unnecessary |
| Inconsistent accuracy | Some tables extract poorly | Single extractor (Camelot) fails on certain table types |
| No fallback options | When extraction fails, user gets nothing | No alternative extraction methods available |
| Complex table failures | Merged cells, multi-row headers lost | Output format (CSV) cannot represent table structure |

### 2.2 User Needs

**Primary users**: Financial analysts, researchers extracting data from company annual reports.

**Key jobs to be done**:
1. Upload a PDF annual report and get all tables as structured data
2. Handle both modern born-digital reports and scanned legacy documents
3. Preserve table structure (headers, spans) in exported data
4. Process large documents (300+ pages) in reasonable time

### 2.3 Business Context

- **Current state**: Internal tool, working but limited
- **Target state**: Production-ready internal tool with commercial potential
- **Competition**: Tabula, Adobe Acrobat, AWS Textract, Azure Document Intelligence

---

## 3. Goals and Non-Goals

### 3.1 Goals

| ID | Goal | Success Metric |
|----|------|----------------|
| G1 | Improve extraction accuracy | >90% cell accuracy on test set |
| G2 | Reduce processing time for born-digital PDFs | 5-10x speedup |
| G3 | Handle both born-digital and scanned PDFs | Automatic detection and routing |
| G4 | Provide fallback when primary extraction fails | <5% complete extraction failures |
| G5 | Preserve table structure in output | Support for merged cells, headers |

### 3.2 Non-Goals (Out of Scope)

| Item | Reason |
|------|--------|
| Manual correction UI | Adds 2+ months; focus on auto-extraction first |
| Cross-page table continuation | Complex edge case; defer to future version |
| OCR for handwritten content | Focus on printed/typed documents |
| Real-time streaming extraction | Batch processing is sufficient |
| Mobile app | Web interface is primary delivery |

---

## 4. Requirements

### 4.1 Functional Requirements

#### FR1: Page Classification
| ID | Requirement | Priority |
|----|-------------|----------|
| FR1.1 | System SHALL classify each PDF page as `born_digital`, `scanned`, or `mixed` | P0 |
| FR1.2 | Classification SHALL be based on text layer presence and quality | P0 |
| FR1.3 | Classification SHALL complete in <100ms per page | P1 |
| FR1.4 | Classification results SHALL be logged for debugging | P2 |

**Acceptance Criteria**:
- Born-digital: >90% of page content is extractable text
- Scanned: <10% extractable text, primarily image content
- Mixed: 10-90% extractable text, or text quality issues detected

#### FR2: Extraction Routing
| ID | Requirement | Priority |
|----|-------------|----------|
| FR2.1 | Born-digital pages SHALL route to direct PDF extraction (no image conversion) | P0 |
| FR2.2 | Scanned pages SHALL route to image-based detection pipeline | P0 |
| FR2.3 | Mixed pages SHALL attempt both paths and use best result | P1 |
| FR2.4 | Routing decisions SHALL be recorded in extraction metadata | P1 |

#### FR3: Multi-Extractor Support
| ID | Requirement | Priority |
|----|-------------|----------|
| FR3.1 | System SHALL support multiple extraction engines (Camelot Lattice, Camelot Stream, pdfplumber) | P0 |
| FR3.2 | System SHALL run multiple extractors per table region | P0 |
| FR3.3 | System SHALL score and rank extraction results | P0 |
| FR3.4 | System SHALL return the highest-scoring extraction | P0 |
| FR3.5 | System SHALL store extraction method used in output metadata | P1 |

#### FR4: Scoring Algorithm
| ID | Requirement | Priority |
|----|-------------|----------|
| FR4.1 | Scoring SHALL evaluate cell coverage (% of text captured) | P0 |
| FR4.2 | Scoring SHALL evaluate structure regularity (row/column consistency) | P0 |
| FR4.3 | Scoring SHALL evaluate numeric integrity (numbers parse correctly) | P1 |
| FR4.4 | Scoring SHALL evaluate header detection confidence | P1 |
| FR4.5 | Individual scores SHALL be weighted and combined into final score | P0 |

**Scoring Formula (initial)**:
```
final_score = (coverage * 0.3) + (regularity * 0.3) + (numeric * 0.2) + (headers * 0.2)
```

#### FR5: Scanned PDF Detection (Phase 3)
| ID | Requirement | Priority |
|----|-------------|----------|
| FR5.1 | System SHALL detect tables in scanned/image PDFs | P0 |
| FR5.2 | System SHALL use a modern detection model (Table Transformer, img2table, or PaddleOCR) | P0 |
| FR5.3 | System SHALL extract text via OCR for detected table regions | P0 |
| FR5.4 | System SHALL recover table structure (rows, columns, cells) from OCR output | P0 |

#### FR6: Rich Output Schema
| ID | Requirement | Priority |
|----|-------------|----------|
| FR6.1 | System SHALL output structured JSON with cell-level data | P0 |
| FR6.2 | Output SHALL include row spans and column spans | P0 |
| FR6.3 | Output SHALL identify header rows | P0 |
| FR6.4 | Output SHALL include confidence scores per cell | P1 |
| FR6.5 | System SHALL generate CSV, XLSX, JSON from structured output | P0 |
| FR6.6 | XLSX output SHALL preserve cell merges | P1 |

**Output Schema**:
```json
{
  "table_id": "page12_table3",
  "page_number": 12,
  "page_type": "born_digital",
  "extraction_method": "camelot-lattice",
  "confidence_score": 0.92,
  "bounding_box": {"x0": 72, "y0": 200, "x1": 540, "y1": 450},
  "header_rows": [0, 1],
  "row_count": 15,
  "column_count": 6,
  "cells": [
    {
      "row": 0,
      "column": 0,
      "row_span": 2,
      "col_span": 1,
      "text": "Region",
      "confidence": 0.98,
      "is_header": true
    }
  ]
}
```

### 4.2 Non-Functional Requirements

#### NFR1: Performance
| ID | Requirement | Target |
|----|-------------|--------|
| NFR1.1 | Born-digital page processing time | <2 seconds/page |
| NFR1.2 | Scanned page processing time | <10 seconds/page |
| NFR1.3 | 300-page document completion time | <15 minutes |
| NFR1.4 | Memory usage per worker | <2GB |
| NFR1.5 | Concurrent document processing | Support 5+ simultaneous |

#### NFR2: Reliability
| ID | Requirement | Target |
|----|-------------|--------|
| NFR2.1 | Complete extraction failure rate | <5% of documents |
| NFR2.2 | Per-table extraction success rate | >95% |
| NFR2.3 | System uptime | 99% |
| NFR2.4 | Graceful degradation on partial failures | Required |

#### NFR3: Accuracy
| ID | Requirement | Target |
|----|-------------|--------|
| NFR3.1 | Table detection recall (born-digital) | >95% |
| NFR3.2 | Table detection recall (scanned) | >85% |
| NFR3.3 | Cell content accuracy | >90% |
| NFR3.4 | Structure accuracy (rows/cols correct) | >85% |

#### NFR4: Maintainability
| ID | Requirement | Target |
|----|-------------|--------|
| NFR4.1 | Add new extractor without core changes | <1 day |
| NFR4.2 | Swap detection model without refactoring | Supported |
| NFR4.3 | Test coverage for extraction logic | >80% |

---

## 5. Technical Architecture

### 5.1 Current Architecture

```
┌─────────────────────────────────────────────────────────┐
│                     Current Flow                        │
└─────────────────────────────────────────────────────────┘

PDF Upload → pdf2image (all pages to JPG) → YOLO Detection → Camelot → CSV/JSON
                         ↑                        ↑            ↑
                    (bottleneck)             (hardcoded)   (single engine)
```

### 5.2 Target Architecture

```
┌─────────────────────────────────────────────────────────┐
│                     Target Flow                          │
└─────────────────────────────────────────────────────────┘

                                ┌─────────────────────────┐
                                │   Page Classifier       │
                                │   (PyMuPDF)             │
                                └──────────┬──────────────┘
                                           │
                    ┌──────────────────────┼───────────────────────┐
                    ▼                      ▼                       ▼
            ┌───────────┐          ┌───────────────┐       ┌───────────┐
            │ Born-     │          │ Mixed         │       │ Scanned   │
            │ Digital   │          │               │       │           │
            └─────┬─────┘          └───────┬───────┘       └─────┬─────┘
                  │                        │                     │
                  ▼                        ▼                     ▼
         ┌─────────────────┐       ┌──────────────┐      ┌──────────────────┐
         │ Direct PDF      │       │ Try Both     │      │ Image Detection  │
         │ Extraction      │       │ Paths        │      │ (Table Trans./   │
         │ (no image conv) │       │              │      │  PaddleOCR/etc)  │
         └────────┬────────┘       └──────┬───────┘      └────────┬─────────┘
                  │                       │                       │
                  └───────────────────────┼───────────────────────┘
                                          ▼
                              ┌───────────────────────┐
                              │   Multi-Extractor     │
                              │   Runner              │
                              │                       │
                              │  ┌─────────────────┐  │
                              │  │ Camelot Lattice │  │
                              │  │ Camelot Stream  │  │
                              │  │ pdfplumber      │  │
                              │  └─────────────────┘  │
                              └───────────┬───────────┘
                                          ▼
                              ┌───────────────────────┐
                              │   Scorer              │
                              │   (pick best result)  │
                              └───────────┬───────────┘
                                          ▼
                              ┌───────────────────────┐
                              │   Structured Output   │
                              │   (JSON schema)       │
                              └───────────┬───────────┘
                                          ▼
                              ┌───────────────────────┐
                              │   Export Formats      │
                              │   CSV / XLSX / JSON   │
                              └───────────────────────┘
```

### 5.3 Component Design

#### 5.3.1 Page Classifier

**File**: `api/scripts/page_classifier.py`

**Interface**:
```python
class PageClassifier:
    def classify(self, pdf_path: str, page_num: int) -> PageClassification:
        """
        Returns PageClassification with:
        - type: 'born_digital' | 'scanned' | 'mixed'
        - text_coverage: float (0-1)
        - has_images: bool
        - confidence: float (0-1)
        """
```

**Implementation approach**:
1. Use PyMuPDF to extract text blocks
2. Calculate text coverage ratio (text area / page area)
3. Check for image elements
4. Apply thresholds to classify

#### 5.3.2 Extractor Interface

**File**: `api/scripts/extractors/base.py`

```python
from abc import ABC, abstractmethod
from dataclasses import dataclass

@dataclass
class ExtractionResult:
    dataframe: pd.DataFrame
    confidence: float
    method: str
    metadata: dict

class BaseExtractor(ABC):
    @abstractmethod
    def extract(
        self,
        pdf_path: str,
        page_num: int,
        table_area: Optional[BoundingBox] = None
    ) -> List[ExtractionResult]:
        """Extract tables from a PDF page."""
        pass

    @abstractmethod
    def name(self) -> str:
        """Return extractor name for logging."""
        pass
```

#### 5.3.3 Concrete Extractors

**Camelot Extractor** (`api/scripts/extractors/camelot_extractor.py`):
- Wraps existing Camelot logic from `predict_table.py`
- Supports both `lattice` and `stream` flavors
- Returns confidence from Camelot's parsing report

**pdfplumber Extractor** (`api/scripts/extractors/pdfplumber_extractor.py`):
- Uses pdfplumber's table detection
- Better for borderless tables in some cases
- Simpler structure recovery

**Vision Extractor** (`api/scripts/extractors/vision_extractor.py`):
- For scanned PDFs
- Uses Table Transformer or PaddleOCR
- Includes OCR step for text extraction

#### 5.3.4 Scorer

**File**: `api/scripts/extractors/scorer.py`

```python
class ExtractionScorer:
    def score(self, result: ExtractionResult, page_text: str) -> float:
        """
        Score extraction quality on 0-1 scale.

        Components:
        - coverage_score: % of page text captured
        - regularity_score: consistency of row/column counts
        - numeric_score: parseable numbers are valid
        - header_score: header detection confidence
        """

    def select_best(self, results: List[ExtractionResult]) -> ExtractionResult:
        """Return highest-scoring result."""
```

### 5.4 File Structure Changes

```
api/scripts/
├── page_classifier.py          # NEW: Page type classification
├── table_extract.py            # MODIFY: Add routing logic
├── extractors/                 # NEW: Extractor module
│   ├── __init__.py
│   ├── base.py                 # Extractor interface
│   ├── camelot_extractor.py    # Camelot wrapper
│   ├── pdfplumber_extractor.py # pdfplumber wrapper
│   ├── vision_extractor.py     # For scanned PDFs
│   └── scorer.py               # Scoring algorithm
├── table_detector.py           # KEEP: Lattice/stream detection
├── header_processor.py         # KEEP: Header merging
└── YOLOV3/                     # DEPRECATE: Phase out over time
    └── ...
```

### 5.5 Database Schema Changes

**Modified Model**: `Extracted` → `ExtractedTable`

```python
class ExtractedTable(models.Model):
    report = models.ForeignKey(Report, on_delete=models.CASCADE)
    page_num = models.IntegerField()
    table_num = models.IntegerField()

    # Existing
    csv_file = models.FileField(...)
    json_file = models.FileField(...)
    xlsx_file = models.FileField(...)  # NEW

    # NEW fields
    page_type = models.CharField(max_length=20)  # born_digital, scanned, mixed
    extraction_method = models.CharField(max_length=50)  # camelot-lattice, etc
    confidence_score = models.FloatField()
    structure_json = models.JSONField()  # Rich schema with spans
    bounding_box = models.JSONField()  # x0, y0, x1, y1

    class Meta:
        ordering = ['page_num', 'table_num']
```

---

## 6. Dependencies

### 6.1 New Dependencies

| Package | Version | Purpose | License |
|---------|---------|---------|---------|
| pymupdf | >=1.23.0 | Page classification, text extraction | AGPL-3.0 |
| pdfplumber | >=0.10.0 | Alternative PDF extractor | MIT |
| openpyxl | >=3.1.0 | XLSX export with cell spans | MIT |

### 6.2 Optional Dependencies (Phase 3)

| Package | Version | Purpose | License |
|---------|---------|---------|---------|
| img2table | >=1.2.0 | Lightweight table detection | MIT |
| transformers | >=4.30.0 | Table Transformer model | Apache-2.0 |
| paddleocr | >=2.7.0 | PP-Structure pipeline | Apache-2.0 |

### 6.3 Dependency Considerations

**PyMuPDF License**: AGPL-3.0 requires open-sourcing if distributed. For commercial use:
- Option A: Open-source the tool
- Option B: Purchase commercial PyMuPDF license
- Option C: Use alternative (pypdf + custom text analysis)

---

## 7. Implementation Phases

### Phase 1: Page Classification + Routing (Week 1-2)

**Deliverables**:
- [ ] `page_classifier.py` with classification logic
- [ ] Integration into `table_extract.py` routing
- [ ] Unit tests for classifier
- [ ] Performance benchmarks

**Definition of Done**:
- Born-digital PDFs skip YOLO/image conversion
- Processing time reduced by 5x+ for born-digital
- All existing tests pass

### Phase 2: Multi-Extractor Framework (Week 3-5)

**Deliverables**:
- [ ] `extractors/` module with base class
- [ ] `camelot_extractor.py` (refactored from predict_table.py)
- [ ] `pdfplumber_extractor.py`
- [ ] `scorer.py` with scoring algorithm
- [ ] Integration tests

**Definition of Done**:
- Multiple extractors run per table
- Best result selected via scoring
- Accuracy improved on test set

### Phase 3: Scanned PDF Support (Week 6-8)

**Deliverables**:
- [ ] Selected vision model integrated
- [ ] `vision_extractor.py` with OCR
- [ ] Routing for scanned pages complete
- [ ] End-to-end tests with scanned samples

**Definition of Done**:
- Scanned PDFs extract successfully
- YOLO v3 can be disabled for new deployments

### Phase 4: Rich Output Schema (Week 9)

**Deliverables**:
- [ ] Database migration for new fields
- [ ] Structured JSON output
- [ ] XLSX export with cell spans
- [ ] API response updates

**Definition of Done**:
- Merged cells preserved in XLSX
- Header rows identified in output
- API returns confidence and method

---

## 8. Testing Strategy

### 8.1 Test Dataset

**Composition**:
- 10 born-digital annual reports (modern companies)
- 5 scanned annual reports (older documents)
- 5 mixed documents

**Sources**:
- SEC EDGAR filings
- UK Companies House
- International company reports

### 8.2 Test Types

| Type | Coverage | Tools |
|------|----------|-------|
| Unit tests | Classifier, scorer, extractors | pytest |
| Integration tests | Full extraction pipeline | pytest |
| Accuracy tests | Compare to ground truth | Custom scripts |
| Performance tests | Timing benchmarks | pytest-benchmark |

### 8.3 Accuracy Metrics

For each test document:
1. **Table Detection**: Count of tables found vs actual
2. **Cell Accuracy**: % of cells matching ground truth
3. **Structure Accuracy**: Row/column counts correct
4. **Processing Time**: Seconds per page

### 8.4 Ground Truth Creation

Manual annotation of test set:
- Mark table boundaries
- Transcribe cell contents
- Note merged cells, header rows

---

## 9. Rollout Plan

### 9.1 Migration Strategy

**Approach**: Parallel operation, gradual cutover

1. Deploy new extraction alongside old
2. Run both on new uploads, compare results
3. Log discrepancies for analysis
4. Switch default to new when confidence high
5. Remove old pipeline after validation period

### 9.2 Feature Flags

```python
EXTRACTION_FLAGS = {
    'use_page_classifier': True,       # Phase 1
    'use_multi_extractor': True,       # Phase 2
    'use_vision_detector': False,      # Phase 3 (gradual)
    'use_rich_schema': True,           # Phase 4
    'legacy_yolo_enabled': True,       # Fallback, disable later
}
```

### 9.3 Rollback Plan

If issues detected:
1. Disable feature flag
2. Revert to YOLO + Camelot path
3. Investigate and fix
4. Re-enable with fixes

---

## 10. Success Metrics

### 10.1 Launch Criteria (MVP)

| Metric | Target | Measurement |
|--------|--------|-------------|
| Born-digital speedup | 5x faster | Benchmark comparison |
| Accuracy improvement | +5% cell accuracy | Test set comparison |
| No regressions | 0 failures on current test set | Automated tests |

### 10.2 Post-Launch Metrics

| Metric | Target | Timeframe |
|--------|--------|-----------|
| Extraction success rate | >95% | 30 days |
| User-reported issues | <10% of uploads | 30 days |
| Processing time p95 | <5 min for 100-page doc | 30 days |

---

## 11. Risks and Mitigations

| Risk | Probability | Impact | Mitigation |
|------|-------------|--------|------------|
| PyMuPDF AGPL licensing | Medium | High | Evaluate commercial license or alternatives |
| Multi-extractor slows processing | Medium | Medium | Run extractors in parallel, cache results |
| Scorer picks wrong result | Medium | Medium | Tune weights, add human review option later |
| Vision models require GPU | Low | Medium | Support CPU fallback, consider cloud GPU |
| Breaking changes to existing API | Low | High | Version API, maintain backwards compatibility |

---

## 12. Future Considerations (v3.0+)

Items deferred from this version:
- Manual correction UI with table editor
- Cross-page table continuation detection
- Confidence threshold for human review routing
- Active learning from corrections
- Document structure extraction (TOC, sections)
- Streaming extraction for very large documents

---

## 13. Appendix

### A. Glossary

| Term | Definition |
|------|------------|
| Born-digital | PDF created from digital source (Word, Excel), has embedded text |
| Scanned | PDF created from scanning physical paper, primarily image content |
| Lattice | Camelot extraction mode for tables with visible borders |
| Stream | Camelot extraction mode for tables without visible borders |
| Table Transformer | Microsoft's deep learning model for table detection and structure |

### B. References

- [Camelot Documentation](https://camelot-py.readthedocs.io/)
- [pdfplumber Documentation](https://github.com/jsvine/pdfplumber)
- [PyMuPDF Documentation](https://pymupdf.readthedocs.io/)
- [Table Transformer Paper](https://arxiv.org/abs/2110.00061)
- [PaddleOCR PP-Structure](https://github.com/PaddlePaddle/PaddleOCR)

### C. Current Codebase Reference

| Component | File Path |
|-----------|-----------|
| Main orchestrator | `api/scripts/table_extract.py` |
| Per-page detection | `api/scripts/YOLOV3/predict_table.py` |
| YOLO inference | `api/scripts/YOLOV3/utils/detect_func.py` |
| Table type detection | `api/scripts/table_detector.py` |
| Header processing | `api/scripts/header_processor.py` |
| Data models | `api/models.py` |
| REST endpoints | `api/views.py` |
| Async tasks | `api/tasks.py` |
