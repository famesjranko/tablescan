# FEATURE: Post-Detection Validation

## Overview

Add a validation layer after YOLO table detection to filter out false positives (infographics, image grids, numbered lists) before presenting results to users in the book viewer.

**Status**: Revised
**Created**: 2026-03-12
**Revised**: 2026-03-12
**Related Issue**: Multi-page ASIC report detecting infographics as tables

---

## Problem Statement

The YOLO model detects rectangular structured regions as tables. This works well for actual tables but produces false positives for:

- Infographics with numbered sections (01, 02, 03...)
- Image grids with captions
- Structured layouts that aren't tabular data
- Card-based content layouts

Users in "Auto + Review" mode see these false detections and must manually reject them, degrading the UX.

---

## Current System Architecture

Understanding the existing flow is critical for choosing the right validation approach.

### Detection-to-Extraction Flow

```
1. YOLO Detection (detect_table_regions in predict_table.py:842-903)
   └── Converts PDF page to JPG, runs YOLOv3 inference at 30% confidence
   └── Returns bounding boxes as percentage coordinates (0-100)
   └── NO Camelot, NO database writes, detection only

2. Review Task (detect_tables_for_review in tasks.py:115-243)
   └── Calls detect_table_regions() for each page
   └── Creates TableSelection records with status='pending', source='yolo'
   └── Detection is PAGE-SERIAL (tasks.py:168) - one page at a time

3. Book Viewer
   └── User sees ALL pending YOLO detections
   └── User approves, rejects, or draws manual selections
   └── Approved selections get status='approved'

4. Extraction (extract_from_selections in tasks.py:247-480)
   └── Gets all approved selections
   └── Calls extract_from_manual_areas() for each page
   └── Uses MultiExtractor (Camelot lattice + stream + pdfplumber)
   └── Existing tableValidate() checks >= 2 rows && >= 2 cols
```

### Key Code References

| Component | Location | Purpose |
|-----------|----------|---------|
| `detect_table_regions()` | predict_table.py:842-903 | YOLO-only detection, returns percentage coords |
| `detect_tables_for_review()` | tasks.py:115-243 | Celery task, creates TableSelection records |
| `extract_from_manual_areas()` | predict_table.py:949-1067 | Extraction with MultiExtractor |
| `tableValidate()` | predict_table.py:176-187 | Validates `>= 2 rows && >= 2 cols` |
| `MultiExtractor` | extractors/multi_extractor.py | Runs Camelot lattice + stream + pdfplumber |
| `CamelotExtractor._is_valid_table()` | extractors/camelot_extractor.py:163-176 | Same 2x2 validation |
| `detect_table_type_from_array()` | table_detector.py:79-157 | OpenCV line detection (flavor classifier) |
| `conf_thres` | detect_func.py:177 | YOLO confidence threshold (hardcoded 0.30) |

---

## Analysis: Why CamelotValidator as Phase 1 is Problematic

The original proposal recommended CamelotValidator as the initial implementation. After detailed analysis, this approach has significant issues:

### Issue 1: Architectural Mismatch (Critical)

The extraction path **intentionally avoids tight region constraints** because they can clip headers:

```python
# From predict_table.py:961-967
"""
Unlike passing table_areas directly to extractors (which constrains extraction
too tightly and can clip headers), this function lets MultiExtractor auto-detect
tables on the page, then filters results to only include tables that overlap
with the user's selection areas.
"""
```

**Impact:** A region-scoped Camelot validator could **reject regions that full-page extraction would recover successfully**. The validator uses constrained `table_areas`, but extraction deliberately avoids them.

### Issue 2: Logic Duplication

Camelot + 2x2 validation **already runs during extraction**:

1. `tableValidate()` at predict_table.py:176 checks `>= 2 rows && >= 2 cols`
2. MultiExtractor runs both `CamelotExtractor('lattice')` and `CamelotExtractor('stream')`
3. `CamelotExtractor._is_valid_table()` applies the same 2x2 check

