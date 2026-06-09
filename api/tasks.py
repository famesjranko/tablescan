"""
tasks.py
    Celery tasks for async PDF table extraction
"""

from collections import defaultdict
import json

import fitz
import pandas as pd
from celery import shared_task
from django.conf import settings
from django.core.cache import cache
from pathlib import Path, PurePath

from api.scripts import table_extract
from api.scripts.logging import Logging
from api.scripts.YOLOV3.predict_table import detect_table_regions, save_extraction_results, extract_from_manual_areas
from api.scripts.extractors import MultiExtractor, ExtractionResult
from api.models import Report, TableSelection, Extracted

from timeit import default_timer as timer
from humanfriendly import format_timespan


def _cache_key_for_selection(report_id: int, selection_id: int) -> str:
    """Generate cache key for extraction variants."""
    return f"extraction_variants:{report_id}:{selection_id}"


def _serialize_variants_for_cache(variants: list) -> str:
    """Serialize extraction variants for cache using JSON."""
    serializable = []
    for v in variants:
        v_copy = v.copy()
        if v_copy.get('dataframe') is not None:
            # Convert DataFrame to JSON-serializable format
            v_copy['dataframe_json'] = v_copy['dataframe'].to_json(orient='split')
        v_copy.pop('dataframe', None)
        serializable.append(v_copy)
    return json.dumps(serializable)


def _deserialize_variants_from_cache(data: str) -> list:
    """Deserialize extraction variants from cache.

    DataFrames are rebuilt directly from the ``orient='split'`` components
    (columns/index/data) with ``dtype=str`` rather than via ``pd.read_json``.
    ``read_json``'s type inference silently corrupts the round-trip in two ways
    (see issue #16):

    - Identifier-like cells lose their exact form ('001' -> 1, '1.50' -> 1.5).
    - Duplicate column labels get a ``.1`` suffix ('Total','Total' ->
      'Total','Total.1').

    Extractor outputs are already string-typed and ``fillna``'d before they are
    cached, so forcing ``str`` on the way back reproduces exactly what was
    extracted instead of re-introducing numeric types. Assumes single-level row
    and column axes (true for every extractor output); MultiIndex axes are not
    produced in this pipeline and are not handled by this reconstruction.
    """
    variants = json.loads(data)
    for v in variants:
        if 'dataframe_json' in v:
            split = json.loads(v['dataframe_json'])
            v['dataframe'] = pd.DataFrame(
                data=split['data'],
                index=split['index'],
                columns=split['columns'],
                dtype=str,
            )
            del v['dataframe_json']
        else:
            v['dataframe'] = None
    return variants


