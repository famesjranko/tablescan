"""
Edited by: Andrew McDonald
version: 1.0
Last edit date: 02.09.21

Logic:
    detect_tables() recieves file_path for pdf document and a page_number
    then converts the pdf page into an image format for preocessing with
    YoloV3 object inferencing. If YoloV3 detects an interesting objects
    (object class: table) within the pdf imaga, the table position are then
    normalised to conform to the original pdf page, and both pdf page and x,y
    co-ordinates are passed to the Camelot library for extraction. Once
    extraction is completed, it is saved to local machine as desired file
    output_type in sub-directory of the main pdf directory respectively named,
    extract_type_dir - for example .csv are saved in pdf_file/csv

    If table is found and saved to local machine, it is then added to the
    database Extraction model and related to the pdf database Report model.

Returns:
    [dataframe]: [page extractions from camelot]
"""

# %%
import django
from pathlib import Path, PurePath
import os

# get django app
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "tablescan.settings")
django.setup()

# import database
from api.models import Extracted
from api.serializers import *
from api.scripts.logging import Logging

import sys
import copy
import datetime as date
from camelot import io as camelot

from time import sleep

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.image as mpimg

# from subprocess import check_output

from PyPDF2 import PdfFileWriter, PdfFileReader
from pdf2image import convert_from_path, convert_from_bytes
from api.scripts.YOLOV3.utils.detect_func import detectTable, parameters
from api.scripts.table_detector import detect_table_type_from_array
from api.scripts.header_processor import process_table_headers, strip_empty_rows_and_cols
from api.scripts.extractors import MultiExtractor, VisionExtractor, ExtractionScorer
from api.scripts.xlsx_exporter import export_to_xlsx
from typing import Optional, List


def build_structure_json(df, metadata: dict = None) -> dict:
    """
    Build rich structure_json from a DataFrame with cell-level data.

    Creates a structured JSON representation of the table that includes:
    - Cell values organized by row and column
    - Cell spans if detected (from metadata)
    - Row and column counts

    Args:
        df: pandas DataFrame containing the table data
        metadata: Optional extraction metadata that may contain span info

    Returns:
        dict with structure_json format containing cells array and dimensions
    """
    if df is None or df.empty:
        return None

    rows, cols = df.shape
    cells = []

    for row_idx in range(rows):
        for col_idx in range(cols):
            cell_value = df.iloc[row_idx, col_idx]
            cell_data = {
                "row": row_idx,
                "col": col_idx,
                "value": str(cell_value) if cell_value is not None else "",
            }

            # Check metadata for span information
            # Camelot and other extractors may provide cell span data
            if metadata:
                cells_meta = metadata.get("cells", [])
                for cm in cells_meta:
                    if cm.get("row") == row_idx and cm.get("col") == col_idx:
                        if cm.get("rowspan", 1) > 1:
                            cell_data["rowspan"] = cm["rowspan"]
                        if cm.get("colspan", 1) > 1:
                            cell_data["colspan"] = cm["colspan"]
                        break

            cells.append(cell_data)

    structure = {
        "rows": rows,
        "cols": cols,
        "cells": cells,
    }

    # Add header information if available
    if metadata and metadata.get("header_rows") is not None:
        structure["header_rows"] = metadata["header_rows"]

    return structure


# %%
def norm_pdf_page(pdf_file, pg):
    pdf_doc = PdfFileReader(open(pdf_file, "rb"), strict=False)
    pdf_page = pdf_doc.getPage(pg - 1)
    pdf_page.cropBox.upperLeft = (0, list(pdf_page.mediaBox)[-1])
    pdf_page.cropBox.lowerRight = (list(pdf_page.mediaBox)[-2], 0)

    return pdf_page


def pdf_page2img(pdf_file, pg, save_image=True):
    img_page = convert_from_path(pdf_file, first_page=pg, last_page=pg)[0]

    if save_image:
        img = pdf_file[:-4] + "-" + str(pg) + ".jpg"
        img_page.save(img)

    return np.array(img_page)


def outpout_yolo(output):
    output = output.split("\n")
    output.remove("")

    bboxes = []

    for x in output:
        cleaned_output = x.split(" ")
        cleaned_output.remove("")
        cleaned_output = [eval(x) for x in cleaned_output]
        bboxes.append(cleaned_output)

    return bboxes