Adding CamelotValidator at detection time means parsing the same PDF regions twice with identical logic.

### Issue 3: Performance Cost at Wrong Time

| Factor | Impact |
|--------|--------|
| Camelot lattice | ~0.3-0.5s per region |
| Camelot stream | ~0.5-1.0s per region |
| **Total per region** | ~0.8-1.5s |
| Detection is page-serial | Latency multiplies per page |
| 10-page doc, 5 false positives/page | **40-75 seconds added** |

This runs at upload time when the user is actively waiting.

### Issue 4: Weak Semantic Test

The `stream` + `>=2x2` test is semantically weak:

- Aligned infographic text can form 2+ rows
- Image captions can form 2+ columns
- Card layouts with text can plausibly pass

You pay the latency and may still keep false positives.

### Issue 5: Lost Observability

Hard `filter` mode removes regions before they become TableSelection records:

- Filtered regions are never stored in the database
- You lose the ability to compare validator decisions against user decisions
- No data to train or improve the validator over time
- Cannot A/B test validator accuracy

**Recommendation:** Use `mark` mode initially, or store filtered regions with a `filtered` status.

### Issue 6: Bounding Box Format Inconsistency

The codebase has inconsistent bbox key naming that any validator/observability layer must handle:

| Location | Key Used |
|----------|----------|
| `extract_from_manual_areas()` | Looks for `bbox` or `_bbox` |
| `CamelotExtractor` | Emits `bounding_box` |
| `PdfplumberExtractor` | Emits `bounding_box` |
| `VisionExtractor` | Emits `bounding_box` |
| `_normalize_bbox()` in table_extract.py | Handles both formats |

**Requirement:** Establish canonical bbox format as part of rollout. Recommend standardizing on `bounding_box` with keys `{x1, y1, x2, y2}`.

### Issue 7: `mark` Mode Requires DB/API/UI Work

The `mark` strategy is **not currently wired through the stack**:

- `TableSelection` model only has statuses: `pending`, `approved`, `rejected`, `failed`
- Serializer doesn't expose validation metadata
- View only allows PATCHing `status` field
- Book viewer treats only `source='yolo' && status='pending'` as reviewable

**Impact:** If `mark` just keeps bad detections as `pending`, UX is unchanged. If it introduces a new state (e.g., `low_confidence`), DB/API/UI plumbing is **required**, not optional.

---

## Revised Implementation Order

