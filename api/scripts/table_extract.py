"""
table_extract.py
    Written by: Andrew McDonald
    Initial: 10.08.21
    Updated: 02.09.21
    version: 1.3

Logic:
    if file_path points to location of pdf document on local machine,
    YOLOV3 extractions will run to find and extract any found table data
    and export to file output_types. Once whole document has been processed
    by YOLOV3, any exported files will then be added to the database Extracted
    and referenced to the file database
    object Report, along with a zip of the csv directory.

Additional:
    Utilises multi-processing for detection and extraction.

Args:
    file_path (str):    [path location of pdf file]
    output_types (str): [extraction output types
    start_page (int):   [extraction starting page]
    end_page (int):     [extraction ending page]

Raises:
    FileNotFoundError:  [if path not found, or not file]
    ValueError:         [when end page is greater than total pages]
    ValueError:         [when end page is less than start page]
    ValueError:         [when start page is less than 1]
    ValueError:         [when start page is greater than end page]
    SystemError:        [when exception is thrown by extraction engine]
    AttributeError:     [when file is not a pdf]

Returns:
    dict: [containing pdf and extracted tables info]
"""

import os
import shutil
import pandas as pd
import json
import multiprocessing as mp

from typing import Any, Callable, Dict, List, Optional
from pathlib import Path, PurePath
from tabulate import tabulate
from PyPDF2 import PdfReader

from api.scripts.logging import Logging
from api.models import Report, TableSelection, Extracted
from api.scripts.page_classifier import PageClassifier
from api.scripts.extractors import VisionExtractor, ExtractionScorer, MultiExtractor
from django.core.cache import cache
from django.conf import settings
import fitz

# Lazy imports for YOLO (requires torch) - only loaded when needed
_yolo_imports = None

def _get_yolo_functions():
    """Lazy load YOLO functions to avoid importing torch at module load."""
    global _yolo_imports
    if _yolo_imports is None:
        from api.scripts.YOLOV3.predict_table import (
            detect_tables, extract_tables_direct, extract_tables_vision,
            extract_tables_direct_readonly, extract_tables_vision_readonly,
            extract_tables_with_all_variants, save_extraction_results
        )
        _yolo_imports = {
            'detect_tables': detect_tables,
            'extract_tables_direct': extract_tables_direct,
            'extract_tables_vision': extract_tables_vision,
            'extract_tables_direct_readonly': extract_tables_direct_readonly,
            'extract_tables_vision_readonly': extract_tables_vision_readonly,
            'extract_tables_with_all_variants': extract_tables_with_all_variants,
            'save_extraction_results': save_extraction_results,
        }
    return _yolo_imports


# Feature flags - loaded from docs/prd.json if available
def _load_feature_flags() -> dict:
    """Load feature flags from prd.json."""
    import json
    default_flags = {
        'use_page_classifier': True,
        'use_multi_extractor': True,
        'use_vision_detector': True,
        'use_rich_schema': False,
        'legacy_yolo_enabled': True,
    }
    try:
        prd_path = Path(__file__).parent.parent.parent / 'docs' / 'prd.json'
        with open(prd_path, 'r') as f:
            prd = json.load(f)
            return prd.get('featureFlags', default_flags)
    except Exception:
        return default_flags


FEATURE_FLAGS = _load_feature_flags()


def _cache_key_for_selection(report_id: int, selection_id: int) -> str:
    """Generate cache key for extraction variants."""
    return f"extraction_variants:{report_id}:{selection_id}"


def _serialize_variants_for_cache(variants: list) -> str:
    """Serialize extraction variants for cache using JSON."""
    serializable = []
    for v in variants:
        v_copy = v.copy()
        if v_copy.get('dataframe') is not None:
            v_copy['dataframe_json'] = v_copy['dataframe'].to_json(orient='split')
        v_copy.pop('dataframe', None)
        serializable.append(v_copy)
    return json.dumps(serializable)


