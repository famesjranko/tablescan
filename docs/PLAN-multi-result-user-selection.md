# Plan: Multi-Result Extraction with User Selection

**Date:** 2026-03-12
**Status:** Planning
**Supersedes:** PLAN-extraction-quality-improvements.md (staged routing approach abandoned)

---

## Problem Summary

The staged routing approach from the previous plan failed because:

1. **ROI routing too restrictive**: Page with vector lines → only runs vector extractors → misses `camelot_stream` which actually works
2. **Fallback didn't trigger**: Quality gate passed garbage results, so vision fallback never ran
3. **Overengineered**: Trying to predict the "best" extractor upfront is fragile

**Simpler solution**: Run ALL extractors, let user pick the best result.

---

## Design Principles

1. **Run everything** - Don't try to predict which extractor will work best
2. **Show all options** - User sees multiple extraction results and picks the best
3. **Score for guidance** - Scoring helps rank results but doesn't exclude any
4. **Quality metadata** - Show quality gate failures as warnings, not hard rejects
5. **User has final say** - Download/save any result they choose

---

## Architecture Overview

```
PDF Page + Table Selection
           │
           ▼
   ┌───────────────────┐
   │  Run ALL Extractors│
   │  (in parallel)     │
   └───────────────────┘
           │
           ▼
   ┌───────────────────┐
   │  Score & Analyze   │
   │  Each Result       │
   └───────────────────┘
           │
           ▼
   ┌───────────────────┐
   │  Return ALL to     │
   │  Frontend          │
   └───────────────────┘
           │
           ▼
   ┌───────────────────┐
   │  User Cycles       │
   │  Through Results   │
   │  & Picks Best      │
   └───────────────────┘
```

---

## Extractors to Run

All extractors run on every table:

| Extractor | Description | Best For |
|-----------|-------------|----------|
| `camelot_lattice` | Line-based detection | Black bordered tables |
| `camelot_stream` | Text-flow based | Borderless/light tables |
| `pdfplumber` | Text strategy | Simple tables |
| `pdfplumber_explicit` | Uses PDF vector lines | Colored border tables |
| `vision` (img2table) | Image-based OCR | Scanned/complex tables |

---

## Data Structure

### Backend Response

```python
{
    "table_id": "uuid",
    "page_num": 11,
    "selection_bbox": {"x1": 42, "y1": 712, "x2": 510, "y2": 489},

    # All extraction results
    "results": [
        {
            "id": "result-1",
            "method": "camelot_stream",
            "score": 0.847,
            "confidence": 0.990,
            "dimensions": {"rows": 10, "cols": 5},
            "quality_warnings": [],  # e.g., ["header_fragmentation", "split_rows"]
            "dataframe_json": {...},  # Table data
            "preview_html": "...",    # Optional: rendered preview
        },
        {
            "id": "result-2",
            "method": "vision",
            "score": 0.834,
            "confidence": 0.834,
            "dimensions": {"rows": 7, "cols": 5},
            "quality_warnings": [],
            "dataframe_json": {...},
            "preview_html": "...",
        },
        # ... more results
    ],

    # Metadata for debugging
    "roi_analysis": {
        "line_count": 33,
        "rect_count": 6,
        "has_colored_lines": true,
        "text_density": 1330,
    },

    # Recommended result (highest score, for auto-select)
    "recommended_id": "result-1",
}
```

### Quality Warnings (from QualityGate)

Kept from previous plan - shown as warnings, not rejections:

- `header_fragmentation` - Spaced chars like "C H A N G E"
- `row_fragmentation` - Split multi-line cells
- `numeric_fragmentation` - Broken numbers like "2 023"
- `empty_rows` - Excessive empty rows
- `empty_cols` - Excessive empty columns

---

## Frontend UI

### Extraction Result Selector

```
┌─────────────────────────────────────────────────────────┐
│  Extraction Results (5 found)                           │
│                                                         │
│  ┌─────────────────────────────────────────────────┐   │
│  │  ◀  Result 2 of 5: vision (Score: 0.834)    ▶   │   │
│  │                                                  │   │
│  │  Dimensions: 7 rows × 5 columns                 │   │
│  │  Confidence: 83.4%                              │   │
│  │  Warnings: None                                 │   │
│  └─────────────────────────────────────────────────┘   │
│                                                         │
│  ┌─────────────────────────────────────────────────┐   │
│  │  Table Preview                                   │   │
│  │  ┌──────────────┬────────┬────────┬─────────┐   │   │
│  │  │ Revenue      │ 2024   │ 2023   │ Change  │   │   │
│  │  ├──────────────┼────────┼────────┼─────────┤   │   │
│  │  │ Operations   │ $31M   │ $28M   │ +10.7%  │   │   │
│  │  │ ...          │ ...    │ ...    │ ...     │   │   │
│  │  └──────────────┴────────┴────────┴─────────┘   │   │
│  └─────────────────────────────────────────────────┘   │
│                                                         │
│  [Download CSV] [Download XLSX] [Use This Result]       │
│                                                         │
│  ─────────────────────────────────────────────────────  │
│  All Results:                                           │
│  ● camelot_stream  (0.847) - 10×5 - Recommended        │
│  ○ vision          (0.834) - 7×5                        │
│  ○ pdfplumber      (0.756) - 8×4 - ⚠ split_rows        │
│  ○ camelot_lattice (0.000) - No table found            │
│  ○ pdfplumber_explicit (0.698) - 7×2 - ⚠ wrong area   │
└─────────────────────────────────────────────────────────┘
```