def img_dim(img, bbox):
    H_img, W_img, _ = img.shape
    x1_img, y1_img, x2_img, y2_img, _, _ = bbox
    w_table, h_table = x2_img - x1_img, y2_img - y1_img

    return [[x1_img, y1_img, x2_img, y2_img], [w_table, h_table], [H_img, W_img]]


def norm_bbox(img, bbox, x_corr=0.02, y_corr=0.02):
    """
    Normalize bounding box coordinates with small margin corrections.
    Small margins capture table borders without including nearby content.
    """
    [[x1_img, y1_img, x2_img, y2_img], [w_table, h_table], [H_img, W_img]] = img_dim(
        img, bbox
    )
    x1_img_norm, y1_img_norm, x2_img_norm, y2_img_norm = (
        x1_img / W_img,
        y1_img / H_img,
        x2_img / W_img,
        y2_img / H_img,
    )
    w_img_norm, h_img_norm = w_table / W_img, h_table / H_img
    w_corr = w_img_norm * x_corr
    h_corr = h_img_norm * y_corr

    # Small symmetric margins - just enough for table borders
    return [
        x1_img_norm - w_corr,
        y1_img_norm - h_corr,
        x2_img_norm + w_corr,
        y2_img_norm + h_corr,
    ]


def bboxes_pdf(img, pdf_page, bbox, save_cropped=False):
    W_pdf = float(pdf_page.cropBox.getLowerRight()[0])
    H_pdf = float(pdf_page.cropBox.getUpperLeft()[1])

    [x1_img_norm, y1_img_norm, x2_img_norm, y2_img_norm] = norm_bbox(img, bbox)
    x1, y1 = x1_img_norm * W_pdf, (1 - y1_img_norm) * H_pdf
    x2, y2 = x2_img_norm * W_pdf, (1 - y2_img_norm) * H_pdf

    if save_cropped:
        page = copy.copy(pdf_page)
        page.cropBox.upperLeft = (x1, y1)
        page.cropBox.lowerRight = (x2, y2)
        output = PdfFileWriter()
        output.addPage(page)

        with open("cropped_" + pdf_file[:-4] + "-" + str(pg) + ".pdf", "wb") as out_f:
            output.write(out_f)

    return [x1, y1, x2, y2]


def tableValidate(dataframe) -> bool:
    """
    validation function for evaluating extracted tables
    uses column length and row depth as measure of validation

    returns Boolean
    """
    row_val = len(dataframe) >= 2
    col_val = len(dataframe.columns) >= 2
    # log.output('INFO', f'table is valid')

    return col_val and row_val


# %%