def _normalize_bbox(bbox: dict) -> tuple:
    """
    Normalize bounding box to (x_min, y_min, x_max, y_max) format.

    Handles different formats:
    - Camelot/pdfplumber: x0, y0, x1, y1
    - VisionExtractor: x1, y1, x2, y2
    """
    if not bbox:
        return None

    # Try x0/y0/x1/y1 format first (Camelot)
    if 'x0' in bbox:
        return (bbox['x0'], bbox['y0'], bbox['x1'], bbox['y1'])
    # Try x1/y1/x2/y2 format (VisionExtractor)
    elif 'x1' in bbox and 'x2' in bbox:
        return (bbox['x1'], bbox['y1'], bbox['x2'], bbox['y2'])
    return None


def _calculate_bbox_overlap(bbox1: dict, bbox2: dict) -> float:
    """
    Calculate intersection-over-union (IoU) for two bounding boxes.

    Args:
        bbox1: Dict with bounding box coordinates (various formats supported)
        bbox2: Dict with bounding box coordinates (various formats supported)

    Returns:
        IoU value from 0.0 (no overlap) to 1.0 (identical boxes)
    """
    if not bbox1 or not bbox2:
        return 0.0

    try:
        # Normalize both bboxes to (x_min, y_min, x_max, y_max)
        norm1 = _normalize_bbox(bbox1)
        norm2 = _normalize_bbox(bbox2)

        if not norm1 or not norm2:
            return 0.0

        x0_1, y0_1, x1_1, y1_1 = norm1
        x0_2, y0_2, x1_2, y1_2 = norm2

        # Calculate intersection
        x_left = max(x0_1, x0_2)
        y_top = max(min(y0_1, y1_1), min(y0_2, y1_2))
        x_right = min(x1_1, x1_2)
        y_bottom = min(max(y0_1, y1_1), max(y0_2, y1_2))

        if x_right <= x_left or y_bottom <= y_top:
            return 0.0

        intersection = (x_right - x_left) * (y_bottom - y_top)

        # Calculate areas
        area1 = abs(x1_1 - x0_1) * abs(y1_1 - y0_1)
        area2 = abs(x1_2 - x0_2) * abs(y1_2 - y0_2)

        if area1 == 0 and area2 == 0:
            return 0.0

        # IoU
        union = area1 + area2 - intersection
        return intersection / union if union > 0 else 0.0
    except (KeyError, TypeError):
        return 0.0


def deduplicate_by_bbox(scored_results: list, iou_threshold: float = 0.5) -> list:
    """
    Deduplicate tables that overlap the same region from different extractors.

    When multiple extractors find tables in overlapping regions, keep only
    the highest-scoring result for each region.

    Args:
        scored_results: List of (ExtractionResult, score) tuples sorted by score descending
        iou_threshold: Minimum IoU to consider tables as duplicates (default 0.5)

    Returns:
        List of ExtractionResult (deduplicated, best results only)
    """
    if not scored_results:
        return []

    log = Logging()

    # Group results by page number
    by_page = {}
    for result, score in scored_results:
        page = result.metadata.get('page_num', 0) if result.metadata else 0
        if page not in by_page:
            by_page[page] = []
        by_page[page].append((result, score))

    selected = []

    for page, page_results in by_page.items():
        # If only one result on this page, keep it
        if len(page_results) == 1:
            selected.append(page_results[0][0])
            continue

        # Multiple results on same page - try bbox deduplication
        page_selected = []
        page_selected_bboxes = []
        all_have_bbox = True

        for result, score in page_results:
            bbox = result.metadata.get('bounding_box') if result.metadata else None

            if not bbox:
                all_have_bbox = False

            # Normalize bbox for comparison
            norm_bbox = _normalize_bbox(bbox) if bbox else None

            if not norm_bbox:
                # Can't compare, tentatively include
                page_selected.append((result, score, None))
                continue

            # Check overlap with already-selected
            is_duplicate = False
            for _, _, existing_norm in page_selected:
                if existing_norm:
                    iou = _calculate_bbox_overlap(bbox,
                        {'x0': existing_norm[0], 'y0': existing_norm[1],
                         'x1': existing_norm[2], 'y1': existing_norm[3]})
                    if iou >= iou_threshold:
                        is_duplicate = True
                        log.output('DEBUG', f'Page {page}: Skipping duplicate table '
                                   f'({result.method}, IoU={iou:.2f})')
                        break

            if not is_duplicate:
                page_selected.append((result, score, norm_bbox))

        # Fallback: if bbox dedup didn't reduce the count, check for similar shapes
        # This handles cases where bboxes are in different coordinate systems
        if len(page_selected) > 1:
            # Check if results look like the same table (similar shape)
            shapes = [(r.dataframe.shape, r, s) for r, s, _ in page_selected]
            # If shapes are very similar (within 2 rows AND 2 columns), likely same table
            base_rows, base_cols = shapes[0][0]
            similar_shapes = all(
                abs(s[0][0] - base_rows) <= 2 and abs(s[0][1] - base_cols) <= 2
                for s in shapes
            )

            if similar_shapes:
                log.output('INFO', f'Page {page}: Similar tables from different extractors, keeping best score')
                # Keep only the highest scoring (already sorted by score desc)
                page_selected = [page_selected[0]]

        selected.extend([r for r, s, _ in page_selected])

    return selected


