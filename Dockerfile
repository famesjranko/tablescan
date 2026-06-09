FROM python:3.11-slim

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Set work directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    # Poppler for Camelot PDF parsing
    poppler-utils \
    # Ghostscript for PDF processing
    ghostscript \
    # Tesseract OCR for img2table
    tesseract-ocr \
    tesseract-ocr-eng \
    # OpenCV dependencies (libxcb1 is needed by Docling's cv2 path; declare it
    # explicitly rather than relying on it being pulled in transitively)
    libgl1 \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender-dev \
    libxcb1 \
    # Build tools
    gcc \
    g++ \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies with pip cache.
# Use CPU-only PyTorch to save ~2GB (no CUDA needed for this project). The
# CPU index is also passed to the requirements step via --extra-index-url so
# that if torch/torchvision are re-resolved there (docling depends on torch),
# the +cpu wheels still win instead of pulling the CUDA build from PyPI.
COPY requirements.txt .
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu && \
    pip install -r requirements.txt --extra-index-url https://download.pytorch.org/whl/cpu

# Pre-download Docling model weights at build time so the first extraction
# does not trigger a multi-hundred-MB cold-start download at runtime.
# DOCLING_ARTIFACTS_PATH points DoclingExtractor at these pre-baked weights
# (see api/scripts/extractors/docling_extractor.py). Weights are baked into the
# image layer at /opt/docling-models (no pip cache mount: this step downloads
# from the HF hub, not pip).
ENV DOCLING_ARTIFACTS_PATH=/opt/docling-models
RUN docling-tools models download -o /opt/docling-models

# Copy project files
COPY . .

# Create directories
RUN mkdir -p documents static outputs

# Collect static files
RUN python manage.py collectstatic --noinput || true

# Expose port
EXPOSE 8000

# Default command (can be overridden in docker-compose)
CMD ["python", "manage.py", "runserver", "0.0.0.0:8000"]