def detect_tables(file_path, page_number, output_type, report_db, extract_dir,
                  flavor='auto', row_tol=2, strip_text='\n', merge_headers=True,
                  page_type: Optional[str] = None) -> list:
    """
    Main function for detection, extraction, and saving extracted tables to database

    Args:
        file_path: Path to PDF file
        page_number: Page number to process
        output_type: Output format type
        report_db: Database report instance
        extract_dir: Dictionary of extraction directories
        flavor: Camelot flavor ('auto', 'lattice', or 'stream')
        row_tol: Row tolerance for Camelot parsing
        strip_text: Characters to strip from cell text
        merge_headers: Whether to merge fragmented multi-row headers
    """
    # create log object
    log = Logging()

    # log.output('INFO', f'processing page {page_number}')

    # previous code; left as many references to them...
    pdf_file = file_path
    pg = page_number

    # image conversion
    img_path = pdf_file[:-4] + "-" + str(pg) + ".jpg"
    pdf_page = norm_pdf_page(pdf_file, pg)
    img = pdf_page2img(pdf_file, pg, save_image=True)

    # yolo inferencing
    opt = parameters(img_path)
    output_detect = detectTable(opt)
    output = outpout_yolo(output_detect)

    # remove unwanted files
    Path.unlink(Path(img_path))
    sleep(0.1)
    # os.rmdir('outputs')

    # do you want to see prediction image?
    see_example = False

    # show example if wanted
    if see_example:
        for out in output:
            [
                [x1_img, y1_img, x2_img, y2_img],
                [w_table, h_table],
                [H_img, W_img],
            ] = img_dim(img, out)
            plt.plot(
                [x1_img, x2_img, x2_img, x1_img, x1_img],
                [y1_img, y1_img, y2_img, y2_img, y1_img],
                linestyle="-.",
                alpha=0.7,
            )
            # plt.scatter([x1_img, x2_img], [y1_img, y2_img])
        imgplot = plt.imshow(img)
        plt.savefig(pdf_file[:-4] + "-" + str(pg) + ".png")
        plt.show()

    interesting_areas = []

    # collect coordinates for found objects
    for x in output:
        [x1, y1, x2, y2] = bboxes_pdf(img, pdf_page, x)

        # x1,y1,x2,y2 where (x1, y1) -> left-top and (x2, y2) -> right-bottom in PDF coordinate space
        bbox_camelot = [",".join([str(x1), str(y1), str(x2), str(y2)])][0]
        interesting_areas.append(bbox_camelot)

    # call camelot on any interesting areas found by Yolov3
    # camelot flavor: 'lattice' for bordered tables, 'stream' for borderless
    # camelot >= v0.10.0: backend= 'poppler' or 'ghostscript'

    def run_camelot_extraction(use_flavor, areas, pdf, page, rtol, strip):
        """Helper to run Camelot with specific flavor and return results with accuracy."""
        kwargs = {
            'filepath': pdf,
            'pages': str(page),
            'flavor': use_flavor,
            'table_areas': areas,
            'backend': 'poppler',
        }

        if use_flavor == 'stream':
            kwargs['row_tol'] = rtol
        # lattice uses defaults - Camelot auto-detects lines

        if strip:
            kwargs['strip_text'] = strip

        try:
            result = camelot.read_pdf(**kwargs)
            # Calculate average accuracy
            total_acc = 0
            count = 0
            for t in result:
                if hasattr(t, 'parsing_report') and 'accuracy' in t.parsing_report:
                    total_acc += t.parsing_report['accuracy']
                    count += 1
            avg_acc = total_acc / count if count > 0 else 0
            return result, avg_acc
        except Exception as e:
            log.output('WARNING', f'Camelot {use_flavor} extraction failed: {e}')
            return None, 0

    # Auto-detect table type if flavor is 'auto'
    actual_flavor = flavor
    if flavor == 'auto':
        actual_flavor = detect_table_type_from_array(img)
        log.output('INFO', f'Auto-detected table type: {actual_flavor}')

        # In auto mode, try both flavors and pick the one with better accuracy
        result_primary, acc_primary = run_camelot_extraction(
            actual_flavor, interesting_areas, pdf_file, pg, row_tol, strip_text
        )
        log.output('INFO', f'{actual_flavor} extraction accuracy: {acc_primary:.1f}%')

        # Try the other flavor
        alt_flavor = 'stream' if actual_flavor == 'lattice' else 'lattice'
        result_alt, acc_alt = run_camelot_extraction(
            alt_flavor, interesting_areas, pdf_file, pg, row_tol, strip_text
        )
        log.output('INFO', f'{alt_flavor} extraction accuracy: {acc_alt:.1f}%')

        # Pick the better result (prefer lattice if accuracy is close)
        if result_alt is not None and acc_alt > acc_primary + 5:
            output_camelot = result_alt
            actual_flavor = alt_flavor
            log.output('INFO', f'Using {alt_flavor} (better accuracy: {acc_alt:.1f}% vs {acc_primary:.1f}%)')
        elif result_primary is not None:
            output_camelot = result_primary
            log.output('INFO', f'Using {actual_flavor} (accuracy: {acc_primary:.1f}%)')
        elif result_alt is not None:
            output_camelot = result_alt
            actual_flavor = alt_flavor
        else:
            output_camelot = []
    else:
        # User specified a flavor, use it directly
        log.output('INFO', f'Using user-specified flavor: {actual_flavor}')
        output_camelot, _ = run_camelot_extraction(
            actual_flavor, interesting_areas, pdf_file, pg, row_tol, strip_text
        )
        if output_camelot is None:
            output_camelot = []

    report = []

    # log camelot parsing report to django terminal
    for table in output_camelot:
        log.output("DEBUG", f"table parsing_report: {table.parsing_report}")
        report.append(table.parsing_report)

    # get camelot dataframes, added tableValidate() check
    output_camelot = [x.df for x in output_camelot if tableValidate(x.df)]

    # clean and process dataframes
    processed_tables = []
    for table in output_camelot:
        # replace NaN's with empty string
        table = table.fillna("")

        # Strip empty rows and columns
        table = strip_empty_rows_and_cols(table)

        # Process headers if enabled
        if merge_headers:
            table = process_table_headers(table, merge_headers=True)

        processed_tables.append(table)

    output_camelot = processed_tables

    # get pdf filename
    filename = Path(file_path).name

    # export and save to database
    # Note1:    CSV,EXCEL: optional arg 'index=[Bool]'
    #           if you wish to exclude the y indexing, set index=False (default is True)
    #
    # Note2:    Can format the JSON Export structure with optional arg 'orient=[String]'
    #           choices: split, records, index, values, table, columns (the default format)

    # Build bounding box data from interesting_areas (YOLO detection coordinates)
    bounding_boxes = []
    for area in interesting_areas:
        coords = area.split(',')
        if len(coords) == 4:
            bounding_boxes.append({
                'x0': float(coords[0]),
                'y0': float(coords[1]),
                'x1': float(coords[2]),
                'y1': float(coords[3])
            })

    for i, db in enumerate(output_camelot):
        # log.output('SUCCESS', f'found table: page {pg}, table {i}')

        # Get bounding box for this table (if available)
        bbox = bounding_boxes[i] if i < len(bounding_boxes) else None

        # Build structure_json from DataFrame
        structure = build_structure_json(db)

        # Get confidence from parsing report (if available)
        confidence = None
        if i < len(report) and report[i]:
            confidence = report[i].get('accuracy', 0) / 100.0  # Convert 0-100 to 0-1

        for key, value in extract_dir.items():
            # build path for file and export
            e_name = filename[:-4] + "-" + str(pg) + "-table-" + str(i) + "." + key
            e_path = PurePath.joinpath(value, e_name)

            # export to file
            if key == "csv":
                db.to_csv(str(e_path), index=False)
            elif key == "json":
                db.to_json(str(e_path), orient="columns")
            elif key == "xlsx":
                # Export to XLSX with cell spans and header formatting (US-018)
                export_to_xlsx(db, str(e_path), structure_json=structure, header_rows=1)

            # build cleaned path for database
            db_path = PurePath(PurePath(e_path).parts[-3], key, PurePath(e_path).name)

            # create csv database instance with rich fields (US-017)
            Extracted.objects.create(
                report=report_db,
                file=str(db_path),
                f_type=key,
                page_num=pg,
                table_num=i,
                # Rich metadata fields
                page_type=page_type,
                extraction_method=f'camelot_{actual_flavor}',
                confidence_score=confidence,
                structure_json=structure,
                bounding_box=bbox,
            )

    # log.output('INFO', f'finished processing page {page_number}')

    return report