# camelot accuracy report list
report_list = []

# variants data list for caching (populated by multiprocessing callbacks)
variants_list = []

# Global page classifier instance for multiprocessing
_page_classifier = None


def _get_page_classifier() -> PageClassifier:
    """Get or create page classifier instance (for multiprocessing)."""
    global _page_classifier
    if _page_classifier is None:
        _page_classifier = PageClassifier()
    return _page_classifier


def process_page_with_routing(
    file_path: str,
    page_num: int,
    output_type: str,
    report_db: "Report",
    extract_dir: Dict[str, Any],
    flavor: str,
    row_tol: int,
    strip_text: str,
    merge_headers: bool
) -> List[Dict[str, Any]]:
    """
    Process a single page with routing based on page classification.

    Phase 2 Architecture:
    - Born-digital pages: Use direct extraction only (MultiExtractor/Camelot)
    - Scanned/Mixed pages: Try BOTH vision AND direct extraction, compare results
      using ExtractionScorer, deduplicate overlapping tables, save only the best

    This enables better accuracy by allowing text-based extractors to outperform
    vision extractors on PDFs that appear scanned but have extractable text
    (e.g., 9.3% text coverage "scanned" pages where Camelot gives 99% accuracy).

    Args:
        file_path: Path to PDF file
        page_num: Page number to process (1-indexed)
        output_type: Output format type
        report_db: Database report instance
        extract_dir: Dictionary of extraction directories
        flavor: Camelot flavor ('auto', 'lattice', or 'stream')
        row_tol: Row tolerance for Camelot parsing
        strip_text: Characters to strip from cell text
        merge_headers: Whether to merge fragmented multi-row headers

    Returns:
        list: Parsing reports for extracted tables
    """
    log = Logging()
    classifier = _get_page_classifier()
    scorer = ExtractionScorer()

    # Classify page (PageClassifier uses 0-indexed pages)
    classification = classifier.classify(file_path, page_num - 1)

    log.output(
        'INFO',
        f'Page {page_num}: type={classification.type}, '
        f'text_coverage={classification.text_coverage:.1%}, '
        f'has_images={classification.has_images}'
    )

    # Get feature flags
    use_vision = FEATURE_FLAGS.get('use_vision_detector', True)
    legacy_yolo = FEATURE_FLAGS.get('legacy_yolo_enabled', True)

    # Get lazy-loaded functions
    yolo = _get_yolo_functions()

    # Collect all extraction candidates
    candidates = []

    # Track variants for caching (returned to main process)
    page_variants_data = None

    if classification.type == 'born_digital':
        # Born-digital: Use direct extraction with all variants for caching
        log.output('INFO', f'Page {page_num}: Using multi-extractor with variants (born-digital)')
        try:
            extraction_data = yolo['extract_tables_with_all_variants'](
                file_path=file_path,
                page_number=page_num,
                merge_headers=merge_headers
            )
            candidates.extend(extraction_data['best_results'])
            # Store variants for caching by main process
            page_variants_data = {
                'page_num': page_num,
                'all_variants': extraction_data['all_variants'],
                'table_bboxes': extraction_data['table_bboxes'],
            }
            log.output('INFO', f'Page {page_num}: Direct extraction found {len(extraction_data["best_results"])} table(s), {len(extraction_data["all_variants"])} variants')
        except Exception as e:
            log.output('WARNING', f'Page {page_num}: Direct extraction failed: {e}')

    elif classification.type == 'scanned' or classification.type == 'mixed':
        # Scanned/Mixed pages: Try BOTH vision AND direct, compare results
        # This approach allows text-based extractors to outperform vision when
        # "scanned" PDFs actually have extractable text (e.g., 9.3% text coverage)
        log.output('INFO', f'Page {page_num}: Trying multiple extractors ({classification.type})')

        # Try vision extraction first (typically better for scanned content)
        if use_vision:
            try:
                vision_results = yolo['extract_tables_vision_readonly'](
                    file_path=file_path,
                    page_number=page_num,
                    strip_text=strip_text,
                    merge_headers=merge_headers
                )
                candidates.extend(vision_results)
                log.output('INFO', f'Page {page_num}: VisionExtractor found {len(vision_results)} table(s)')
                if not vision_results:
                    log.output('INFO', f'Page {page_num}: VisionExtractor found no tables')
            except Exception as e:
                log.output('WARNING', f'Page {page_num}: VisionExtractor failed: {e}')

        # Also try direct extraction (Camelot works on some "scanned" PDFs with text layer)
        try:
            direct_results = yolo['extract_tables_direct_readonly'](
                file_path=file_path,
                page_number=page_num,
                merge_headers=merge_headers
            )
            candidates.extend(direct_results)
            log.output('INFO', f'Page {page_num}: Direct extraction found {len(direct_results)} table(s)')
        except Exception as e:
            log.output('WARNING', f'Page {page_num}: Direct extraction failed: {e}')

        # If both failed and legacy YOLO is enabled, try YOLO as last resort
        if not candidates:
            if legacy_yolo:
                log.output('INFO', f'Page {page_num}: Falling back to legacy YOLO pipeline')
                try:
                    yolo_report = yolo['detect_tables'](
                        file_path, page_num, output_type, report_db, extract_dir,
                        flavor, row_tol, strip_text, merge_headers,
                        page_type=classification.type
                    )
                    # YOLO fallback doesn't have variants - return compatible structure
                    return {
                        'parsing_report': yolo_report,
                        'variants_data': None,
                        'page_num': page_num,
                    }
                except Exception as e:
                    log.output('WARNING', f'Page {page_num}: Legacy YOLO also failed: {e}')
            else:
                log.output('WARNING', f'Page {page_num}: No extractor available (YOLO disabled)')

    # If no candidates found, return empty result
    if not candidates:
        log.output('INFO', f'Page {page_num}: No tables found by any extractor')
        return {
            'parsing_report': [],
            'variants_data': None,
            'page_num': page_num,
        }

    # Score all candidates
    scored = scorer.score_all(candidates)

    # Log comparison of methods (top 5 results)
    log.output('INFO', f'Page {page_num}: Scoring {len(scored)} candidate table(s)')
    for result, score in scored[:5]:
        log.output(
            'DEBUG',
            f'Page {page_num}: {result.method}: score={score:.4f}, '
            f'confidence={result.confidence:.3f}, '
            f'shape={result.dataframe.shape}'
        )

    # Deduplicate overlapping tables (same region from different extractors)
    best_results = deduplicate_by_bbox(scored, iou_threshold=0.5)

    # Log which methods won
    method_counts = {}
    for result in best_results:
        method = result.method
        method_counts[method] = method_counts.get(method, 0) + 1

    log.output(
        'INFO',
        f'Page {page_num}: After deduplication: {len(best_results)} table(s), '
        f'methods: {method_counts}'
    )

    # Save winning results
    report = yolo['save_extraction_results'](
        results=best_results,
        file_path=file_path,
        page_num=page_num,
        report_db=report_db,
        extract_dir=extract_dir,
        page_type=classification.type
    )

    # Return both parsing report and variants data for caching
    return {
        'parsing_report': report,
        'variants_data': page_variants_data,
        'page_num': page_num,
    }


