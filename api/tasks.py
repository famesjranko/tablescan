"""
tasks.py
    Celery tasks for async PDF table extraction
"""

from celery import shared_task
from django.conf import settings
from pathlib import Path, PurePath

from api.scripts import table_extract
from api.scripts.logging import Logging
from api.models import Report

from timeit import default_timer as timer
from humanfriendly import format_timespan


@shared_task(bind=True)
def extract_tables_task(self, report_id, file_path, start_page, end_page,
                        flavor='auto', row_tol=2, strip_text='\n', merge_headers=True):
    """
    Async task to extract tables from a PDF document.
    Updates task state with progress for SSE streaming.

    Args:
        report_id: Database ID of the Report
        file_path: Path to PDF file
        start_page: Starting page number
        end_page: Ending page number (-1 for all)
        flavor: Camelot flavor ('auto', 'lattice', or 'stream')
        row_tol: Row tolerance for stream flavor
        strip_text: Characters to strip from cell text
        merge_headers: Whether to merge fragmented multi-row headers
    """
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
        log.output("INFO", f"[Task {self.request.id}] Options: flavor={flavor}, merge_headers={merge_headers}")

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
            flavor=flavor, row_tol=row_tol, strip_text=strip_text,
            merge_headers=merge_headers, report_id=report_id,
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
