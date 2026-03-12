# Plan: Extraction Quality Improvements

**Date:** 2026-03-12
**Status:** Abandoned
**Superseded by:** PLAN-multi-result-user-selection.md

---

## Post-Mortem: Why This Approach Failed

The staged routing approach was too clever. Key failures:

1. **ROI routing was too restrictive**: Page 11 of ASIC report has 33 vector lines, so ROI said "use vector strategy". But `camelot_stream` (a text extractor) was what actually worked. The routing excluded it.

2. **Quality gate passed garbage**: `pdfplumber_explicit` extracted the page header ("Y OVER" / "VIEW") instead of the table. Quality gate passed it (no fragmentation detected), so fallback to vision never triggered.

3. **Fallback logic was flawed**: Only fell back to vision if quality gate FAILED. But garbage can pass quality gates.

**Lesson learned**: Don't try to predict which extractor will work. Run ALL extractors, show ALL results to user, let them pick.

**What's worth keeping**:
- `PdfplumberExplicitExtractor` - useful as one option among many
- `QualityGate` - useful for warnings/metadata, not hard rejection
- `ROIInspector` - useful for debugging metadata
- Scoring weight insights - confidence is unreliable

---

**Original plan follows for reference:**

---

**Original Status:** Implemented (but approach abandoned)
**Supersedes:** FEATURE-colored-border-extraction.md (approach rejected)

---

## Problem Summary

Tables with light-colored borders are poorly extracted, but the root cause is **architectural**, not parameter tuning:

1. **Vector structure ignored**: PDF contains 33 line objects that pdfplumber can see, but extractors try to rediscover them via image processing
2. **Scorer rewards "dense but wrong"**: Camelot stream produces broken tables (split rows, fragmented headers) but scores 0.8591 vs img2table's correct extraction at 0.8496
3. **No quality gates**: Scorer can't detect structural problems like `C H A N G E` or split multi-line cells
4. **Pure competition model**: All extractors run, best score wins - no routing based on table characteristics

---

## Design Principles

1. **Use what the PDF gives you** - extract vector structure, don't rediscover it from images
2. **Quality gates before ranking** - reject structurally broken results, then rank survivors
3. **Route by morphology** - inspect table ROI first, choose extraction strategy accordingly
4. **Fallback, not competition** - escalate to heavier methods only when lighter ones fail
5. **Generalize, don't overfit** - solutions must work across all table types

---

## Implementation Phases

### Phase 1: Vector-Aware Extraction (High Impact, Medium Effort)

**Goal**: Use PDF line/rect objects directly instead of image-based detection.

#### 1.1 Add pdfplumber explicit-lines extractor

Extract line coordinates from table ROI, pass to pdfplumber as explicit lines:

```python
class PdfplumberExplicitExtractor(BaseExtractor):
    """Uses PDF vector structure for table detection."""

    def extract(self, pdf_path, page_num, table_areas):
        with pdfplumber.open(pdf_path) as pdf:
            page = pdf.pages[page_num - 1]

            # Extract lines within table bbox
            lines = page.lines
            rects = page.rects

            # Convert to explicit line coordinates
            v_lines = [l['x0'] for l in lines if l['height'] > l['width']]
            h_lines = [l['y0'] for l in lines if l['width'] > l['height']]

            # Also extract lines from rectangle edges
            for r in rects:
                v_lines.extend([r['x0'], r['x1']])
                h_lines.extend([r['y0'], r['y1']])

            # Dedupe and sort
            v_lines = sorted(set(v_lines))
            h_lines = sorted(set(h_lines))

            tables = page.extract_tables({
                'vertical_strategy': 'explicit',
                'horizontal_strategy': 'explicit',
                'explicit_vertical_lines': v_lines,
                'explicit_horizontal_lines': h_lines,
            })
```

#### 1.2 Add PyMuPDF extractor (alternative/additional)

PyMuPDF has native table finding and direct access to vector drawings:

```python
class PyMuPDFExtractor(BaseExtractor):
    """Uses PyMuPDF for fast vector-aware extraction."""

    def extract(self, pdf_path, page_num, table_areas):
        import fitz  # PyMuPDF

        doc = fitz.open(pdf_path)
        page = doc[page_num - 1]

        # Native table detection
        tables = page.find_tables()

        # Or use drawings for custom detection
        drawings = page.get_drawings()
```

**Acceptance Criteria**:
- [x] PdfplumberExplicitExtractor implemented and tested
- [x] Works on tables with colored/light borders (uses PDF vector structure)
- [x] Doesn't break standard black-bordered tables
- [x] Added to StagedMultiExtractor pipeline (vector strategy)

---

### Phase 2: Quality Gates (High Impact, Medium Effort)

**Goal**: Reject structurally broken results before scoring.

#### 2.1 Add structural quality checks

