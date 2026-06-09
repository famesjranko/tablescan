#!/usr/bin/env bash
#
# verify_docling_isolated.sh
#   Fast, host-safe verification of DoclingExtractor logic.
#
#   Runs scripts/docling_isolated_checks.py inside an ephemeral
#   python:3.11-slim container with ONLY pandas + pymupdf + pytest installed.
#   No torch, no docling model weights, no Django/camelot, no full image
#   build, and nothing installed on the host. The container is --rm and any
#   root-owned scratch files it creates are removed via a throwaway container.
#
#   This validates the extractor's pure logic + control flow in seconds. The
#   full docling integration path (region crop -> Docling -> dataframe) is
#   covered by the importorskip-guarded tests in api/tests/test_extractors.py
#   and runs as part of the normal suite once docling is installed.
#
# Usage:
#   scripts/verify_docling_isolated.sh
#
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
IMAGE="python:3.11-slim"

if ! command -v docker >/dev/null 2>&1; then
    echo "docker is required but not found on PATH" >&2
    exit 1
fi

WORK="$(mktemp -d)"
cleanup() {
    # Container may have written root-owned caches; remove them via a container.
    docker run --rm -v "$WORK":/w "$IMAGE" rm -rf /w/exti /w/__pycache__ \
        /w/.pytest_cache /w/test_docling_checks.py >/dev/null 2>&1 || true
    rm -rf "$WORK" 2>/dev/null || true
}
trap cleanup EXIT

# Assemble a minimal `exti` package from the REAL source files so that
# `from .base import ...` resolves without pulling the full extractors package
# (which would require camelot / pdfplumber / img2table / etc.).
mkdir -p "$WORK/exti"
cp "$REPO/api/scripts/extractors/base.py" "$WORK/exti/base.py"
cp "$REPO/api/scripts/extractors/docling_extractor.py" "$WORK/exti/docling_extractor.py"
: > "$WORK/exti/__init__.py"
cp "$REPO/scripts/docling_isolated_checks.py" "$WORK/test_docling_checks.py"

echo "Running isolated DoclingExtractor checks in $IMAGE ..."
docker run --rm -v "$WORK":/work -w /work "$IMAGE" bash -c '
    pip install -q --disable-pip-version-check pandas pymupdf pytest &&
    python -m pytest test_docling_checks.py -q
'
