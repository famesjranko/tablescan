# TableScan

Automated PDF table extraction with a modern web interface. Upload PDFs, extract tables using AI-powered detection, and download results as CSV/JSON.

## Features

- **AI Table Detection** - YOLOv3 locates tables in PDF documents
- **Accurate Parsing** - Camelot extracts table data with high fidelity
- **Book Viewer** - Interactive PDF viewer with page-by-page navigation
- **Manual Selection** - Draw table regions directly on the PDF
- **Review Workflow** - Approve/reject AI detections before extraction
- **Multiple Extraction Modes** - Auto, Auto+Review, or Manual
- **Web Interface** - Clean, responsive UI built with htmx + Tailwind CSS
- **Async Processing** - Celery handles extraction in the background
- **Multiple Exports** - Download as CSV, JSON, or ZIP archive

## Quick Start

```bash
# Clone and start
git clone https://github.com/your-repo/tablescan.git
cd tablescan
docker-compose up --build

# Open http://localhost:8000
```

## Architecture

```
Browser ──► Django ──► Celery Worker
              │              │
              │         [YOLOv3 Detection]
              │         [Camelot Parsing]
              │              │
              └──── Redis ◄──┘
```

**Stack**: Django 3.2 / htmx / Tailwind CSS / Celery / Redis / YOLOv3 / Camelot

## Usage

### Extraction Modes

1. **Auto** - Upload PDF, YOLO detects tables, extraction runs immediately
2. **Auto + Review** - YOLO detects tables, you approve/reject before extraction
3. **Manual** - Draw table regions yourself, full control over extraction

### Workflow

1. **Upload** - Drag & drop or select a PDF, choose extraction mode
2. **Review** (if Auto+Review or Manual) - Open Book Viewer, approve/reject detections or draw manual selections
3. **Extract** - Run extraction on approved regions
4. **Download** - Get individual tables (CSV/JSON) or everything as ZIP

## API Endpoints

### Reports

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/upload/` | POST | Upload PDF and trigger extraction |
| `/api/reports/` | GET | List all reports |
| `/api/reports/{id}/` | GET | Get report with extracted tables |
| `/api/reports/{id}/` | DELETE | Delete a report |

### Table Selections

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/reports/{id}/selections/` | GET | List table selections for a report |
| `/api/reports/{id}/selections/` | POST | Create a manual table selection |
| `/api/reports/{id}/selections/{sel_id}/` | PATCH | Update selection (approve/reject) |
| `/api/reports/{id}/selections/{sel_id}/` | DELETE | Delete a selection |

### Extraction Tasks

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/reports/{id}/detect-tables/` | POST | Trigger YOLO detection (creates pending selections) |
| `/api/reports/{id}/extract-selections/` | POST | Extract tables from approved selections |

### TableSelection Model

```json
{
  "id": 1,
  "report": 5,
  "page_num": 1,
  "x1": 10.5,
  "y1": 20.0,
  "x2": 90.5,
  "y2": 80.0,
  "source": "yolo",      // "yolo" or "manual"
  "status": "pending",   // "pending", "approved", "rejected", "failed"
  "confidence": 0.85
}
```

## Development

```bash
# Run without Docker
pip install -r requirements.txt
python manage.py migrate
python manage.py runserver

# Start Celery worker (separate terminal)
celery -A tablescan worker --loglevel=info
```

Requires: Python 3.9+, Redis, Poppler (`apt install poppler-utils`)

## Project Structure

```
├── api/
│   ├── views.py          # API + template views
│   ├── tasks.py          # Celery extraction tasks
│   ├── models.py         # Report, Extracted, TableSelection models
│   └── scripts/          # YOLO + Camelot extraction engine
├── templates/            # htmx/Tailwind frontend
├── tablescan/            # Django settings + Celery config
├── Dockerfile
└── docker-compose.yml    # Django + Redis + Celery
```
