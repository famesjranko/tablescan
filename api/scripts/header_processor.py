"""
header_processor.py
    Post-processing for extracted tables to merge fragmented multi-row headers.
"""

import pandas as pd
import numpy as np
import re


# Pattern to detect numeric/data values (not headers)
# Matches: 34.5%, 1199 sec, n=1, 98.3% n=2, (97.7%, n=3), 1672.1 sec, n=4, etc.
_NUMERIC_DATA_PATTERN = re.compile(
    r'^[\s\(\[]*'  # Optional leading whitespace, parens, brackets
    r'[\d,.$€£¥]+'  # Must start with digits or currency
    r'[\d,.\s%]*'  # More digits, decimals, spaces, percent
    r'(?:'  # Optional suffix group
        r'(?:sec|ms|min|hr|n\s*=\s*\d+|%|[a-z]{1,3})'  # Units or n=X
        r'[\s,]*'
    r')*'
    r'[\s\)\]]*$',  # Optional trailing whitespace, parens
    re.IGNORECASE
)

# Pattern for cells that are clearly labels/headers
_HEADER_LABEL_PATTERN = re.compile(
    r'^[A-Za-z][A-Za-z\s\-_/]+$'  # Starts with letter, mostly letters
)


def _is_numeric_data_cell(cell_str: str) -> bool:
    """Check if a cell contains numeric data (not a header label)."""
    if not cell_str:
        return False

    # Quick check: if it starts with a digit or currency, likely numeric
    if cell_str[0].isdigit() or cell_str[0] in '$€£¥(':
        return True

    # Check against numeric pattern
    if _NUMERIC_DATA_PATTERN.match(cell_str):
        return True

    # Check for percentage or number anywhere with few letters
    digits = sum(1 for c in cell_str if c.isdigit())
    letters = sum(1 for c in cell_str if c.isalpha())

    # If more digits than letters, it's probably data
    if digits > 0 and digits >= letters:
        return True

    return False


def is_likely_header_row(row: pd.Series) -> bool:
    """
    Determine if a row is likely part of a header based on its characteristics.

    Header rows typically:
    - Contain mostly text labels (not numeric values)
    - May have some empty cells due to merged cell spans
    - Have short text values (column names, not data)

    Args:
        row: A pandas Series representing a row

    Returns:
        True if the row appears to be a header row
    """
    total = len(row)
    if total == 0:
        return False

    numeric_count = 0
    text_count = 0
    empty_count = 0

    for cell in row:
        cell_str = str(cell).strip()
        if not cell_str or cell_str.lower() == 'nan':
            empty_count += 1
            continue

        # Use improved numeric detection
        if _is_numeric_data_cell(cell_str):
            numeric_count += 1
        else:
            text_count += 1

    # If all cells are empty, not a header
    if empty_count == total:
        return False

    total_content = numeric_count + text_count
    if total_content == 0:
        return False

    text_ratio = text_count / total_content

    # Header rows have mostly text (>= 70% - raised from 60%)
    # Also require at least 2 text cells to avoid false positives
    return text_ratio >= 0.70 and text_count >= 2


def detect_header_rows(df: pd.DataFrame, max_header_rows: int = 4) -> int:
    """
    Detect how many rows at the top of the DataFrame are header rows.

    Args:
        df: The DataFrame to analyze
        max_header_rows: Maximum number of rows to consider as headers

    Returns:
        Number of header rows detected (0 if none or already processed)
    """
    if df.empty:
        return 0

    header_count = 0

    # Check up to max_header_rows
    for i in range(min(max_header_rows, len(df))):
        row = df.iloc[i]
        if is_likely_header_row(row):
            header_count += 1
        else:
            # Stop when we hit a data row
            break

    return header_count


def detect_header_spans(df: pd.DataFrame, num_header_rows: int) -> list:
    """
    Detect column and row spans from empty cell patterns in multi-row headers.

    Colspan: A cell spans multiple columns if cells to its right are empty
    and the row below has content in those positions.

    Rowspan: A cell spans multiple rows if cells below it are empty.

    Args:
        df: The DataFrame to analyze
        num_header_rows: Number of header rows to examine

    Returns:
        List of dicts with keys: row, col, value, colspan, rowspan, children
        - row: 0-indexed row number within header
        - col: 0-indexed column number
        - value: The cell's text content
        - colspan: Number of columns this cell spans (default 1)
        - rowspan: Number of rows this cell spans (default 1)
        - children: List of child header values (from row below) if colspan > 1
    """
    if df.empty or num_header_rows <= 0:
        return []

    header_rows = df.iloc[:num_header_rows]
    spans = []

    # Track which cells are "covered" by a rowspan from above
    covered = set()  # (row, col) pairs that are covered by rowspan

    for row_idx in range(num_header_rows):
        col_idx = 0
        while col_idx < len(df.columns):
            # Skip cells covered by rowspan from above
            if (row_idx, col_idx) in covered:
                col_idx += 1
                continue

            cell_value = str(header_rows.iloc[row_idx, col_idx]).strip()

            if cell_value and cell_value.lower() != 'nan':
                # Count consecutive empty cells to the right (colspan)
                colspan = 1
                check_col = col_idx + 1

                while check_col < len(df.columns):
                    next_val = str(header_rows.iloc[row_idx, check_col]).strip()
                    if not next_val or next_val.lower() == 'nan':
                        # Confirm span if row below has content
                        if row_idx + 1 < num_header_rows:
                            below = str(header_rows.iloc[row_idx + 1, check_col]).strip()
                            if below and below.lower() != 'nan':
                                colspan += 1
                                check_col += 1
                                continue
                    break

                # Count consecutive empty cells below (rowspan)
                rowspan = 1
                for check_row in range(row_idx + 1, num_header_rows):
                    below_val = str(header_rows.iloc[check_row, col_idx]).strip()
                    if not below_val or below_val.lower() == 'nan':
                        rowspan += 1
                        # Mark this cell as covered
                        covered.add((check_row, col_idx))
                    else:
                        break

                # Collect children (values in row below this span)
                children = []
                if row_idx + 1 < num_header_rows and colspan > 1:
                    for c in range(col_idx, col_idx + colspan):
                        child = str(header_rows.iloc[row_idx + 1, c]).strip()
                        if child and child.lower() != 'nan':
                            children.append(child)

                spans.append({
                    'row': row_idx,
                    'col': col_idx,
                    'value': cell_value,
                    'colspan': colspan,
                    'rowspan': rowspan,
                    'children': children if children else None
                })
                col_idx += colspan
            else:
                col_idx += 1

    return spans


