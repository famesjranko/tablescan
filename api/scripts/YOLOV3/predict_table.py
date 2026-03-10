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
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "api.settings")
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
                  flavor='auto', row_tol=2, strip_text='\n', merge_headers=True) -> list:
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
    for i, db in enumerate(output_camelot):
        # log.output('SUCCESS', f'found table: page {pg}, table {i}')
        for key, value in extract_dir.items():
            # build path for file and export
            e_name = filename[:-4] + "-" + str(pg) + "-table-" + str(i) + "." + key
            e_path = PurePath.joinpath(value, e_name)

            # export to file
            if key == "csv":
                db.to_csv(str(e_path), index=False)
            elif key == "json":
                db.to_json(str(e_path), orient="columns")

            # build cleaned path for database
            db_path = PurePath(PurePath(e_path).parts[-3], key, PurePath(e_path).name)

            # create csv database instance
            Extracted.objects.create(
                report=report_db,
                file=str(db_path),
                f_type=key,
                page_num=pg,
                table_num=i,
            )

    # log.output('INFO', f'finished processing page {page_number}')

    return report


# %%
if __name__ == "__main__":

    # for module import and calling
    detect_tables()

# %%