```python
class QualityGate:
    """Hard reject for structurally broken extractions."""

    def passes(self, result: ExtractionResult) -> Tuple[bool, List[str]]:
        """Returns (passed, list_of_failures)."""
        failures = []
        df = result.dataframe

        # Check 1: Spaced single characters in headers
        if self._has_spaced_chars(df.iloc[0]):
            failures.append('header_fragmentation')

        # Check 2: Split multi-line cells (adjacent sparse rows)
        if self._has_split_rows(df):
            failures.append('row_fragmentation')

        # Check 3: Broken numeric tokens
        if self._has_broken_numbers(df):
            failures.append('numeric_fragmentation')

        return len(failures) == 0, failures

    def _has_spaced_chars(self, row) -> bool:
        """Detect patterns like 'C H A N G E' or '2 0 2 3'."""
        import re
        pattern = r'(?:^|[^A-Za-z0-9])([A-Za-z0-9] ){3,}'
        for cell in row:
            if re.search(pattern, str(cell)):
                return True
        return False

    def _has_split_rows(self, df) -> bool:
        """Detect rows that look like continuations of previous row."""
        for i in range(1, len(df)):
            row = df.iloc[i]
            prev = df.iloc[i-1]

            # If first column starts with lowercase or '(' and
            # previous row's first column is non-empty, likely split
            first_cell = str(row.iloc[0]).strip()
            prev_first = str(prev.iloc[0]).strip()

            if first_cell and prev_first:
                if first_cell[0].islower() or first_cell.startswith('('):
                    # Check if rest of row is mostly empty
                    non_empty = sum(1 for c in row[1:] if str(c).strip())
                    if non_empty <= 1:
                        return True
        return False

    def _has_broken_numbers(self, df) -> bool:
        """Detect patterns like '2 023' or '513 ,558'."""
        import re
        pattern = r'\d\s+[\d,]'  # digit, space(s), digit or comma
        for col in df.columns:
            for val in df[col]:
                if re.search(pattern, str(val)):
                    return True
        return False
```

#### 2.2 Integrate quality gates into scorer

```python
class ExtractionScorer:
    def __init__(self, ...):
        self._quality_gate = QualityGate()

    def score(self, result, page_text=None) -> float:
        # Quality gate first
        passed, failures = self._quality_gate.passes(result)
        if not passed:
            # Heavy penalty, but don't zero out completely
            # (allows comparison of "least bad" if all fail)
            return self._compute_score(result, page_text) * 0.3

        return self._compute_score(result, page_text)
```

**Acceptance Criteria**:
- [x] QualityGate class implemented with 5 checks (spaced chars, split rows, broken numbers, empty rows, empty cols)
- [x] Broken extractions (fragmented headers, split rows) fail quality gate
- [x] Well-structured extractions pass quality gate
- [x] Integrated into ExtractionScorer (optional quality_gate parameter)

---

### Phase 3: Staged Routing (Medium Impact, Higher Effort)

**Goal**: Route to appropriate extractor based on table characteristics.

#### 3.1 Add ROI inspector

```python
class ROIInspector:
    """Analyzes table region to determine best extraction strategy."""

    def analyze(self, pdf_path, page_num, bbox) -> dict:
        with pdfplumber.open(pdf_path) as pdf:
            page = pdf.pages[page_num - 1]

            # Filter objects within bbox
            lines_in_roi = [l for l in page.lines if self._in_bbox(l, bbox)]
            rects_in_roi = [r for r in page.rects if self._in_bbox(r, bbox)]
            chars_in_roi = [c for c in page.chars if self._in_bbox(c, bbox)]

            return {
                'has_vector_lines': len(lines_in_roi) > 4,
                'has_filled_rects': any(r.get('fill') for r in rects_in_roi),
                'line_count': len(lines_in_roi),
                'rect_count': len(rects_in_roi),
                'text_density': len(chars_in_roi),
                'avg_line_width': self._avg_width(lines_in_roi),
            }

    def recommend_strategy(self, analysis: dict) -> str:
        """Returns: 'vector', 'text', or 'vision'."""
        if analysis['has_vector_lines'] and analysis['line_count'] > 8:
            return 'vector'  # Use explicit lines
        elif analysis['text_density'] > 50:
            return 'text'    # Use stream/text-based
        else:
            return 'vision'  # Use img2table
```

#### 3.2 Implement staged MultiExtractor