@shared_task(bind=True)
def extract_tables_task(self, report_id, file_path, start_page, end_page,
                        enabled_libraries=None, strip_text='\n', merge_headers=True):
    """
    Async task to extract tables from a PDF document.
    Updates task state with progress for SSE streaming.

    Args:
        report_id: Database ID of the Report
        file_path: Path to PDF file
        start_page: Starting page number
        end_page: Ending page number (-1 for all)
        enabled_libraries: Dict of library toggles (camelot, pdfplumber, pymupdf, vision)
        strip_text: Characters to strip from cell text
        merge_headers: Whether to merge fragmented multi-row headers
    """
    if enabled_libraries is None:
        enabled_libraries = {'camelot': True, 'pdfplumber': True, 'pymupdf': True, 'vision': True}
    log = Logging()

    # Update state to show we've started
    self.update_state(state='PROGRESS', meta={
        'current': 0,
        'total': 100,
        'status': 'Starting extraction...'
    })

    start = timer()

    try:
        # Validate report exists before processing (handles stale tasks after rebuild)
        try:
            report = Report.objects.get(id=report_id)
        except Report.DoesNotExist:
            log.output("WARNING", f"[Task {self.request.id}] Report {report_id} not found - stale task, skipping")
            return {
                'status': 'skipped',
                'report_id': report_id,
                'reason': 'Report no longer exists (stale task)'
            }

        log.output("INFO", f"[Task {self.request.id}] Starting extraction for report {report_id}")
        log.output("INFO", f"[Task {self.request.id}] Options: enabled_libraries={enabled_libraries}, merge_headers={merge_headers}")

        # Update progress
        self.update_state(state='PROGRESS', meta={
            'current': 10,
            'total': 100,
            'status': 'Loading PDF document...'
        })

        # Progress callback for status updates during extraction
        def update_progress(percent, status):
            self.update_state(state='PROGRESS', meta={
                'current': percent,
                'total': 100,
                'status': status
            })

        # Run extraction with options
        extracted = table_extract.extract(
            file_path, start_page, end_page,
            enabled_libraries=enabled_libraries,
            strip_text=strip_text,
            merge_headers=merge_headers,
            report_id=report_id,
            progress_callback=update_progress
        )

        # Update progress to complete
        self.update_state(state='PROGRESS', meta={
            'current': 90,
            'total': 100,
            'status': 'Finalizing...'
        })

        end = timer()
        duration = format_timespan(end - start)
        log.output("INFO", f"[Task {self.request.id}] Extraction completed in {duration}")

        return {
            'status': 'completed',
            'report_id': report_id,
            'duration': duration,
            'result': extracted
        }

    except Exception as e:
        log.output("ERROR", f"[Task {self.request.id}] Extraction failed: {str(e)}")
        self.update_state(state='FAILURE', meta={
            'status': f'Error: {str(e)}'
        })
        raise


@shared_task(bind=True)
def detect_tables_for_review(self, report_id):
    """
    Async task to run YOLO detection and save boxes as TableSelection records.
    Used for the review workflow where users approve/reject detected tables.

    Args:
        report_id: Database ID of the Report

    Returns:
        dict with status, report_id, selections_count, redirect_url
    """
    log = Logging()

    self.update_state(state='PROGRESS', meta={
        'current': 0,
        'total': 100,
        'status': 'Starting detection...'
    })

    start = timer()

    try:
        # Validate report exists
        try:
            report = Report.objects.get(id=report_id)
        except Report.DoesNotExist:
            log.output("WARNING", f"[Task {self.request.id}] Report {report_id} not found - stale task, skipping")
            return {
                'status': 'skipped',
                'report_id': report_id,
                'reason': 'Report no longer exists (stale task)'
            }

        # Update status to detecting
        report.extraction_status = 'detecting'
        report.save(update_fields=['extraction_status'])

        log.output("INFO", f"[Task {self.request.id}] Starting YOLO detection for report {report_id}")

        self.update_state(state='PROGRESS', meta={
            'current': 10,
            'total': 100,
            'status': 'Running table detection...'
        })

        # Get page range
        start_page = report.start_page or 1
        end_page = report.end_page if report.end_page and report.end_page > 0 else report.total_pages or 1

        file_path = report.document.path
        total_pages = end_page - start_page + 1
        selections_created = 0

        # Process each page
        for i, page_num in enumerate(range(start_page, end_page + 1)):
            progress = 10 + int(80 * (i / total_pages))
            self.update_state(state='PROGRESS', meta={
                'current': progress,
                'total': 100,
                'status': f'Detecting tables on page {page_num}...'
            })

            try:
                regions = detect_table_regions(file_path, page_num)

                # Save each detected region as a TableSelection
                for region in regions:
                    TableSelection.objects.create(
                        report=report,
                        page_num=page_num,
                        x1=region['x1'],
                        y1=region['y1'],
                        x2=region['x2'],
                        y2=region['y2'],
                        confidence=region.get('confidence'),
                        source='yolo',
                        status='pending'
                    )
                    selections_created += 1

                log.output("INFO", f"[Task {self.request.id}] Page {page_num}: detected {len(regions)} table(s)")

            except Exception as page_error:
                log.output("WARNING", f"[Task {self.request.id}] Page {page_num} detection failed: {str(page_error)}")
                # Continue with other pages

        # Update status to pending_review
        report.extraction_status = 'pending_review'
        report.save(update_fields=['extraction_status'])

        self.update_state(state='PROGRESS', meta={
            'current': 100,
            'total': 100,
            'status': 'Detection complete'
        })

        end = timer()
        duration = format_timespan(end - start)
        log.output("INFO", f"[Task {self.request.id}] Detection completed in {duration}, {selections_created} selections created")

        return {
            'status': 'completed',
            'report_id': report_id,
            'selections_count': selections_created,
            'redirect_url': f'/reports/{report_id}/viewer/'
        }

    except Exception as e:
        log.output("ERROR", f"[Task {self.request.id}] Detection failed: {str(e)}")

        # Update report status to failed
        try:
            report = Report.objects.get(id=report_id)
            report.extraction_status = 'failed'
            report.save(update_fields=['extraction_status'])
        except Report.DoesNotExist:
            pass

        # Create user-friendly error message
        error_msg = str(e)
        if 'Traceback' in error_msg or 'Error' in error_msg[:20]:
            user_friendly_msg = 'Table detection failed. Please ensure the PDF is valid and try again.'
        else:
            user_friendly_msg = f'Detection error: {error_msg}'

        self.update_state(state='FAILURE', meta={
            'status': user_friendly_msg
        })
        raise Exception(user_friendly_msg) from e