# %%


def extract_tables_direct(file_path: str, page_number: int, output_type: str,
                          report_db, extract_dir: dict, flavor: str = 'auto',
                          row_tol: int = 2, strip_text: str = '\n',
                          merge_headers: bool = True,
                          page_type: Optional[str] = None) -> list:
    """
    Extract tables directly using multiple extractors without YOLO detection.
    Used for born-digital PDF pages where text layer is reliable.

    Runs both Camelot (lattice + stream) and pdfplumber extractors,
    then uses ExtractionScorer to select the best result for each table.

    Args:
        file_path: Path to PDF file
        page_number: Page number to process
        output_type: Output format type
        report_db: Database report instance
        extract_dir: Dictionary of extraction directories
        flavor: Camelot flavor ('auto', 'lattice', or 'stream') - used for fallback
        row_tol: Row tolerance for Camelot parsing
        strip_text: Characters to strip from cell text
        merge_headers: Whether to merge fragmented multi-row headers

    Returns:
        list: Parsing reports for extracted tables
    """
    log = Logging()
    pg = page_number

    log.output('INFO', f'[multi-extractor] Starting extraction for page {pg}')

    # Use MultiExtractor to run all backends and select best
    multi_extractor = MultiExtractor()

    try:
        best_results, comparison = multi_extractor.extract_with_comparison(
            file_path, pg, table_areas=None
        )
    except Exception as e:
        log.output('WARNING', f'[multi-extractor] All extractors failed: {e}')
        best_results = []
        comparison = {'extractors_run': [], 'total_candidates': 0}

    # Log extraction summary
    log.output('INFO', f'[multi-extractor] Ran {len(comparison.get("extractors_run", []))} extractors')
    for ext_info in comparison.get('extractors_run', []):
        log.output('DEBUG', f'[multi-extractor] {ext_info["name"]}: {ext_info["tables_found"]} table(s)')

    if not best_results:
        log.output('INFO', f'[multi-extractor] No tables found on page {pg}')
        return []

    # Log selected methods
    for sel in comparison.get('selected_methods', []):
        log.output('INFO',
            f'[multi-extractor] Selected {sel["method"]} '
            f'(score={sel["score"]:.4f}, confidence={sel["confidence"]:.3f})'
        )

    # Build parsing reports (for compatibility with existing code)
    report = []
    processed_tables = []
    extraction_methods = []
    processed_results = []  # Track original results for metadata access

    for result in best_results:
        # Create a parsing report compatible with Camelot format
        parsing_report = {
            'accuracy': result.confidence * 100,  # Convert 0-1 to 0-100
            'whitespace': result.metadata.get('parsing_report', {}).get('whitespace', 0),
            'extraction_method': result.method,
        }
        report.append(parsing_report)

        # Process the dataframe
        table = result.dataframe.copy()

        # Clean table
        table = table.fillna("")
        table = strip_empty_rows_and_cols(table)

        if merge_headers:
            table = process_table_headers(table, merge_headers=True)

        # Validate table
        if tableValidate(table):
            processed_tables.append(table)
            extraction_methods.append(result.method)
            processed_results.append(result)  # Keep track of the result

            log.output('DEBUG',
                f'[multi-extractor] Table validated: '
                f'{len(table)} rows x {len(table.columns)} cols, method={result.method}'
            )

    # Get pdf filename
    filename = Path(file_path).name

    # Export and save to database
    for i, (db, method, result) in enumerate(zip(processed_tables, extraction_methods, processed_results)):
        # Extract bounding box from result metadata
        bbox = result.metadata.get('bounding_box') if result.metadata else None

        # Build structure_json from DataFrame
        structure = build_structure_json(db, result.metadata if result.metadata else None)

        # Get confidence score from the result
        confidence = result.confidence

        for key, value in extract_dir.items():
            e_name = filename[:-4] + "-" + str(pg) + "-table-" + str(i) + "." + key
            e_path = PurePath.joinpath(value, e_name)

            if key == "csv":
                db.to_csv(str(e_path), index=False)
            elif key == "json":
                # Include extraction method in JSON output (backwards compatible - additive)
                # Use to_json to get columns format, then parse and add metadata
                import json as json_lib
                from io import StringIO

                # Get JSON string in columns format (original format)
                json_str = db.to_json(orient="columns")
                json_output = json_lib.loads(json_str)

                # Add extraction metadata (additive - backwards compatible)
                json_output['_extraction_metadata'] = {
                    'method': method,
                    'page_num': pg,
                    'table_num': i,
                }

                with open(str(e_path), 'w') as f:
                    json_lib.dump(json_output, f)
            elif key == "xlsx":
                # Export to XLSX with cell spans and header formatting (US-018)
                export_to_xlsx(db, str(e_path), structure_json=structure, header_rows=1)

            db_path = PurePath(PurePath(e_path).parts[-3], key, PurePath(e_path).name)

            # Create database instance with rich fields (US-017)
            Extracted.objects.create(
                report=report_db,
                file=str(db_path),
                f_type=key,
                page_num=pg,
                table_num=i,
                # Rich metadata fields
                page_type=page_type,
                extraction_method=method,
                confidence_score=confidence,
                structure_json=structure,
                bounding_box=bbox,
            )

    log.output('INFO', f'[multi-extractor] Page {pg}: exported {len(processed_tables)} table(s)')

    return report