def pdf_stats(
    filename: str,
    total_pages: int,
    start_page: int,
    end_page: int,
    output_types: dict,
    tables_found: Optional[int] = None,
) -> str:
    """
    print basic document processing information for logging

    Args:
        filename (str):     [pdf file name]
        total_pages (int):  [pdf total pages]
        start_page (int):   [extraction starting page]
        end_page (int):     [extraction ending page]
        output_types (str): [extraction output types]
        tables_found (int, optional): [how many tables found from extraction.
                                        Defaults to 0.]

    Returns:
        [type]: [description]
    """
    
    # get document info
    if tables_found is None:
        info = [
            ("file name", filename),
            ("total pages", total_pages),
            ("start page", start_page),
            ("end page", end_page),
            ("output types", [key for key in output_types]),
        ]
    else:
        info = [
            ("file name", filename),
            ("total pages", total_pages),
            ("start page", start_page),
            ("end page", end_page),
            ("output types", [key for key in output_types]),
            ("tables found", tables_found),
        ]

    return tabulate(info, tablefmt="fancy_grid")


def get_num_pages(path: str) -> int:
    """
    find the total number of pages in pdf document
    returns int

    Args:
        path (str): [path location of pdf file]

    Returns:
        int: [number of pages in pdf]
    """
    
    with open(path, "rb") as f:
        pdf = PdfReader(f)
        return len(pdf.pages)