```python
class StagedMultiExtractor:
    """Routes extraction based on ROI analysis."""

    def __init__(self):
        self._inspector = ROIInspector()
        self._quality_gate = QualityGate()
        self._scorer = ExtractionScorer()

        self._vector_extractors = [
            PdfplumberExplicitExtractor(),
            CamelotExtractor(flavor='lattice'),
        ]
        self._text_extractors = [
            CamelotExtractor(flavor='stream'),
            PdfplumberExtractor(vertical_strategy='text'),
        ]
        self._vision_extractors = [
            VisionExtractor(),
        ]

    def extract_best(self, pdf_path, page_num, table_areas=None):
        # Step 1: Analyze ROI
        analysis = self._inspector.analyze(pdf_path, page_num, table_areas)
        strategy = self._inspector.recommend_strategy(analysis)

        # Step 2: Run primary extractors for strategy
        extractors = {
            'vector': self._vector_extractors,
            'text': self._text_extractors,
            'vision': self._vision_extractors,
        }[strategy]

        results = self._run_extractors(extractors, pdf_path, page_num, table_areas)

        # Step 3: Quality gate
        passing = [(r, self._scorer.score(r)) for r in results
                   if self._quality_gate.passes(r)[0]]

        if passing:
            # Return best passing result
            return max(passing, key=lambda x: x[1])[0]

        # Step 4: Fallback - try vision if not already tried
        if strategy != 'vision':
            vision_results = self._run_extractors(
                self._vision_extractors, pdf_path, page_num, table_areas
            )
            if vision_results:
                return max(vision_results, key=lambda r: self._scorer.score(r))

        # Step 5: Return least-bad from all results
        all_results = results + (vision_results if strategy != 'vision' else [])
        if all_results:
            return max(all_results, key=lambda r: self._scorer.score(r))

        return None
```

**Acceptance Criteria**:
- [x] ROIInspector correctly identifies vector-rich tables (line_count, rect_count, has_colored_lines)
- [x] StagedMultiExtractor routes based on ROI analysis (vector/text/vision strategies)
- [x] Falls back to vision when vector/text fail quality gate
- [x] Performance acceptable (runs only strategy-specific extractors, not all)

---

### Phase 4: Confidence Calibration (Lower Priority)

**Goal**: Reduce reliance on extractor-reported confidence.

#### 4.1 Reduce confidence weight

```python
# Before (confidence dominates):
confidence_weight = 0.4

# After (confidence as tiebreaker):
confidence_weight = 0.15
coverage_weight = 0.25
regularity_weight = 0.25
quality_gate_weight = 0.25  # NEW
numeric_weight = 0.05
header_weight = 0.05
```

#### 4.2 Add per-extractor confidence calibration (future)

Build labeled benchmark, measure actual accuracy vs reported confidence, apply calibration curve per extractor.

---

## Testing Strategy

### Unit Tests

- [x] QualityGate detects spaced characters (test_quality_gate.py)
- [x] QualityGate detects split rows (test_quality_gate.py)
- [x] ROIInspector correctly analyzes vector-rich PDFs (test_roi_inspector.py)
- [x] PdfplumberExplicitExtractor extracts from explicit lines (test_explicit_extractor.py)

### Integration Tests

- [x] Vector-lined tables: StagedMultiExtractor routes correctly
- [x] Standard black-bordered tables: no regression (477 tests pass)
- [x] Borderless tables: text/stream mode still works
- [x] Quality gates filter broken extractions

### Benchmark PDFs

| PDF | Table Type | Expected Outcome |
|-----|------------|------------------|
| ASIC report p11 | Light blue borders | 7x5, merged cells |
| Standard invoice | Black borders | Lattice succeeds |
| Text-only table | No borders | Stream succeeds |
| Scanned document | Image-based | Vision succeeds |

---

## Migration Path

1. **Phase 1**: Add PdfplumberExplicitExtractor alongside existing extractors
2. **Phase 2**: Add QualityGate, penalize failing results
3. **Phase 3**: Replace MultiExtractor with StagedMultiExtractor
4. **Phase 4**: Tune weights based on benchmark results

Each phase is independently deployable and testable.

---

## Rejected Approaches

### Adding more extractor variants (from FEATURE-colored-border-extraction.md)

**Why rejected**:
- Doesn't solve scorer picking wrong result
- Extractor proliferation (maintenance burden)
- Doesn't generalize

### Increasing row_tol globally

**Why rejected**:
- Fixes one table, breaks others
- Not generalizable

### Pure OCR/vision for all PDFs

**Why rejected**:
- Performance cost
- Re-OCR introduces errors for born-digital PDFs

---

## Success Metrics

1. **Primary**: ASIC page 11 extracts correctly (7x5, merged cells, correct headers)
2. **Regression**: Existing test suite passes
3. **Performance**: Average extraction time within 20% of current
4. **Quality**: >90% of tables pass quality gate on first extraction strategy

---

## Dependencies

- `pdfplumber` (already installed)
- `pymupdf` / `fitz` (optional, for Phase 1 alternative)
- No new ML models required

---

## Estimated Effort

| Phase | Effort | Impact |
|-------|--------|--------|
| Phase 1: Vector-aware extraction | 2-3 days | High |
| Phase 2: Quality gates | 1-2 days | High |
| Phase 3: Staged routing | 2-3 days | Medium |
| Phase 4: Confidence calibration | 1 day | Low |

**Total**: ~7-9 days for full implementation
