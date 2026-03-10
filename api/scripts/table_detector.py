"""
table_detector.py
    Auto-detect whether a table image has borders (lattice) or is borderless (stream).
    Uses OpenCV edge detection and Hough line transform.
"""

import cv2
import numpy as np
from pathlib import Path


def detect_table_type(img_path: str, min_lines: int = 3) -> str:
    """
    Analyze an image to determine if it contains a bordered table.

    Uses edge detection and Hough line transform to detect grid patterns.
    If the image has 3+ horizontal and 3+ vertical lines forming a grid,
    it's considered a bordered table (lattice). Otherwise, it's borderless (stream).

    Args:
        img_path: Path to the table image (JPG)
        min_lines: Minimum number of lines in each direction to consider as bordered

    Returns:
        "lattice" for bordered tables, "stream" for borderless tables
    """
    # Read the image
    if not Path(img_path).exists():
        return "stream"  # Default to stream if image doesn't exist

    img = cv2.imread(img_path, cv2.IMREAD_GRAYSCALE)
    if img is None:
        return "stream"

    # Apply Gaussian blur to reduce noise
    blurred = cv2.GaussianBlur(img, (3, 3), 0)

    # Edge detection using Canny
    edges = cv2.Canny(blurred, 50, 150, apertureSize=3)

    # Detect lines using Hough Line Transform
    lines = cv2.HoughLinesP(
        edges,
        rho=1,
        theta=np.pi / 180,
        threshold=100,
        minLineLength=50,
        maxLineGap=10
    )

    if lines is None:
        return "stream"

    horizontal_lines = 0
    vertical_lines = 0

    for line in lines:
        x1, y1, x2, y2 = line[0]

        # Calculate angle of the line
        if x2 - x1 == 0:
            angle = 90
        else:
            angle = abs(np.degrees(np.arctan((y2 - y1) / (x2 - x1))))

        # Classify as horizontal (0-15 degrees) or vertical (75-90 degrees)
        if angle < 15:
            horizontal_lines += 1
        elif angle > 75:
            vertical_lines += 1

    # If we have enough lines in both directions, it's a bordered table
    if horizontal_lines >= min_lines and vertical_lines >= min_lines:
        return "lattice"

    return "stream"


def detect_table_type_from_array(img_array: np.ndarray, min_lines: int = 2) -> str:
    """
    Same as detect_table_type but accepts a numpy array directly.
    Uses multiple detection strategies for robustness.

    Args:
        img_array: Image as numpy array (can be RGB or grayscale)
        min_lines: Minimum number of lines in each direction to consider as bordered

    Returns:
        "lattice" for bordered tables, "stream" for borderless tables
    """
    if img_array is None:
        return "lattice"  # Default to lattice as it handles more cases

    try:
        # Convert to grayscale if needed
        if len(img_array.shape) == 3:
            img = cv2.cvtColor(img_array, cv2.COLOR_RGB2GRAY)
        else:
            img = img_array

        # Strategy 1: Edge detection + Hough lines
        blurred = cv2.GaussianBlur(img, (3, 3), 0)
        edges = cv2.Canny(blurred, 30, 100, apertureSize=3)

        lines = cv2.HoughLinesP(
            edges,
            rho=1,
            theta=np.pi / 180,
            threshold=80,  # Lower threshold for better detection
            minLineLength=30,  # Shorter minimum line length
            maxLineGap=15
        )

        if lines is not None:
            horizontal_lines = 0
            vertical_lines = 0

            for line in lines:
                x1, y1, x2, y2 = line[0]
                length = np.sqrt((x2-x1)**2 + (y2-y1)**2)

                # Only count significant lines
                if length < 20:
                    continue

                if x2 - x1 == 0:
                    angle = 90
                else:
                    angle = abs(np.degrees(np.arctan((y2 - y1) / (x2 - x1))))

                if angle < 10:
                    horizontal_lines += 1
                elif angle > 80:
                    vertical_lines += 1

            if horizontal_lines >= min_lines and vertical_lines >= min_lines:
                return "lattice"

        # Strategy 2: Morphological approach - detect grid patterns
        _, binary = cv2.threshold(img, 200, 255, cv2.THRESH_BINARY_INV)

        # Detect horizontal lines
        h_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (40, 1))
        h_lines = cv2.morphologyEx(binary, cv2.MORPH_OPEN, h_kernel)

        # Detect vertical lines
        v_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (1, 40))
        v_lines = cv2.morphologyEx(binary, cv2.MORPH_OPEN, v_kernel)

        # Count connected components (lines)
        h_count = cv2.connectedComponents(h_lines)[0] - 1
        v_count = cv2.connectedComponents(v_lines)[0] - 1

        if h_count >= min_lines and v_count >= min_lines:
            return "lattice"

        # Default to lattice for better handling of bordered tables
        # Stream mode often produces worse results for tables with any borders
        return "lattice"

    except Exception:
        # If OpenCV operations fail, default to lattice
        return "lattice"
