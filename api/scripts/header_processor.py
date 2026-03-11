"""
header_processor.py
    Post-processing for extracted tables to merge fragmented multi-row headers.
"""

import pandas as pd
import numpy as np


def is_likely_header_row(row: pd.Series) -> bool:
    """
    Determine if a row is likely part of a header based on its characteristics.

    Header rows typically:
    - Contain mostly text (not numeric values)
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
        if not cell_str:
            empty_count += 1
            continue

        # Check if cell is purely numeric (data row indicator)
        cleaned = cell_str.replace(',', '').replace('%', '').replace('.', '')
        cleaned = cleaned.replace('n=', '').replace('sec', '').strip()
        if cleaned.isdigit():
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

    # Header rows have mostly text (>= 60%)
    # Data rows have mostly numbers
    return text_ratio >= 0.6


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
    Detect column spans from empty cell patterns in multi-row headers.

    A cell is considered to span multiple columns if:
    - It has a non-empty value
    - The cells to its right in the same row are empty
    - The row below has content in those empty positions

    Args:
        df: The DataFrame to analyze
        num_header_rows: Number of header rows to examine

    Returns:
        List of dicts with keys: row, col, value, colspan, children
        - row: 0-indexed row number within header
        - col: 0-indexed column number
        - value: The cell's text content
        - colspan: Number of columns this cell spans
        - children: List of child header values (from row below) if colspan > 1
    """
    if df.empty or num_header_rows <= 0:
        return []

    header_rows = df.iloc[:num_header_rows]
    spans = []

    for row_idx in range(num_header_rows):
        col_idx = 0
        while col_idx < len(df.columns):
            cell_value = str(header_rows.iloc[row_idx, col_idx]).strip()

            if cell_value and cell_value.lower() != 'nan':
                # Count consecutive empty cells to the right
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
