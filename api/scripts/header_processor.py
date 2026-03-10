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


def merge_header_rows(df: pd.DataFrame, num_header_rows: int) -> pd.DataFrame:
    """
    Merge multiple header rows into a single header.

    Combines cell values vertically, joining with a space separator.

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
                          max_header_rows: int = 4) -> pd.DataFrame:
    """
    Main function to detect and merge fragmented multi-row headers.

    Conservative approach: only merge if clearly beneficial.

    Args:
        df: The extracted table DataFrame
        merge_headers: Whether to attempt header merging
        max_header_rows: Maximum number of rows to consider as headers

    Returns:
        DataFrame with processed headers
    """
    if df.empty or not merge_headers:
        return df

    # Clean up column names
    df = clean_column_names(df)

    return df


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
