# FEATURE: Post-Detection Validation

## Overview

Add a validation step after YOLO table detection to filter out false positives (infographics, image grids, numbered lists) before presenting results to users in the book viewer.

**Status**: Scoped
**Created**: 2026-03-12
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

## Solution

Add a pluggable validation layer between YOLO detection and result presentation. The validator checks if detected regions contain actual tabular structure before returning them.

```
PDF Page
    │
    ▼
┌─────────────────┐
│ YOLO Detection  │  ← Finds rectangular structured regions
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│   Validation    │  ← Verifies actual table structure exists
│    (new step)   │
└────────┬────────┘
         │
         ▼
  Validated Regions  → Book Viewer
```

---

## Design Principles

### 1. Pluggable Architecture

Validators implement a common interface. The system can swap validators or chain multiple validators without changing detection code.

```python
class RegionValidator(ABC):
    @abstractmethod
    def validate(self, pdf_path, page_num, region) -> ValidationResult
```

### 2. Configurable Behavior

- Enable/disable validation via settings
- Choose validation strategy (filter vs mark)
- Adjust thresholds per validator

### 3. Fail-Safe Defaults

- Validation errors should not block detection
- If validator fails, region passes through (fail-open)
- Invalid regions can be kept with low-confidence flag rather than filtered

---

## Validation Strategies

### Strategy A: Filter Invalid (Default)

Remove regions that fail validation. Users only see high-confidence detections.

**Pros**: Cleaner UX, fewer false positives to reject
**Cons**: May filter out legitimate edge-case tables

### Strategy B: Mark Invalid

Keep all regions but mark validation status. UI can show visual indicators.

**Pros**: No data loss, user makes final decision
**Cons**: More clutter, doesn't solve the core UX problem

### Recommendation

Start with **Strategy A** (filter) but make it configurable. Users who need maximum recall can switch to Strategy B.

---

## Validator Implementations

### Phase 1: CamelotValidator (Initial Implementation)

Uses Camelot's table detection to verify structure exists.

**Logic:**
1. Convert region coordinates to Camelot format
2. Try `lattice` flavor (detects bordered tables)
3. If no result, try `stream` flavor (detects borderless tables)
4. Valid if either finds >= 2 rows AND >= 2 columns

**Why Camelot?**
- Already a project dependency
- Battle-tested table detection
- Handles both bordered and borderless tables
- Returns actual structure metrics (rows, cols)

**Camelot Modes:**

| Mode | Detects | Speed | False Positives |
|------|---------|-------|-----------------|
| Lattice | Tables with visible gridlines | Fast | Low |
| Stream | Tables aligned by whitespace | Medium | Medium |

**Validation Flow:**
```
Region
  │
  ├──► Lattice check ──► Found structure? ──► Valid ✓
  │                              │
  │                              ▼ No
  │
  └──► Stream check ──► Found structure? ──► Valid ✓
                               │
                               ▼ No

                        Invalid ✗
```

### Phase 2: Future Validators (Not in Initial Scope)

These can be added later without architecture changes:

**LineDetectionValidator**
- Uses OpenCV to detect grid lines
- Fast, doesn't require PDF parsing
- Good for quick pre-filtering

**TextDensityValidator**
- Analyzes text-to-image ratio in region
- Infographics have high image density
- Tables have high text density

**AspectRatioValidator**
- Filters very square regions (often icons/images)
- Tables typically have width > height

**CompositeValidator**
- Chains multiple validators
- Configurable AND/OR logic
- Weighted scoring across validators

---

## Data Structures

### ValidationResult

```python
@dataclass
class ValidationResult:
    is_valid: bool
    confidence_adjustment: float  # -1.0 to +1.0, applied to YOLO confidence
    reason: str                   # Machine-readable reason code
    message: str                  # Human-readable explanation
    metadata: dict                # Validator-specific data
```

**Reason Codes:**
- `lattice_found_structure` - Lattice mode found table
- `stream_found_structure` - Stream mode found table
- `no_table_structure` - Neither mode found structure
- `insufficient_rows` - Found structure but < min rows
- `insufficient_cols` - Found structure but < min cols
- `validation_error` - Validator encountered an error
- `validation_skipped` - Validation disabled or bypassed

### Region (Extended)

```python
{
    'x1': float,           # Existing: percentage coords
    'y1': float,
    'x2': float,
    'y2': float,
    'confidence': float,   # Existing: YOLO confidence
    'validated': bool,     # New: passed validation?
    'validation_reason': str,  # New: reason code
    'validation_meta': dict,   # New: rows_found, cols_found, etc.
}
```

---

## Configuration

### Settings Structure

```python
# In settings.py or dedicated config

DETECTION_VALIDATION = {
    # Master switch
    'enabled': True,

    # Which validator to use
    'validator': 'camelot',  # Options: 'camelot', 'composite', 'none'

    # What to do with invalid regions
    'strategy': 'filter',  # Options: 'filter', 'mark'

    # CamelotValidator settings
    'camelot': {
        'min_rows': 2,
        'min_cols': 2,
        'try_lattice': True,
        'try_stream': True,
        'timeout_seconds': 5,  # Per-region timeout
    },

    # Performance settings
    'parallel': False,  # Validate regions in parallel
    'fail_open': True,  # On error, pass region through
}
```

### Runtime Override

