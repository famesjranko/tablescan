# TableScan

Automated PDF table extraction with a modern web interface. Upload PDFs, extract tables using AI-powered detection, and download results as CSV/JSON.

## Features

- **AI Table Detection** - YOLOv3 locates tables in PDF documents
- **Accurate Parsing** - Camelot extracts table data with high fidelity
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

1. **Upload** - Drag & drop or select a PDF
2. **Process** - Extraction runs asynchronously with progress updates
3. **Download** - Get individual tables (CSV/JSON) or everything as ZIP

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/upload/` | POST | Upload PDF and trigger extraction |
| `/api/reports/` | GET | List all reports |
| `/api/reports/{id}/` | GET | Get report with extracted tables |

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
│   ├── tasks.py          # Celery extraction task
│   └── scripts/          # YOLO + Camelot extraction engine
├── templates/            # htmx/Tailwind frontend
├── tablescan/            # Django settings + Celery config
├── Dockerfile
└── docker-compose.yml    # Django + Redis + Celery
```