def merge_header_rows_hierarchical(
    df: pd.DataFrame,
    num_header_rows: int,
    separator: str = " > "
) -> pd.DataFrame:
    """
    Merge multiple header rows preserving hierarchy via separator.

    Unlike simple space-joining, this creates column names like
    "Parent > Child" to show the hierarchy explicitly.

    Args:
        df: The DataFrame with multi-row headers
        num_header_rows: Number of rows to merge into the header
        separator: String to join parent and child headers

    Returns:
        DataFrame with merged hierarchical headers
    """
    if num_header_rows <= 1 or df.empty:
        return df

    spans = detect_header_spans(df, num_header_rows)
    header_rows = df.iloc[:num_header_rows]

    # Build column names with parent prefix
    new_headers = []
    for col_idx in range(len(df.columns)):
        parts = []
        for span in spans:
            # Check if this column is covered by this span
            if span['col'] <= col_idx < span['col'] + span['colspan']:
                parts.append((span['row'], span['value']))

        # Sort by row (parent first)
        parts.sort(key=lambda x: x[0])
        header_name = separator.join(p[1] for p in parts) if parts else f'Column_{col_idx}'
        new_headers.append(header_name)

    result = df.iloc[num_header_rows:].copy()
    result.columns = new_headers
    return result.reset_index(drop=True)


def merge_header_rows(df: pd.DataFrame, num_header_rows: int) -> pd.DataFrame:
    """
    Merge multiple header rows into a single header.

    Combines cell values vertically, joining with a space separator.
    This is the legacy function - prefer merge_header_rows_hierarchical
    for new code.

    Args:
        df: The DataFrame with fragmented headers
        num_header_rows: Number of rows to merge into the header

    Returns:
        DataFrame with merged header
    """
    if num_header_rows <= 1 or df.empty:
        return df

    # Extract header rows
    header_rows = df.iloc[:num_header_rows]

    # Merge each column's header values
    new_headers = []
    for col in df.columns:
        # Get all header values for this column
        header_values = []
        for i in range(num_header_rows):
            val = str(header_rows.iloc[i][col]).strip()
            if val and val.lower() != 'nan':
                header_values.append(val)

        # Join non-empty values
        merged_header = ' '.join(header_values) if header_values else f'Column_{col}'
        new_headers.append(merged_header)

    # Create new DataFrame with merged headers
    data_rows = df.iloc[num_header_rows:]
    result = data_rows.copy()
    result.columns = new_headers
    result = result.reset_index(drop=True)

    return result


def clean_column_names(df: pd.DataFrame) -> pd.DataFrame:
    """
    Clean up column names by removing extra whitespace and newlines.

    Args:
        df: DataFrame to clean

    Returns:
        DataFrame with cleaned column names
    """
    df = df.copy()

    # Clean column names
    new_columns = []
    for col in df.columns:
        col_str = str(col)
        # Replace newlines and multiple spaces with single space
        col_str = ' '.join(col_str.split())
        new_columns.append(col_str)

    df.columns = new_columns
    return df


def process_table_headers(df: pd.DataFrame, merge_headers: bool = True,
                          max_header_rows: int = 4) -> tuple:
    """
    Main function to detect and merge fragmented multi-row headers.

    Always detects hierarchy and uses hierarchical separator for column names.
    Returns both the processed DataFrame and header span information for
    downstream consumers (XLSX export, frontend preview).

    Args:
        df: The extracted table DataFrame
        merge_headers: Whether to attempt header merging
        max_header_rows: Maximum number of rows to consider as headers

    Returns:
        tuple: (processed_df, header_spans)
            - processed_df: DataFrame with processed headers
            - header_spans: List of span dicts for multi-row header rendering
    """
    if df.empty or not merge_headers:
        return df, []

    # Detect how many header rows exist
    num_header_rows = detect_header_rows(df, max_header_rows)

    # Detect header spans (for XLSX export and frontend rendering)
    header_spans = []
    if num_header_rows > 1:
        header_spans = detect_header_spans(df, num_header_rows)
        # Use hierarchical merge for explicit parent-child naming
        df = merge_header_rows_hierarchical(df, num_header_rows)

    # Clean up column names
    df = clean_column_names(df)

    return df, header_spans


def strip_empty_rows_and_cols(df: pd.DataFrame) -> pd.DataFrame:
    """
    Remove completely empty rows and columns from the DataFrame.

    Args:
        df: DataFrame to clean

    Returns:
        DataFrame with empty rows/columns removed
    """
    if df.empty:
        return df

    # Remove rows where all values are empty/NaN
    df = df.replace('', np.nan)
    df = df.dropna(how='all')

    # Remove columns where all values are empty/NaN
    df = df.dropna(axis=1, how='all')

    # Reset index
    df = df.reset_index(drop=True)

    # Replace NaN back to empty string
    df = df.fillna('')

    return df