def end_of_range(start_page: int, end_page: int, total_pages: int) -> int:
    """
    checks and validates user requested extraction end page

    Args:
        start_page (int):   [user entered starting page]
        end_page (int):     [user entered ending page]
        end_at (int):       [total pages in document]

    Raises:
        ValueError: [end page is larger than document total pages]
        ValueError: [end page is less than starting page]

    Returns:
        int: [extraction end page number]
    """
    
    if end_page == -1:
        return total_pages

    if end_page > total_pages:
        error_msg = f"end_page {end_page} is out of scope, max {total_pages}"
        raise ValueError(error_msg)
    elif end_page < start_page:
        error_msg = (
            f"end_page {end_page} is out of scope, cannot be less than starting page"
        )
        raise ValueError(error_msg)
    elif end_page >= 1:
        return end_page


def start_of_range(start_page: int, end_at: int, start_at: int = 1) -> int:
    """
    checks and validates user requested extraction start page

    Args:
        start_page (int):           [user entered starting page]
        end_at (int):               [extraction range ending page]
        start_at (int, optional):   [default start page]. Defaults to 1.

    Raises:
        ValueError: [start page is less than 1]
        ValueError: [start page is greater than end page]

    Returns:
        int: [extraction start page number]
    """

    if start_page >= 1 and start_page <= end_at:
        return start_page
    elif start_page < 1:
        error_msg = f"start_page {start_page} is out of scope, cannot be less than 1"
        raise ValueError(error_msg)
    elif start_page > end_at:
        error_msg = f"start_page {start_page} is out of scope, cannot be greater than end page {end_at}"
        raise ValueError(error_msg)
    else:
        return start_at


def collect_result(filename: str, table: Dict[str, Any], tables_list: List[Dict[str, Any]]) -> None:
    """
    append dictionary of table data to tables list
    returns None

    Args:
        filename (str): [table output file name]
        table (Dict[str, Any]):   [json table structure]
        tables_list (List[Dict[str, Any]]): [list to append to]

    Returns: None
    """
    
    filename = filename.replace("json", "csv")
    table_data = {filename: table}
    tables_list.append(table_data)

    return None


