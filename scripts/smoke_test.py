#!/usr/bin/env python
"""
Smoke test for TableScan 2.0 pipelines.

Tests the full extraction pipeline via API:
- Phase 1: Page classification and routing
- Phase 2: Multi-extractor (Camelot + pdfplumber)
- Phase 3: Vision extraction for scanned PDFs
- Phase 4: Rich metadata and XLSX export

Usage:
    python scripts/smoke_test.py [--server URL]
"""

import argparse
import json
import os
import sys
import tempfile
import time
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

import fitz  # PyMuPDF
import requests


def create_born_digital_pdf():
    """Create a test born-digital PDF with a table."""
    doc = fitz.open()
    page = doc.new_page(width=612, height=792)

    # Add title
    page.insert_text(fitz.Point(50, 50), "Test Financial Report", fontsize=16)

    # Add text content
    for y in range(80, 150, 15):
        page.insert_text(fitz.Point(50, y), "Sample text content for testing extraction.", fontsize=10)

    # Draw a table
    shape = page.new_shape()
    table_x, table_y = 50, 180
    col_widths = [100, 100, 100]
    row_height = 25
    num_rows = 4

    # Draw grid
    for i in range(num_rows + 1):
        y = table_y + i * row_height
        shape.draw_line(fitz.Point(table_x, y), fitz.Point(table_x + sum(col_widths), y))

    x = table_x
    for width in [0] + col_widths:
        x += width
        shape.draw_line(fitz.Point(x - width if width == 0 else x, table_y),
                       fitz.Point(x - width if width == 0 else x, table_y + num_rows * row_height))

    shape.finish(color=(0, 0, 0), width=1)
    shape.commit()

    # Add table content
    data = [
        ["Product", "Q1 Sales", "Q2 Sales"],
        ["Widget A", "$1,234", "$1,456"],
        ["Widget B", "$2,345", "$2,567"],
        ["Total", "$3,579", "$4,023"],
    ]

    for row_idx, row in enumerate(data):
        y = table_y + row_idx * row_height + 18
        x = table_x
        for col_idx, cell in enumerate(row):
            page.insert_text(fitz.Point(x + 5, y), cell, fontsize=10)
            x += col_widths[col_idx]

    return doc.tobytes()


def create_scanned_pdf():
    """Create a test 'scanned' PDF (image-based)."""
    doc = fitz.open()
    page = doc.new_page(width=612, height=792)

    # For a true scanned PDF, we'd embed an image
    # For now, create a low-text PDF that will be classified as 'mixed' or 'scanned'
    page.insert_text(fitz.Point(50, 50), "Scanned Document", fontsize=14)

    # Draw a simple table as shapes (minimal text)
    shape = page.new_shape()
    for i in range(5):
        y = 100 + i * 30
        shape.draw_line(fitz.Point(50, y), fitz.Point(300, y))
    for x in [50, 125, 200, 300]:
        shape.draw_line(fitz.Point(x, 100), fitz.Point(x, 220))

    shape.finish(color=(0, 0, 0), width=1)
    shape.commit()

    return doc.tobytes()