Allow per-request override for testing:
```python
detect_table_regions(file_path, page_num, validate=True, validator_config={...})
```

---

## Integration Points

### 1. detect_table_regions() in predict_table.py

Primary integration point. Add validation after YOLO inference, before returning regions.

```python
def detect_table_regions(file_path: str, page_number: int,
                         validate: bool = True) -> List[dict]:
    # ... existing YOLO detection code ...

    regions = []
    for bbox in output:
        regions.append({...})

    # NEW: Validation step
    if validate and settings.DETECTION_VALIDATION['enabled']:
        regions = validate_regions(file_path, page_number, regions)

    return regions
```

### 2. New module: api/scripts/validators.py

Contains all validator classes and factory function.

```python
# validators.py

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import List, Dict, Optional

@dataclass
class ValidationResult:
    ...

class RegionValidator(ABC):
    ...

class CamelotValidator(RegionValidator):
    ...

def get_validator(config: dict = None) -> RegionValidator:
    """Factory function to get configured validator"""
    ...

def validate_regions(pdf_path: str, page_num: int,
                     regions: List[dict]) -> List[dict]:
    """Convenience function to validate a list of regions"""
    ...
```

### 3. Database: TableSelection model

No schema changes required. Existing fields sufficient:
- `confidence` - Can reflect adjusted confidence
- `source` - Already distinguishes 'yolo' vs 'manual'
- `status` - Already has 'pending', 'approved', 'rejected'

Optional future enhancement: Add `validation_reason` field for debugging.

---

## Performance Considerations

### Estimated Overhead

| Operation | Time per Region |
|-----------|-----------------|
| Camelot lattice | ~0.3-0.5s |
| Camelot stream | ~0.5-1.0s |
| Total (both) | ~0.8-1.5s |

For a page with 5 false detections, adds ~4-7 seconds.

### Mitigations

1. **Early exit**: If lattice finds structure, skip stream
2. **Timeout**: Cap validation time per region (5s default)
3. **Parallel validation**: Process regions concurrently (optional)
4. **Quick reject**: Skip validation for very small regions
5. **Caching**: Reuse page renders between YOLO and Camelot

### Acceptable Tradeoff

Given that:
- Validation runs once at upload time, not on every page view
- False positives significantly degrade UX
- Review workflow is interactive (user is waiting anyway)

Adding 5-10 seconds to detection is acceptable for cleaner results.

---

## Testing Plan

### Unit Tests

1. **CamelotValidator**
   - Valid bordered table → returns valid
   - Valid borderless table → returns valid
   - Infographic region → returns invalid
   - Empty region → returns invalid
   - Validation error → fails gracefully

2. **validate_regions()**
   - Filters invalid when strategy='filter'
   - Marks invalid when strategy='mark'
   - Passes all through when validation disabled
   - Handles empty region list

3. **Configuration**
   - Respects enabled flag
   - Respects min_rows/min_cols
   - Timeout works correctly

### Integration Tests

1. **End-to-end with known PDF**
   - Upload ASIC report chapter
   - Verify infographic pages return fewer/no detections
   - Verify actual table pages still detected

2. **Performance benchmark**
   - Measure validation overhead on 10-page document
   - Verify within acceptable range

### Manual Testing

1. Upload ASIC annual report (the problematic document)
2. Verify infographics on pages 7-10 not detected
3. Verify actual tables elsewhere still detected
4. Check book viewer shows clean results

---

## Rollout Plan

### Phase 1: Implementation (This PR)

1. Create `api/scripts/validators.py` with base classes
2. Implement `CamelotValidator`
3. Add configuration to settings
4. Integrate into `detect_table_regions()`
5. Add unit tests
6. Manual testing with ASIC report

### Phase 2: Monitoring & Tuning

1. Monitor validation hit rate (what % filtered)
2. Collect feedback on false negatives
3. Tune thresholds (min_rows, min_cols, confidence)

### Phase 3: Future Enhancements (As Needed)

1. Add LineDetectionValidator for faster pre-filtering
2. Add CompositeValidator for multi-signal validation
3. Expose validation toggle in UI for power users

---

## File Changes Summary

| File | Change |
|------|--------|
| `api/scripts/validators.py` | **New** - Validator classes and utilities |
| `api/scripts/YOLOV3/predict_table.py` | Integrate validation into `detect_table_regions()` |
| `tablescan/settings.py` | Add `DETECTION_VALIDATION` config |
| `api/tests/test_validators.py` | **New** - Unit tests for validators |
| `docs/FEATURE-detection-validation.md` | **New** - This document |

---

## Open Questions

1. **Should validation be async?**
   - Current: Runs synchronously in Celery task
   - Could: Run as separate Celery subtask for better timeout handling
   - Decision: Start synchronous, optimize if needed

2. **What about manual selection mode?**
   - Validation only applies to YOLO detections
   - Manual selections skip validation (user explicitly drew them)
   - Decision: Correct, no change needed

3. **Should we store validation results?**
   - Current: Just filter/mark in memory
   - Could: Store in TableSelection for analytics
   - Decision: Defer to Phase 2, add field if needed for debugging

---

## Success Metrics

1. **Primary**: Infographic pages in ASIC report return 0 false detections
2. **Secondary**: No regression in detection of actual tables
3. **Performance**: Validation adds < 2 seconds per page average