@shared_task(bind=True)
def extract_from_selections(self, report_id):
    """
    Extract tables from approved TableSelection regions.

    Gets all TableSelection records with status='approved' (includes both
    YOLO-approved and manual selections), groups them by page, and uses
    the same Camelot extraction logic as auto mode to extract tables.

    Args:
        report_id: Database ID of the Report

    Returns:
        dict with status, report_id, tables_extracted
    """
    log = Logging()

    self.update_state(state='PROGRESS', meta={
        'current': 0,
        'total': 100,
        'status': 'Starting extraction from selections...'
    })

    start = timer()

    try:
        # Validate report exists
        try:
            report = Report.objects.get(id=report_id)
        except Report.DoesNotExist:
            log.output("WARNING", f"[Task {self.request.id}] Report {report_id} not found - stale task, skipping")
            return {
                'status': 'skipped',
                'report_id': report_id,
                'reason': 'Report no longer exists (stale task)'
            }

        # Update status to extracting
        report.extraction_status = 'extracting'
        report.save(update_fields=['extraction_status'])

        log.output("INFO", f"[Task {self.request.id}] Starting extraction from selections for report {report_id}")

        # Get approved selections
        approved_selections = TableSelection.objects.filter(
            report=report,
            status='approved'
        ).order_by('page_num', 'created_at')

        if not approved_selections.exists():
            log.output("WARNING", f"[Task {self.request.id}] No approved selections found for report {report_id}")
            report.extraction_status = 'completed'
            report.save(update_fields=['extraction_status'])
            return {
                'status': 'completed',
                'report_id': report_id,
                'tables_extracted': 0,
                'message': 'No approved selections to extract'
            }

        # Get PDF page dimensions for coordinate conversion
        file_path = report.document.path

        # Group selections by page_num with coordinate conversion
        # Both manual and YOLO selections use percentage coords (0-100) for display
        # Convert to PDF coordinates for Camelot extraction
        selections_by_page = defaultdict(list)
        with fitz.open(file_path) as pdf_doc:
            for sel in approved_selections:
                log.output("INFO", f"[Task {self.request.id}] Processing selection {sel.id}: "
                          f"source='{sel.source}', page={sel.page_num}")

                # Both manual and YOLO selections are now in percentage coords (0-100)
                page = pdf_doc[sel.page_num - 1]  # fitz uses 0-indexed pages
                page_width = page.rect.width
                page_height = page.rect.height

                pdf_x1 = (sel.x1 / 100) * page_width
                pdf_x2 = (sel.x2 / 100) * page_width
                # Y-flip: canvas origin is top-left, PDF origin is bottom-left
                # y1 (canvas top) → higher PDF Y value (top in PDF coords)
                # y2 (canvas bottom) → lower PDF Y value (bottom in PDF coords)
                pdf_y1 = (1 - sel.y1 / 100) * page_height
                pdf_y2 = (1 - sel.y2 / 100) * page_height

                table_area = (pdf_x1, pdf_y1, pdf_x2, pdf_y2)
                log.output("INFO", f"[Task {self.request.id}] {sel.source.upper()} COORDS: "
                          f"canvas ({sel.x1:.1f}%, {sel.y1:.1f}%, {sel.x2:.1f}%, {sel.y2:.1f}%) → "
                          f"PDF ({pdf_x1:.1f}, {pdf_y1:.1f}, {pdf_x2:.1f}, {pdf_y2:.1f}) "
                          f"[page {page_width:.0f}x{page_height:.0f}]")

                selections_by_page[sel.page_num].append(table_area)

        log.output("INFO", f"[Task {self.request.id}] Found {len(approved_selections)} approved selections across {len(selections_by_page)} pages")

        self.update_state(state='PROGRESS', meta={
            'current': 10,
            'total': 100,
            'status': 'Loading PDF and preparing extraction...'
        })

        # Setup extraction directories
        working_dir = Path(file_path).parent
        extract_dir = {
            "csv": working_dir / "csv",
            "json": working_dir / "json",
            "xlsx": working_dir / "xlsx",
        }

        # Create output directories
        for dir_path in extract_dir.values():
            dir_path.mkdir(parents=True, exist_ok=True)

        total_tables_extracted = 0
        pages_to_process = sorted(selections_by_page.keys())
        total_pages = len(pages_to_process)

        # Track failed pages for partial success reporting
        failed_pages = []
        selection_ids_by_page = defaultdict(list)
        for sel in approved_selections:
            selection_ids_by_page[sel.page_num].append(sel.id)

        # Initialize multi-extractor for running all methods
        multi_extractor = MultiExtractor()
        cache_ttl = getattr(settings, 'EXTRACTION_VARIANTS_CACHE_TTL', 600)

        # Process each selection individually (not grouped by page)
        # This allows per-selection caching and method switching
        all_selections = list(approved_selections)
        total_selections = len(all_selections)

        for i, selection in enumerate(all_selections):
            page_num = selection.page_num

            # Create progress callback for detailed method-level updates
            # Map technical method names to user-friendly descriptions
            method_descriptions = {
                'camelot_lattice': 'Detecting table borders',
                'camelot_stream': 'Analyzing whitespace layout',
                'pdfplumber': 'Scanning PDF structure',
                'pdfplumber_text': 'Extracting text patterns',
                'pymupdf': 'Processing document layers',
                'pymupdf_text': 'Reading text alignment',
                'img2table': 'Running visual recognition',
            }

            def make_progress_callback(sel_idx, sel_total):
                def callback(method_name, method_idx, method_total):
                    # Progress: 10-90% range, split between selections and methods
                    base = 10 + int(80 * sel_idx / sel_total)
                    method_increment = int(80 / sel_total * method_idx / method_total)
                    progress = base + method_increment
                    description = method_descriptions.get(method_name, method_name)
                    self.update_state(state='PROGRESS', meta={
                        'current': progress,
                        'total': 100,
                        'message': f'Table {sel_idx + 1}/{sel_total}: {description} (method {method_idx}/{method_total})'
                    })
                return callback

            # Get the table area for this selection
            with fitz.open(file_path) as pdf_doc:
                page = pdf_doc[page_num - 1]
                page_width = page.rect.width
                page_height = page.rect.height

                pdf_x1 = (selection.x1 / 100) * page_width
                pdf_x2 = (selection.x2 / 100) * page_width
                pdf_y1 = (1 - selection.y1 / 100) * page_height
                pdf_y2 = (1 - selection.y2 / 100) * page_height
                table_area = (pdf_x1, pdf_y1, pdf_x2, pdf_y2)

            log.output("INFO", f"[Task {self.request.id}] Selection {selection.id}: extracting with all methods")

            try:
                # Run ALL extractors and get scored results
                all_variants = multi_extractor.extract_all_with_scores(
                    pdf_path=file_path,
                    page_num=page_num,
                    table_areas=[table_area],
                    progress_callback=make_progress_callback(i, total_selections)
                )

                # Filter out failed/empty results for display but keep them in cache
                valid_variants = [v for v in all_variants if v.get('dataframe') is not None and v.get('rows', 0) > 0]

                if valid_variants:
                    # Cache ALL variants (including failed ones for transparency)
                    cache_key = _cache_key_for_selection(report.id, selection.id)
                    cache.set(cache_key, _serialize_variants_for_cache(all_variants), timeout=cache_ttl)
                    log.output("INFO", f"[Task {self.request.id}] Cached {len(all_variants)} variants for selection {selection.id}")

                    # Get the best result (highest score)
                    best_variant = valid_variants[0]

                    # Create ExtractionResult for saving
                    best_result = ExtractionResult(
                        dataframe=best_variant['dataframe'],
                        confidence=best_variant['confidence'],
                        method=best_variant['method'],
                        metadata=best_variant.get('metadata', {})
                    )

                    # Save the best result to disk and database
                    save_extraction_results(
                        results=[best_result],
                        file_path=file_path,
                        page_num=page_num,
                        report_db=report,
                        extract_dir=extract_dir,
                        page_type='born_digital',
                        selection=selection
                    )
                    total_tables_extracted += 1
                    log.output("INFO", f"[Task {self.request.id}] Selection {selection.id}: saved best result ({best_variant['method']}, score={best_variant['score']:.3f})")
                else:
                    # No valid results from any extractor
                    log.output("WARNING", f"[Task {self.request.id}] Selection {selection.id}: no tables extracted from any method")
                    failed_pages.append(page_num)
                    selection.status = 'failed'
                    selection.save(update_fields=['status'])

            except Exception as sel_error:
                log.output("WARNING", f"[Task {self.request.id}] Selection {selection.id} extraction failed: {str(sel_error)}")
                failed_pages.append(page_num)
                selection.status = 'failed'
                selection.save(update_fields=['status'])

        # Update status to completed
        report.extraction_status = 'completed'
        report.save(update_fields=['extraction_status'])

        # Determine final status message
        if failed_pages:
            if total_tables_extracted > 0:
                status_msg = f'Partial extraction complete. {len(failed_pages)} page(s) failed.'
            else:
                status_msg = 'Extraction failed on all pages.'
        else:
            status_msg = 'Extraction complete'

        self.update_state(state='PROGRESS', meta={
            'current': 100,
            'total': 100,
            'status': status_msg
        })

        end = timer()
        duration = format_timespan(end - start)
        log.output("INFO", f"[Task {self.request.id}] Extraction completed in {duration}, {total_tables_extracted} tables extracted")

        result = {
            'status': 'completed' if total_tables_extracted > 0 else 'partial_failure',
            'report_id': report_id,
            'tables_extracted': total_tables_extracted,
            'pages_processed': len(pages_to_process),
            'duration': duration
        }

        # Include failed pages info for partial success reporting
        if failed_pages:
            result['failed_pages'] = failed_pages
            result['message'] = f'Extraction completed with {len(failed_pages)} failed page(s): {", ".join(str(p) for p in sorted(failed_pages))}'

        return result

    except Exception as e:
        log.output("ERROR", f"[Task {self.request.id}] Extraction from selections failed: {str(e)}")

        # Update report status to failed
        try:
            report = Report.objects.get(id=report_id)
            report.extraction_status = 'failed'
            report.save(update_fields=['extraction_status'])
        except Report.DoesNotExist:
            pass

        # Create user-friendly error message
        error_msg = str(e)
        if 'Traceback' in error_msg or 'Error' in error_msg[:20]:
            # Looks like a raw exception, provide a user-friendly message
            user_friendly_msg = 'Table extraction failed. Please check that the PDF contains valid tables and try again.'
        else:
            user_friendly_msg = f'Extraction error: {error_msg}'

        self.update_state(state='FAILURE', meta={
            'status': user_friendly_msg
        })
        raise Exception(user_friendly_msg) from e
