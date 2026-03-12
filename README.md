# TableScan

Automated PDF table extraction with AI-powered detection. Upload PDFs, review detected tables, and export to CSV/JSON.

## Features

- **AI Table Detection** - YOLOv3 locates tables in PDF documents
- **Book Viewer** - Interactive PDF viewer with page navigation and zoom
- **Review Workflow** - Approve/reject detections before extraction
- **Manual Selection** - Draw table regions directly on the PDF
- **Multiple Modes** - Auto, Auto+Review, or Manual extraction
- **Async Processing** - Celery handles extraction in the background
- **Multiple Exports** - CSV, JSON, or ZIP archive

## Quick Start

```bash
git clone https://github.com/famesjranko/automated-PDF-tabulated-data-extractor-api.git
cd automated-PDF-tabulated-data-extractor-api

# Start with Docker (recommended)
make docker-build
make docker-dev

# Open http://localhost:8000
```

## Development

All development commands are available via `make help`:

```bash
make docker-dev      # Build and run with Docker
make dev             # Run locally (Django + Redis + Celery)
make test            # Run all tests
make test-unit       # Run unit tests only (no services)
make clean           # Stop services and clean temp files
```

Requires Docker, or Python 3.11+ with Redis and Poppler (`apt install poppler-utils`).

## Architecture

```
Browser ──► Django ──► Celery Worker
              │              │
              │         [YOLOv3 Detection]
              │         [Camelot Parsing]
              │              │
         PostgreSQL    Redis (broker)
```

**Stack**: Django 4.2 / htmx / Tailwind CSS / Celery / Redis / PostgreSQL / YOLOv3 / Camelot

## Usage

### Extraction Modes

| Mode | Description |
|------|-------------|
| **Auto** | YOLO detects tables, extraction runs immediately |
| **Auto + Review** | YOLO detects tables, approve/reject before extraction |
| **Manual** | Draw table regions yourself |

### Workflow

1. **Upload** - Select PDF and extraction mode
2. **Review** - Open Book Viewer, approve/reject/draw selections
3. **Extract** - Process approved regions
4. **Download** - Get CSV/JSON or ZIP archive

## API

| Endpoint | Description |
|----------|-------------|
| `POST /api/upload/` | Upload PDF |
| `GET /api/reports/` | List reports |
| `GET /api/reports/{id}/` | Get report with tables |
| `POST /api/reports/{id}/detect-tables/` | Trigger YOLO detection |
| `POST /api/reports/{id}/extract-selections/` | Extract approved selections |
| `GET/POST /api/reports/{id}/selections/` | List/create selections |
| `PATCH /api/reports/{id}/selections/{sel_id}/` | Update selection status |

## Project Structure

```
├── api/
│   ├── views.py       # API + template views
│   ├── tasks.py       # Celery extraction tasks
│   ├── models.py      # Report, Extracted, TableSelection
│   └── scripts/       # YOLO + Camelot extraction engine
├── templates/         # htmx/Tailwind frontend
├── tablescan/         # Django settings + Celery config
├── Makefile           # Development commands
├── Dockerfile
└── docker-compose.yml
```