### UI Features

1. **Carousel/tabs** to cycle through results
2. **Table preview** for each result
3. **Score + warnings** visible
4. **Download any result** (CSV, XLSX, JSON)
5. **"Use This Result"** button to save choice
6. **Quick list** showing all results with scores

---

## Backend Changes

### 1. New Endpoint or Modify Existing

Option A: New endpoint `/api/extract-all/`
Option B: Modify existing extraction to return multiple results

### 2. Unified Extractor Runner

```python
class UnifiedExtractor:
    """Runs all extractors and returns all results."""

    def __init__(self):
        self._extractors = [
            CamelotExtractor(flavor='lattice'),
            CamelotExtractor(flavor='stream'),
            PdfplumberExtractor(),
            PdfplumberExplicitExtractor(),
            VisionExtractor(),
        ]
        self._scorer = ExtractionScorer()
        self._quality_gate = QualityGate()
        self._roi_inspector = ROIInspector()  # For metadata only

    def extract_all(self, pdf_path, page_num, table_areas=None):
        """Run all extractors, return all results with scores."""
        results = []

        for extractor in self._extractors:
            try:
                extractions = extractor.extract(pdf_path, page_num, table_areas)
                for ext in extractions:
                    score = self._scorer.score(ext)
                    gate_result = self._quality_gate.evaluate(ext)

                    results.append({
                        'method': ext.method,
                        'dataframe': ext.dataframe,
                        'score': score,
                        'confidence': ext.confidence,
                        'quality_warnings': gate_result.failures,
                        'metadata': ext.metadata,
                    })
            except Exception as e:
                results.append({
                    'method': extractor.name,
                    'error': str(e),
                    'score': 0,
                })

        # Sort by score descending
        results.sort(key=lambda r: r.get('score', 0), reverse=True)

        # Add ROI analysis for debugging
        roi = self._roi_inspector.analyze(pdf_path, page_num,
                                          table_areas[0] if table_areas else None)

        return {
            'results': results,
            'roi_analysis': roi.__dict__,
            'recommended_id': results[0]['method'] if results else None,
        }
```

### 3. Keep Existing Components

From previous plan, keep but repurpose:
- `QualityGate` - For warnings metadata
- `ExtractionScorer` - For ranking/recommendation
- `ROIInspector` - For debugging metadata
- `PdfplumberExplicitExtractor` - As one of the extractors

---

## Migration Path

### Phase 1: Backend (1-2 days)
- [ ] Create `UnifiedExtractor` class
- [ ] Modify extraction endpoint to return all results
- [ ] Include scores, warnings, metadata in response
- [ ] Keep backward compatibility (still return "best" for existing callers)

### Phase 2: Frontend (2-3 days)
- [ ] Add result selector UI component
- [ ] Implement carousel/tabs for cycling results
- [ ] Show table preview for each result
- [ ] Download buttons for any result
- [ ] "Use This Result" to save choice

### Phase 3: Integration (1 day)
- [ ] Wire up frontend to new endpoint/response
- [ ] Handle edge cases (no results, errors)
- [ ] Update auto/manual/review flows

### Phase 4: Polish (1 day)
- [ ] Loading states while extractors run
- [ ] Error handling UI
- [ ] Mobile responsiveness

---

## Scoring Algorithm

Keep from previous plan, but as guidance not gating:

```python
# Weights (tunable)
confidence_weight = 0.15   # Extractor self-reported (unreliable)
coverage_weight = 0.25     # Cell fill rate
regularity_weight = 0.25   # Row/column consistency
numeric_weight = 0.10      # Numeric content detection
header_weight = 0.25       # Header quality

# Quality gate failures reduce score but don't exclude
if quality_failures:
    score *= 0.7  # Penalty but still shown to user
```

---

## Success Metrics

1. **User can see all extraction options** for any table
2. **User can download any result** (not just "best")
3. **Scores help guide** user to good results
4. **No silent failures** - if extraction fails, user knows why
5. **ASIC page 11** shows both camelot_stream (10x5) and vision (7x5) as options

---

## Rejected from Previous Plan

| Approach | Why Rejected |
|----------|--------------|
| Staged routing | Too restrictive, missed working extractors |
| Hard quality gate rejection | User might want "bad" result anyway |
| Auto-select only | User has no recourse if auto picks wrong |

---

## Open Questions

1. **Parallel extraction?** - Run extractors in parallel for speed?
2. **Caching?** - Cache results so user can switch without re-extracting?
3. **Partial results?** - Show results as they complete, or wait for all?
4. **Comparison view?** - Side-by-side comparison of two results?

---

## Estimated Effort

| Phase | Effort |
|-------|--------|
| Backend changes | 1-2 days |
| Frontend UI | 2-3 days |
| Integration | 1 day |
| Polish | 1 day |

**Total**: ~5-7 days