def collect_parsing_report(result: Dict[str, Any]) -> None:
    """
    Collector function for grabbing multi-processing outputs.
    Appends parsing reports to report_list and variants to variants_list.

    Args:
        result: Dict with 'parsing_report', 'variants_data', and 'page_num'

    Returns: None
    """
    if not result:
        return None

    # Handle new dict structure
    if isinstance(result, dict) and 'parsing_report' in result:
        parsing_report = result.get('parsing_report')
        variants_data = result.get('variants_data')

        if parsing_report:
            report_list.append(parsing_report)

        if variants_data:
            variants_list.append(variants_data)
    else:
        # Backwards compatibility with old list format
        report_list.append(result)

    return None


def process_extracted_file(
    filename: str, tables_list: list, full_working_dir: str
) -> None:
    """
    extraction file processing

    Logic:
        1. append json data to tables_list for response to front-end
        2. parse found csv into pandas and print to terminal with tabulate

    Args:
        file (str):             [name of file]
        tables_list (list):     [list to send as response to front-end]
        full_working_dir (str): [the working directory of the Report]
    """
    
    # set to true if want visual terminal log of found tables in django
    show_tables_in_log = False

    if filename.suffix == ".json":
        # append json data to tables_list
        with open(filename, mode="r") as handle:
            parsed = json.load(handle)
            collect_result(Path(filename).name, parsed, tables_list)
    elif filename.suffix == ".csv" and show_tables_in_log:
        # print table to log
        df = pd.read_csv(os.path.join(full_working_dir, filename))
        print(tabulate(df, headers="keys", tablefmt="fancy_grid"))
    
    return None