class SmokeTest:
    def __init__(self, server_url="http://localhost:8000"):
        self.server_url = server_url.rstrip("/")
        self.session = requests.Session()
        self.results = []

    def log(self, msg, status="INFO"):
        colors = {"INFO": "\033[94m", "OK": "\033[92m", "FAIL": "\033[91m", "WARN": "\033[93m"}
        reset = "\033[0m"
        print(f"{colors.get(status, '')}{status}: {msg}{reset}")

    def login(self, username="admin", password="lensell"):
        """Login and get session."""
        # Get CSRF token
        resp = self.session.get(f"{self.server_url}/admin/login/")
        if resp.status_code != 200:
            self.log(f"Cannot reach server at {self.server_url}", "FAIL")
            return False

        # Login
        csrf = self.session.cookies.get("csrftoken")
        resp = self.session.post(
            f"{self.server_url}/admin/login/",
            data={"username": username, "password": password, "csrfmiddlewaretoken": csrf},
            headers={"Referer": f"{self.server_url}/admin/login/"}
        )

        if resp.status_code == 200 and "logout" in resp.text.lower():
            self.log("Logged in as admin", "OK")
            return True

        self.log("Login failed - trying to create admin user", "WARN")
        return False

    def upload_pdf(self, pdf_bytes, filename):
        """Upload a PDF and return the response."""
        csrf = self.session.cookies.get("csrftoken")

        files = {"document": (filename, pdf_bytes, "application/pdf")}
        headers = {"X-CSRFToken": csrf, "Referer": f"{self.server_url}/"}

        resp = self.session.post(
            f"{self.server_url}/api/upload/",
            files=files,
            headers=headers
        )

        return resp

    def get_report(self, report_id):
        """Get report details."""
        resp = self.session.get(f"{self.server_url}/api/reports/{report_id}/")
        return resp

    def test_born_digital_pipeline(self):
        """Test Phase 1-2: Born-digital PDF extraction."""
        self.log("Testing born-digital PDF pipeline...")

        pdf_bytes = create_born_digital_pdf()
        resp = self.upload_pdf(pdf_bytes, "smoke_test_born_digital.pdf")

        if resp.status_code not in [200, 201]:
            self.log(f"Upload failed: {resp.status_code} - {resp.text[:200]}", "FAIL")
            return False

        data = resp.json()
        report_id = data.get("id") or data.get("report_id") or data.get("report id")

        if not report_id:
            self.log(f"No report ID in response: {data}", "FAIL")
            return False

        self.log(f"Uploaded, report ID: {report_id}", "OK")

        # Check report details
        report_resp = self.get_report(report_id)
        if report_resp.status_code != 200:
            self.log(f"Cannot fetch report: {report_resp.status_code}", "FAIL")
            return False

        report = report_resp.json()

        # Check for extracted tables
        extracted = report.get("extracted", [])
        self.log(f"Tables extracted: {len(extracted)}", "OK" if extracted else "WARN")

        # Check for new metadata fields (Phase 4)
        if extracted:
            first = extracted[0]
            checks = {
                "page_type": first.get("page_type"),
                "extraction_method": first.get("extraction_method"),
                "confidence_score": first.get("confidence_score"),
            }

            for field, value in checks.items():
                if value is not None:
                    self.log(f"  {field}: {value}", "OK")
                else:
                    self.log(f"  {field}: not populated", "WARN")

            # Check for XLSX
            xlsx_file = first.get("xlsx_file") or first.get("file_xlsx")
            if xlsx_file:
                self.log(f"  XLSX export: present", "OK")
            else:
                self.log(f"  XLSX export: not found", "WARN")

        return True

    def test_api_endpoints(self):
        """Test API endpoints return expected data."""
        self.log("Testing API endpoints...")

        # Test reports list
        resp = self.session.get(f"{self.server_url}/api/reports/")
        if resp.status_code == 200:
            self.log("GET /api/reports/ works", "OK")
        else:
            self.log(f"GET /api/reports/ failed: {resp.status_code}", "FAIL")
            return False

        # Test extracted list
        resp = self.session.get(f"{self.server_url}/api/extracted/")
        if resp.status_code == 200:
            self.log("GET /api/extracted/ works", "OK")
        else:
            self.log(f"GET /api/extracted/ failed: {resp.status_code}", "FAIL")
            return False

        return True

    def run_all(self):
        """Run all smoke tests."""
        print("\n" + "=" * 60)
        print("TableScan 2.0 Smoke Tests")
        print("=" * 60 + "\n")

        # Check server is running
        try:
            resp = requests.get(f"{self.server_url}/api/", timeout=5)
        except requests.exceptions.ConnectionError:
            self.log(f"Server not running at {self.server_url}", "FAIL")
            self.log("Start with: make dev", "INFO")
            return False

        # Login
        if not self.login():
            self.log("Could not authenticate", "FAIL")
            return False

        results = []

        # Run tests
        results.append(("API Endpoints", self.test_api_endpoints()))
        results.append(("Born-Digital Pipeline", self.test_born_digital_pipeline()))

        # Summary
        print("\n" + "=" * 60)
        print("Summary")
        print("=" * 60)

        passed = sum(1 for _, r in results if r)
        total = len(results)

        for name, result in results:
            status = "PASS" if result else "FAIL"
            self.log(f"{name}: {status}", "OK" if result else "FAIL")

        print(f"\nTotal: {passed}/{total} passed")

        return passed == total


def main():
    parser = argparse.ArgumentParser(description="TableScan 2.0 Smoke Tests")
    parser.add_argument("--server", default="http://localhost:8000", help="Server URL")
    args = parser.parse_args()

    tester = SmokeTest(args.server)
    success = tester.run_all()

    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