Keep the pluggable architecture (it's well-designed), but change the implementation phases:

### Phase 1: YOLO Confidence Threshold (Quick Win)

**Current:** `conf_thres = 0.30` hardcoded in `detect_func.py:177`

```python
class parameters:
    def __init__(self, img):
        ...
        self.conf_thres = 0.30  # <- Hardcoded
```

**Action:**
1. Make threshold configurable via Django settings
2. Pass threshold from predict_table.py into parameters() (don't make YOLO utils read Django settings)
3. Benchmark 0.35 and 0.40 against the ASIC report
4. Save before/after detection results for comparison

**Why First:**
- Zero architecture changes
- ~2 hours effort
- False positives (infographics) likely have lower confidence than real tables
- Comments in code suggest "very good at 30%" and "very good at 40%" for different weights

**Implementation Pattern:**

```python
# tablescan/settings.py
YOLO_DETECTION = {
    'confidence_threshold': 0.35,  # Previously hardcoded 0.30
}

# api/scripts/YOLOV3/utils/detect_func.py
class parameters:
    def __init__(self, img, conf_thres=0.30):  # Accept as parameter
        ...
        self.conf_thres = conf_thres  # Use passed value

# api/scripts/YOLOV3/predict_table.py
from django.conf import settings

def detect_table_regions(file_path: str, page_number: int) -> List[dict]:
    ...
    # Get threshold from settings with safe default
    conf_threshold = getattr(settings, 'YOLO_DETECTION', {}).get('confidence_threshold', 0.30)
    opt = parameters(img_path, conf_thres=conf_threshold)
    ...
```

This keeps the YOLO utility decoupled from Django while allowing configuration.

### Phase 2: Geometric Scoring (Not Hard Filtering)

Add geometric metrics as **confidence adjustments**, not hard filters. This is critical because MultiExtractor explicitly supports borderless tables (runs `lattice`, `stream`, AND `pdfplumber`), so compact or borderless tables are first-class use cases.

```python
def detect_table_regions(file_path: str, page_number: int) -> List[dict]:
    # ... existing YOLO detection ...

    regions = []
    for bbox in output:
        confidence = bbox[5] if len(bbox) > 5 else 0.5
        [x1_norm, y1_norm, x2_norm, y2_norm] = norm_bbox(img, bbox)

        # Calculate geometric metrics
        width = x2_norm - x1_norm
        height = y2_norm - y1_norm
        area = width * height
        aspect_ratio = width / height if height > 0 else 0

        # Geometric scoring (adjust confidence, don't filter)
        geo_adjustment = 0.0
        geo_flags = []

        if area < 0.03:  # Very small
            geo_adjustment -= 0.15
            geo_flags.append('small_area')
        if area > 0.95:  # Page-sized
            geo_adjustment -= 0.20
            geo_flags.append('large_area')
        if 0.85 < aspect_ratio < 1.15:  # Very square
            geo_adjustment -= 0.10
            geo_flags.append('square')
        if width < 0.10 or height < 0.05:  # Very narrow
            geo_adjustment -= 0.10
            geo_flags.append('narrow')

        adjusted_confidence = max(0.0, min(1.0, confidence + geo_adjustment))

        regions.append({
            'x1': x1_norm * 100,
            'y1': y1_norm * 100,
            'x2': x2_norm * 100,
            'y2': y2_norm * 100,
            'confidence': adjusted_confidence,
            'raw_confidence': confidence,
            'geo_flags': geo_flags,
        })

    return regions
```

**Why Scoring, Not Filtering:**
- Borderless tables are legitimate use cases in this codebase
- Hard rejection risks false negatives on compact tables
- Scoring preserves all detections while surfacing quality signals
- Can promote to hard filtering **after** recall data confirms safety

**When to Graduate to Hard Filtering:**
After benchmarking on the ASIC report AND known-good borderless tables, promote specific flags to hard filters if they show zero false negatives.

### Phase 3: Pluggable Validator Architecture

Create the extensible validator framework:

```python
# api/scripts/validators.py

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import List, Dict, Optional

@dataclass
class ValidationMetrics:
    """Metrics for validator decisions and observability."""
    horizontal_lines: int = 0
    vertical_lines: int = 0
    edge_density: float = 0.0
    text_density: float = 0.0
    grid_score: float = 0.0

@dataclass
class ValidationResult:
    is_valid: bool
    confidence_adjustment: float  # -1.0 to +1.0
    reason: str                   # Machine-readable code
    message: str                  # Human-readable explanation
    metrics: ValidationMetrics    # Observability data

class RegionValidator(ABC):
    """Base class for all validators."""

    @abstractmethod
    def validate(self, pdf_path: str, page_num: int,
                 region: dict, image: np.ndarray = None) -> ValidationResult:
        """Validate a single region."""
        pass

    @abstractmethod
    def name(self) -> str:
        """Validator identifier for logging."""
        pass

class CompositeValidator(RegionValidator):
    """Chains multiple validators with configurable logic."""

    def __init__(self, validators: List[RegionValidator],
                 mode: str = 'all'):  # 'all', 'any', 'weighted'
        self.validators = validators
        self.mode = mode
```

### Phase 4: OpenCV Score-Based Validator (Refactor Required)

**Important:** The existing OpenCV code is a **flavor classifier**, not a validator:

```python
# Current behavior (table_detector.py:79-157)
def detect_table_type_from_array(img_array, min_lines=2) -> str:
    # Always returns "lattice" or "stream" - never "invalid"
    # On failure paths, defaults to "lattice"
    if img_array is None:
        return "lattice"  # <- Default, not validation
    ...
    if horizontal_lines >= min_lines and vertical_lines >= min_lines:
        return "lattice"
    return "stream"  # <- Always returns something
```

**Refactor to return metrics:**

```python
# api/scripts/validators.py

@dataclass
class GridAnalysis:
    """Detailed grid structure analysis."""
    horizontal_lines: int
    vertical_lines: int
    edge_density: float
    intersection_count: int
    has_grid_structure: bool
    confidence: float  # 0.0 to 1.0

def analyze_grid_structure(img_array: np.ndarray) -> GridAnalysis:
    """
    Analyze image for grid/table structure.
    Returns metrics instead of just flavor classification.
    """
    if img_array is None:
        return GridAnalysis(0, 0, 0.0, 0, False, 0.0)

    # Convert to grayscale
    if len(img_array.shape) == 3:
        img = cv2.cvtColor(img_array, cv2.COLOR_RGB2GRAY)
    else:
        img = img_array

    # Edge detection
    blurred = cv2.GaussianBlur(img, (3, 3), 0)
    edges = cv2.Canny(blurred, 50, 150, apertureSize=3)
    edge_density = np.count_nonzero(edges) / edges.size

    # Line detection
    lines = cv2.HoughLinesP(edges, 1, np.pi/180, 100,
                            minLineLength=50, maxLineGap=10)

    horizontal = 0
    vertical = 0
    if lines is not None:
        for line in lines:
            x1, y1, x2, y2 = line[0]
            angle = abs(np.degrees(np.arctan2(y2-y1, x2-x1)))
            if angle < 15:
                horizontal += 1
            elif angle > 75:
                vertical += 1

    # Calculate confidence
    has_grid = horizontal >= 2 and vertical >= 2
    confidence = min(1.0, (horizontal + vertical) / 10) if has_grid else 0.0

    return GridAnalysis(
        horizontal_lines=horizontal,
        vertical_lines=vertical,
        edge_density=edge_density,
        intersection_count=min(horizontal, vertical),
        has_grid_structure=has_grid,
        confidence=confidence
    )

class OpenCVValidator(RegionValidator):
    """Fast validation using OpenCV line detection."""

    def __init__(self, min_lines: int = 2, min_confidence: float = 0.3):
        self.min_lines = min_lines
        self.min_confidence = min_confidence

    def validate(self, pdf_path, page_num, region, image=None) -> ValidationResult:
        if image is None:
            # Extract region from page image
            image = self._extract_region_image(pdf_path, page_num, region)

        analysis = analyze_grid_structure(image)

        is_valid = (analysis.has_grid_structure and
                   analysis.confidence >= self.min_confidence)

        return ValidationResult(
            is_valid=is_valid,
            confidence_adjustment=analysis.confidence - 0.5,
            reason='grid_detected' if is_valid else 'no_grid_structure',
            message=f"Found {analysis.horizontal_lines}H x {analysis.vertical_lines}V lines",
            metrics=ValidationMetrics(
                horizontal_lines=analysis.horizontal_lines,
                vertical_lines=analysis.vertical_lines,
                edge_density=analysis.edge_density,
                grid_score=analysis.confidence
            )
        )

    def name(self) -> str:
        return 'opencv'
```

**Performance comparison:**
| Validator | Time per Region | Accuracy |
|-----------|-----------------|----------|
| OpenCV | ~50ms | Good for bordered tables |
| Camelot | ~800-1500ms | Better semantic understanding |

**Critical: Start as Scoring, Not Rejection**

The `is_valid` field should initially be used for **telemetry and UI hints only**, not hard filtering. Because this codebase explicitly supports borderless tables (MultiExtractor runs stream mode), `no_grid_structure` does NOT mean "not a table".

Initial rollout:
1. Log all validation results with metrics
2. Surface low-confidence detections visually in book viewer (e.g., lighter border color)
3. Collect user approval/rejection data against validator predictions
4. **After** confirming no false negatives on borderless tables, graduate specific patterns to hard filtering

### Phase 5: CamelotValidator (Fallback Only)

Only implement CamelotValidator if Phases 1-4 are insufficient:

```python
class CamelotValidator(RegionValidator):
    """
    Heavy-weight validation using Camelot table detection.
    Use as fallback when faster validators are inconclusive.

    WARNING: This validator has known issues:
    - Region-scoped extraction can clip headers
    - Extraction path uses full-page detection intentionally
    - ~20x slower than OpenCV
    """

    def __init__(self, min_rows: int = 2, min_cols: int = 2,
                 timeout: float = 5.0):
        self.min_rows = min_rows
        self.min_cols = min_cols
        self.timeout = timeout

    def validate(self, pdf_path, page_num, region, image=None) -> ValidationResult:
        # Convert percentage coords to Camelot format
        # ... coordinate conversion ...

        # Try lattice first (faster, more reliable)
        try:
            tables = camelot.read_pdf(
                pdf_path,
                pages=str(page_num),
                flavor='lattice',
                table_areas=[area_str]
            )
            if self._is_valid_structure(tables):
                return ValidationResult(
                    is_valid=True,
                    confidence_adjustment=0.2,
                    reason='lattice_found_structure',
                    message=f"Lattice found {len(tables)} table(s)",
                    metrics=self._build_metrics(tables)
                )
        except Exception as e:
            pass  # Fall through to stream

        # Try stream (slower, handles borderless)
        try:
            tables = camelot.read_pdf(
                pdf_path,
                pages=str(page_num),
                flavor='stream',
                table_areas=[area_str]
            )
            if self._is_valid_structure(tables):
                return ValidationResult(
                    is_valid=True,
                    confidence_adjustment=0.1,
                    reason='stream_found_structure',
                    message=f"Stream found {len(tables)} table(s)",
                    metrics=self._build_metrics(tables)
                )
        except Exception:
            pass

        return ValidationResult(
            is_valid=False,
            confidence_adjustment=-0.3,
            reason='no_table_structure',
            message="Neither lattice nor stream found valid structure",
            metrics=ValidationMetrics()
        )
```

---

## Configuration

```python
# tablescan/settings.py

YOLO_DETECTION = {
    'confidence_threshold': 0.35,  # Phase 1: was 0.30
}

DETECTION_VALIDATION = {
    # Master switch
    'enabled': True,

    # Geometric pre-filters (Phase 2)
    'geometric': {
        'min_area': 0.03,      # 3% of page
        'max_area': 0.95,      # 95% of page
        'min_aspect_ratio': 0.5,   # width/height
        'max_aspect_ratio': 4.0,
        'min_width': 0.10,     # 10% of page width
        'min_height': 0.05,    # 5% of page height
    },

    # Validator selection (Phase 3+)
    'validator': 'opencv',  # Options: 'none', 'opencv', 'camelot', 'composite'

    # What to do with invalid regions
    'strategy': 'mark',  # 'filter' or 'mark' - use 'mark' initially for observability

    # OpenCV validator settings (Phase 4)
    'opencv': {
        'min_lines': 2,
        'min_confidence': 0.3,
    },

    # Camelot validator settings (Phase 5, fallback)
    'camelot': {
        'min_rows': 2,
        'min_cols': 2,
        'try_lattice': True,
        'try_stream': True,
        'timeout_seconds': 5,
    },

    # General settings
    'fail_open': True,  # On error, pass region through
}
```

---

## Integration Points

### 1. detect_table_regions() in predict_table.py

Primary integration point with phased rollout:

```python
def detect_table_regions(file_path: str, page_number: int,
                         validate: bool = True) -> List[dict]:
    # ... existing YOLO detection code ...

    regions = []
    for bbox in output:
        confidence = bbox[5] if len(bbox) > 5 else None
        [x1_norm, y1_norm, x2_norm, y2_norm] = norm_bbox(img, bbox)

        # Phase 2: Geometric pre-filters
        if settings.DETECTION_VALIDATION['enabled']:
            geo = settings.DETECTION_VALIDATION['geometric']
            width = x2_norm - x1_norm
            height = y2_norm - y1_norm
            area = width * height
            aspect = width / height if height > 0 else 0

            if area < geo['min_area'] or area > geo['max_area']:
                continue
            if aspect < geo['min_aspect_ratio'] or aspect > geo['max_aspect_ratio']:
                continue
            if width < geo['min_width'] or height < geo['min_height']:
                continue

        regions.append({
            'x1': x1_norm * 100,
            'y1': y1_norm * 100,
            'x2': x2_norm * 100,
            'y2': y2_norm * 100,
            'confidence': confidence,
        })

    # Phase 3+: Pluggable validation
    if validate and settings.DETECTION_VALIDATION['enabled']:
        validator_type = settings.DETECTION_VALIDATION['validator']
        if validator_type != 'none':
            regions = validate_regions(file_path, page_number, regions, img)

    return regions
```

### 2. New module: api/scripts/validators.py

Contains all validator classes, metrics, and factory functions.

### 3. Refactor: api/scripts/table_detector.py

Change from flavor classifier to metrics producer:
- Keep existing `detect_table_type()` for backward compatibility
- Add new `analyze_grid_structure()` returning GridAnalysis
- OpenCVValidator uses the new metrics function

### 4. Database: Optional Enhancement

For observability in `mark` mode:

```python
# api/models.py (optional future enhancement)
class TableSelection(models.Model):
    # ... existing fields ...
    validation_status = models.CharField(
        max_length=20,
        choices=[('passed', 'Passed'), ('failed', 'Failed'), ('skipped', 'Skipped')],
        null=True, blank=True
    )
    validation_reason = models.CharField(max_length=50, null=True, blank=True)
    validation_metrics = models.JSONField(null=True, blank=True)
```

---

## Testing Plan

### Phase 1 Tests: Confidence Threshold

```python
def test_yolo_threshold_configurable(self):
    # Given: settings with higher threshold
    with override_settings(YOLO_DETECTION={'confidence_threshold': 0.40}):
        # When: detection runs
        regions = detect_table_regions(test_pdf, 1)

        # Then: only high-confidence regions returned
        for region in regions:
            self.assertGreaterEqual(region['confidence'], 0.40)
```

### Phase 2 Tests: Geometric Filters

```python
def test_filters_tiny_regions(self):
    # Given: a region < 3% page area
    # When: geometric filter runs
    # Then: region is excluded

def test_filters_very_square_regions(self):
    # Given: a region with aspect ratio ~1.0
    # When: geometric filter runs
    # Then: region is excluded

def test_passes_normal_table_dimensions(self):
    # Given: a region with typical table dimensions
    # When: geometric filter runs
    # Then: region is included
```

### Phase 4 Tests: OpenCV Validator

```python
def test_opencv_detects_bordered_table(self):
    # Given: image of bordered table
    analysis = analyze_grid_structure(table_image)

    # Then: finds grid structure
    self.assertTrue(analysis.has_grid_structure)
    self.assertGreaterEqual(analysis.horizontal_lines, 2)
    self.assertGreaterEqual(analysis.vertical_lines, 2)

def test_opencv_rejects_infographic(self):
    # Given: image of infographic
    analysis = analyze_grid_structure(infographic_image)

    # Then: no grid structure
    self.assertFalse(analysis.has_grid_structure)
```

### Integration Tests

```python
def test_asic_report_infographics_filtered(self):
    # Given: ASIC report with infographics on pages 7-10
    # When: detection runs with validation
    # Then: infographic pages return 0 detections

def test_asic_report_tables_preserved(self):
    # Given: ASIC report with actual tables
    # When: detection runs with validation
    # Then: table pages return expected detections
```

---

## Rollout Plan

| Phase | Deliverables | Effort | Risk |
|-------|--------------|--------|------|
| 1 | Configurable YOLO threshold + benchmark harness + saved before/after results | 2 hours | Low |
| 1.5 | Canonical bbox format standardization (`bounding_box` with `{x1,y1,x2,y2}`) | 2 hours | Low |
| 2 | Geometric **scoring** (not filtering) in detect_table_regions() | 3 hours | Low |
| 3 | Validator base classes, CompositeValidator, ValidationMetrics | 4 hours | Low |
| 3.5 | DB/API/UI plumbing for `mark` mode (if using mark strategy) | 1 day | Medium |
| 4 | Refactored OpenCV + OpenCVValidator (scoring mode initially) | 1 day | Medium |
| 5 | CamelotValidator (fallback/debug only) | 1 day | Medium |
| 6 | Graduate scoring to filtering after recall data confirms safety | Ongoing | Low |

**Key Principles:**
- Ship threshold + scoring first, measure impact before any hard rejection
- DB/API/UI work for `mark` mode is **required** if using that strategy, not optional
- Collect recall data on borderless tables before graduating any filter to hard rejection
- Keep Camelot as fallback/debug validator only

---

## File Changes Summary

| File | Change |
|------|--------|
| `api/scripts/YOLOV3/utils/detect_func.py:177` | Accept `conf_thres` as parameter |
| `api/scripts/YOLOV3/predict_table.py:870` | Pass threshold from settings to parameters() |
| `api/scripts/YOLOV3/predict_table.py:884-901` | Add geometric scoring (confidence adjustments) |
| `api/scripts/validators.py` | **New** - Validator interface + implementations |
| `api/scripts/extractors/*.py` | Standardize bbox key to `bounding_box` |
| `api/models.py` | Add `validation_status`, `validation_metrics` fields (if using mark mode) |
| `api/serializers.py` | Expose validation fields (if using mark mode) |
| `api/scripts/table_detector.py` | Refactor to return metrics (keep backward compat) |
| `tablescan/settings.py` | Add `YOLO_DETECTION` and `DETECTION_VALIDATION` config |
| `api/tests/test_validators.py` | **New** - Unit tests for validators |

---

## Success Metrics

| Metric | Target | Measurement |
|--------|--------|-------------|
| False positives on ASIC infographics | 0 detections | Manual test on pages 7-10 |
| True positive preservation | No regression | A/B test on known good tables |
| Detection latency | < 2s added per page | Performance benchmark |
| Validator accuracy | > 90% agreement with user decisions | Compare against rejection rate |

---

## Open Questions (Resolved)

| Question | Resolution |
|----------|------------|
| CamelotValidator first? | No - architectural mismatch with extraction path |
| Can we use existing OpenCV? | Needs refactoring from classifier to metrics |
| Filter vs mark strategy? | Start with `mark` for observability |
| Async validation? | Not needed if using fast validators |
| Store validation results? | Yes, for observability and improvement |

---

## Appendix: Architectural Decisions

### Why Not CamelotValidator First

1. **Extraction path mismatch**: `extract_from_manual_areas()` intentionally uses full-page extraction to avoid clipping headers. Region-scoped Camelot validation uses a different strategy.

2. **Logic duplication**: `tableValidate()` and `CamelotExtractor._is_valid_table()` already implement the same 2x2 check during extraction.

3. **Latency**: 0.8-1.5s per region in a serial detection loop is unacceptable for multi-page documents.

4. **Weak semantics**: The `stream >= 2x2` test can still pass many non-tables (aligned text, captions, card layouts).

### Why Geometric Filters First

1. **Zero latency**: Simple arithmetic, ~0ms per region
2. **Clear heuristics**: Tables have predictable dimensions
3. **Safe defaults**: Conservative thresholds avoid false negatives
4. **Complementary**: Works alongside any other validator

### Why Refactor OpenCV

The existing `detect_table_type_from_array()` always returns a valid flavor - it's designed for extraction routing, not validation. A proper validator needs:

1. Metrics (line counts, density) for confidence scoring
2. A true "invalid" state for regions without grid structure
3. Observability data for debugging and improvement