def extract(file_path: str, start_page: int, end_page: int,
            flavor: str = 'auto', row_tol: int = 2, strip_text: str = '\n',
            merge_headers: bool = True, report_id: int = None,
            progress_callback: Optional[Callable[[int, str], None]] = None) -> Dict[str, Any]:
    """
    extract function links django API request /upload to YoloV3 extraction engine.
    takes a pdf filepath, desired extraction output types, start page, and end page.
    returns a dictionary of document info, along with tables extracted

    Args:
        file_path (str):    [path location of pdf file]
        start_page (int):   [extraction starting page]
        end_page (int):     [extraction ending page]
        flavor (str):       [camelot flavor: 'auto', 'lattice', or 'stream']
        row_tol (int):      [row tolerance for stream flavor]
        strip_text (str):   [characters to strip from cell text]
        merge_headers (bool): [whether to merge fragmented multi-row headers]

    Raises:
        FileNotFoundError:  [if path not found, or not file]
        ValueError:         [when end page is greater than total pages]
        ValueError:         [when end page is less than start page]
        ValueError:         [when start page is less than 1]
        ValueError:         [when start page is greater than end page]
        SystemError:        [when exception is thrown by extraction engine]
        AttributeError:     [when file is not a pdf]

    Returns:
        dict: [containing pdf and extracted tables info]
    """
    
    # create log object
    log = Logging()

    # get report database object
    file_name = Path(file_path).name
    if report_id:
        report_db = Report.objects.get(id=report_id)
    else:
        # Fallback for backwards compatibility - use most recent matching report
        report_db = Report.objects.filter(document__endswith=file_name).order_by('-id').first()
        if not report_db:
            raise Report.DoesNotExist(f"No report found for {file_name}")

    # check path exists
    if not Path(file_path).exists():
        error_msg = f"{PurePath(file_path).name} not found!"
        report_db.delete()
        log.output("INFO", "removed database object")

        raise FileNotFoundError(error_msg)

    # check if is a file
    if not Path(file_path).is_file():
        error_msg = f"{PurePath(file_path).name} is not a file!"
        report_db.delete()
        log.output("INFO", "removed database object")

        raise FileNotFoundError(error_msg)

    # pdf type check
    if not file_name.endswith(".pdf"):
        error_msg = f"{PurePath(file_path).name} is not a pdf!"
        report_db.delete()
        log.output("INFO", "removed database object")

        raise AttributeError(error_msg)

    # get working dir
    full_working_dir = Path(file_path).parent

    # get total number of pages for pdf
    total_pages = get_num_pages(file_path)

    # update database with ending page
    report_db.total_pages = total_pages
    report_db.save()

    # get end of extraction page range
    try:
        end_at = end_of_range(start_page, end_page, total_pages)
    except Exception as error_msg:
        report_db.delete()
        log.output("INFO", "removed database object")
        raise ValueError(error_msg)

    # update database with end page
    report_db.end_page = end_at
    report_db.save()

    # get start of extraction page range
    try:
        start_at = start_of_range(start_page, end_at)
    except Exception as error_msg:
        report_db.delete()
        log.output("INFO", "removed database object")
        raise ValueError(error_msg)

    # update database with starting page
    report_db.start_page = start_at
    report_db.save()

    # set directory test bool
    dir_created = False

    # build extraction directory names
    extract_dir = {
        "csv": PurePath(full_working_dir, "csv"),
        "json": PurePath(full_working_dir, "json"),
        "xlsx": PurePath(full_working_dir, "xlsx"),
    }

    # create new folders for storing to be extracted files.
    for dir in extract_dir.values():
        Path(dir).mkdir(parents=True, exist_ok=True)
        dir_created = True

    if dir_created:
        log.output("INFO", "export directories created")

    # get pdf stats
    pdf_info = pdf_stats(
        PurePath(file_path).name, report_db.total_pages, start_page, end_at, extract_dir
    )

    log.output("INFO", f"processing pdf stats \n{pdf_info}")

    # Update progress: analyzing PDF
    if progress_callback:
        progress_callback(15, f"Analyzing {end_at - start_at + 1} page(s)...")

    # Multi-processing 1: Init multiprocessing Pool
    pool = mp.Pool(mp.cpu_count())

    log.output("INFO", f"multiprocessing using {mp.cpu_count()} cpu cores")

    # Multi-processing 2: Use async to loop to parallelize extraction
    # Note: apply_async returns an unordered list
    # Pages are routed based on classification (born-digital skips YOLO)
    try:
        log.output("INFO", f"starting extractions for pages {start_at} to {end_at}...")
        log.output("INFO", f"extraction options: flavor={flavor}, row_tol={row_tol}, merge_headers={merge_headers}")

        # Update progress: extraction starting
        if progress_callback:
            progress_callback(20, "Running OCR and table detection...")
        for num in range(start_at, end_at + 1, 1):
            detection_objects = pool.apply_async(
                process_page_with_routing,
                (str(file_path), num, "all", report_db, extract_dir,
                 flavor, row_tol, strip_text, merge_headers),
                callback=collect_parsing_report,
            )
    except Exception as e:
        error_msg = "".join(["from extraction pipeline: ", str(e)])
        pool.terminate()
        pool.join()
        report_db.delete()
        log.output("INFO", "removed database object")
        raise SystemError(error_msg)
    finally:
        # Multi-processing 3: Ensure pool cleanup even on exception
        try:
            pool.close()
            # Multi-processing 4: wait until process queue is empty.
            pool.join()
        except Exception:
            pass  # Pool already terminated in except block

    log.output("INFO", "finished extracting")

    # Update progress: extraction complete, now post-processing
    if progress_callback:
        progress_callback(80, "Processing extracted tables...")

    # Post-process: Create TableSelections and cache variants for method switching
    # This runs in the main process (safe for Django ORM and cache operations)
    cache_ttl = getattr(settings, 'EXTRACTION_VARIANTS_CACHE_TTL', 600)

    if variants_list:
        log.output("INFO", f"Caching variants for {len(variants_list)} page(s)...")

        # Get page dimensions for coordinate conversion
        with fitz.open(file_path) as pdf_doc:
            for page_data in variants_list:
                page_num = page_data['page_num']
                all_variants = page_data['all_variants']
                table_bboxes = page_data.get('table_bboxes', [])

                if not all_variants:
                    continue

                # Get page dimensions
                page = pdf_doc[page_num - 1]
                page_width = page.rect.width
                page_height = page.rect.height

                # Create TableSelection for this table
                # Use bounding box if available, otherwise use full page
                if table_bboxes and len(table_bboxes) > 0:
                    bbox = table_bboxes[0]
                    coords = _normalize_bbox(bbox)
                    if coords:
                        c0, c1, c2, c3 = coords
                        # Convert to percentage (0-100)
                        x1_pct = (c0 / page_width) * 100
                        x2_pct = (c2 / page_width) * 100
                        # Y-flip: PDF origin is bottom-left, screen is top-left
                        y1_pct = (1 - c3 / page_height) * 100
                        y2_pct = (1 - c1 / page_height) * 100
                        # Ensure valid box: y1 < y2 (top < bottom in screen coords)
                        if y1_pct > y2_pct:
                            y1_pct, y2_pct = y2_pct, y1_pct
                    else:
                        x1_pct, y1_pct, x2_pct, y2_pct = 0, 0, 100, 100
                else:
                    # Default to full page if no bbox
                    x1_pct, y1_pct, x2_pct, y2_pct = 0, 0, 100, 100

                # Create TableSelection with source='auto'
                selection = TableSelection.objects.create(
                    report=report_db,
                    page_num=page_num,
                    x1=x1_pct,
                    y1=y1_pct,
                    x2=x2_pct,
                    y2=y2_pct,
                    source='auto',
                    status='approved',  # Auto-approved since already extracted
                )

                # Cache all variants for this selection
                cache_key = _cache_key_for_selection(report_db.id, selection.id)
                cache.set(cache_key, _serialize_variants_for_cache(all_variants), timeout=cache_ttl)

                # Link selection to the Extracted record for this page/table
                # Find the Extracted record that was just created
                extracted = Extracted.objects.filter(
                    report=report_db,
                    page_num=page_num
                ).order_by('-id').first()

                if extracted and extracted.selection is None:
                    extracted.selection = selection
                    extracted.save(update_fields=['selection'])

                log.output("INFO", f"Page {page_num}: cached {len(all_variants)} variants, selection_id={selection.id}")

    # testing camelot parsing report
    # ==============================
    acc_total = 0
    count = 0

    # collect total accuracy and count cases
    for report in report_list:
        if isinstance(report, list) and len(report) > 0:
            count += 1
            acc_total += report[0].get("accuracy", 0)

    # empty lists
    report_list.clear()
    variants_list.clear()

    # get average accuracy and log to console
    if count > 0:
        acc_avg = acc_total / count
        log.output(
            "DEBUG", f"camelot parsing report accuracy avg: {round(acc_avg, 2)}%"
        )
    # ==============================

    log.output("INFO", "collecting table data for HTTP response...")

    # loop through extraction directories:
    for key, value in extract_dir.items():
        if key == "csv":
            zip_name = file_name.replace(".pdf", "-CSV")
            zip_path = PurePath(full_working_dir, zip_name)

            # create zip of csv extraction directory
            shutil.make_archive(
                zip_path, "zip", Path(full_working_dir), Path(value).name
            )

            log.output("INFO", f'{"".join([zip_name,".zip"])} created')

            number_of_tables = 0

            # count table files
            for path in Path(value).iterdir():
                if path.is_file():
                    number_of_tables += 1

    log.output("INFO", "finished collecting table data for HTTP response")

    # save zip file to database
    report_db.zip_csv.name = str(PurePath(full_working_dir.name, zip_name)) + ".zip"
    report_db.save()

    log.output("INFO", "database updated")

    # remove any leftover jpg files
    for file in Path(full_working_dir).iterdir():
        if file.suffix == ".jpg":
            Path.unlink(file)
            log.output("INFO", f"removed leftover file: {PurePath(file).name}")

    # build response dictionary for front-end
    response = {
        "report id": report_db.id,
        "file name": PurePath(file_path).name,
        "total pages": report_db.total_pages,
        "start page": start_page,
        "end page": end_at,
        "output types": "{}".format(list(extract_dir.keys())),
        "tables found": number_of_tables,
    }

    # get pdf stats
    pdf_info = pdf_stats(
        PurePath(file_path).name,
        report_db.total_pages,
        start_page,
        end_at,
        extract_dir,
        number_of_tables,
    )

    log.output("INFO", f"processed pdf stats \n{pdf_info}")

    # return dictionary for front-end
    return response


if __name__ == "__main__":
    extract()