# %%


def extract_tables_vision(file_path: str, page_number: int, output_type: str,
                          report_db, extract_dir: dict, flavor: str = 'auto',
                          row_tol: int = 2, strip_text: str = '\n',
                          merge_headers: bool = True,
                          page_type: Optional[str] = None) -> list:
    """
    Extract tables using VisionExtractor for scanned PDF pages.
    Uses img2table for vision-based table detection and extraction.

    Results are scored using ExtractionScorer (same as born-digital) to ensure
    consistent quality selection across extraction methods.

    Args:
        file_path: Path to PDF file
        page_number: Page number to process
        output_type: Output format type
        report_db: Database report instance
        extract_dir: Dictionary of extraction directories
        flavor: Unused for vision extraction (kept for API compatibility)
        row_tol: Unused for vision extraction (kept for API compatibility)
        strip_text: Characters to strip from cell text
        merge_headers: Whether to merge fragmented multi-row headers

    Returns:
        list: Parsing reports for extracted tables
    """
    log = Logging()
    pg = page_number

    log.output('INFO', f'[vision-extractor] Starting extraction for page {pg}')

    # Initialize VisionExtractor and scorer
    vision_extractor = VisionExtractor(
        implicit_rows=True,
        borderless_tables=True,
        min_confidence=0.5
    )
    scorer = ExtractionScorer()

    try:
        # Extract tables using vision-based detection
        results = vision_extractor.extract(file_path, pg, table_areas=None)
        log.output('INFO', f'[vision-extractor] Found {len(results)} table(s) on page {pg}')
    except Exception as e:
        log.output('WARNING', f'[vision-extractor] Extraction failed: {e}')
        return []

    if not results:
        log.output('INFO', f'[vision-extractor] No tables found on page {pg}')
        return []

    # Score all results (same scoring as born-digital)
    scored_results = scorer.score_all(results)

    # Log scores
    for result, score in scored_results:
        log.output('DEBUG',
            f'[vision-extractor] {result.method}: score={score:.4f}, '
            f'confidence={result.confidence:.3f}'
        )

    # Build parsing reports (for compatibility with existing code)
    report = []
    processed_tables = []
    extraction_methods = []
    processed_results = []  # Track original results for metadata access

    for result, score in scored_results:
        # Create a parsing report compatible with Camelot format
        parsing_report = {
            'accuracy': result.confidence * 100,  # Convert 0-1 to 0-100
            'whitespace': 0,  # Not applicable for vision extraction
            'extraction_method': result.method,
            'computed_score': score,
        }
        report.append(parsing_report)

        # Process the dataframe
        table = result.dataframe.copy()

        # Clean table
        table = table.fillna("")
        table = strip_empty_rows_and_cols(table)

        if merge_headers:
            table = process_table_headers(table, merge_headers=True)

        # Validate table
        if tableValidate(table):
            processed_tables.append(table)
            extraction_methods.append(result.method)
            processed_results.append(result)  # Keep track of the result

            log.output('DEBUG',
                f'[vision-extractor] Table validated: '
                f'{len(table)} rows x {len(table.columns)} cols, method={result.method}'
            )

    # Get pdf filename
    filename = Path(file_path).name

    # Export and save to database (same format as born-digital)
    for i, (db, method, result) in enumerate(zip(processed_tables, extraction_methods, processed_results)):
        # Extract bounding box from result metadata
        bbox = result.metadata.get('bounding_box') if result.metadata else None

        # Build structure_json from DataFrame
        structure = build_structure_json(db, result.metadata if result.metadata else None)

        # Get confidence score from the result
        confidence = result.confidence

        for key, value in extract_dir.items():
            e_name = filename[:-4] + "-" + str(pg) + "-table-" + str(i) + "." + key
            e_path = PurePath.joinpath(value, e_name)

            if key == "csv":
                db.to_csv(str(e_path), index=False)
            elif key == "json":
                import json as json_lib

                json_str = db.to_json(orient="columns")
                json_output = json_lib.loads(json_str)

                # Add extraction metadata (additive - backwards compatible)
                json_output['_extraction_metadata'] = {
                    'method': method,
                    'page_num': pg,
                    'table_num': i,
                    'page_type': page_type or 'scanned',
                }

                with open(str(e_path), 'w') as f:
                    json_lib.dump(json_output, f)
            elif key == "xlsx":
                # Export to XLSX with cell spans and header formatting (US-018)
                export_to_xlsx(db, str(e_path), structure_json=structure, header_rows=1)

            db_path = PurePath(PurePath(e_path).parts[-3], key, PurePath(e_path).name)

            # Create database instance with rich fields (US-017)
            Extracted.objects.create(
                report=report_db,
                file=str(db_path),
                f_type=key,
                page_num=pg,
                table_num=i,
                # Rich metadata fields
                page_type=page_type,
                extraction_method=method,
                confidence_score=confidence,
                structure_json=structure,
                bounding_box=bbox,
            )

    log.output('INFO', f'[vision-extractor] Page {pg}: exported {len(processed_tables)} table(s)')

    return report


# %%
if __name__ == "__main__":

    # for module import and calling
    detect_tables()

# %%
