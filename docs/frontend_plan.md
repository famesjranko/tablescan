PDF Table Extractor Frontend Plan                                                                                │
│                                                                                                                  │
│ Context                                                                                                          │
│                                                                                                                  │
│ This 2022 uni project has a working Django REST API for PDF table extraction (YOLO + Camelot) but no frontend -  │
│ only Django Admin. The goal is to add a modern, performant, feature-rich web frontend.                           │
│                                                                                                                  │
│ Current State (after Phase 1 & 2):                                                                               │
│ - Django 3.2 REST API with 3 endpoints: /api/upload/, /api/reports/, /api/extracted/                             │
│ - Extraction engine works (YOLOv3 detection → Camelot parsing → CSV/JSON output)                                 │
│ - Frontend UI complete: upload, reports list, report detail with previews                                        │
│ - Celery + Redis for async extraction with progress tracking                                                     │
│ - Mobile-responsive design with Tailwind CSS                                                                     │
│ - No authentication (Phase 3)                                                     │
│                                                                                                                  │
│ ---                                                                                                              │
│ Decisions                                                                                                        │
│                                                                                                                  │
│ ┌────────────────┬───────────────────────────────────────────────────────┐                                       │
│ │    Decision    │                        Choice                         │                                       │
│ ├────────────────┼───────────────────────────────────────────────────────┤                                       │
│ │ Architecture   │ Django + htmx/Alpine.js (single codebase, minimal JS) │                                       │
│ ├────────────────┼───────────────────────────────────────────────────────┤                                       │
│ │ Authentication │ None for v1 (structure for adding later)              │                                       │
│ ├────────────────┼───────────────────────────────────────────────────────┤                                       │
│ │ Deployment     │ Local dev first, Docker-ready from start              │                                       │
│ └────────────────┴───────────────────────────────────────────────────────┘                                       │
│                                                                                                                  │
│ ---                                                                                                              │
│ Proposed Tech Stack                                                                                              │
│                                                                                                                  │
│ ┌────────────┬────────────────────────────────────────┐                                                          │
│ │   Layer    │               Technology               │                                                          │
│ ├────────────┼────────────────────────────────────────┤                                                          │
│ │ Backend    │ Django 3.2 + DRF (existing)            │                                                          │
│ ├────────────┼────────────────────────────────────────┤                                                          │
│ │ Reactivity │ htmx 2.x (AJAX, partial updates)       │                                                          │
│ ├────────────┼────────────────────────────────────────┤                                                          │
│ │ UI State   │ Alpine.js 3.x (drag-drop, modals)      │                                                          │
│ ├────────────┼────────────────────────────────────────┤                                                          │
│ │ Styling    │ Tailwind CSS 3.x                       │                                                          │
│ ├────────────┼────────────────────────────────────────┤                                                          │
│ │ Task Queue │ Celery + Redis (async extraction)      │                                                          │
│ ├────────────┼────────────────────────────────────────┤                                                          │
│ │ Progress   │ Polling (simpler than SSE, same UX)    │                                                          │
│ └────────────┴────────────────────────────────────────┘                                                          │
│                                                                                                                  │
│ ---                                                                                                              │
│ Implementation Phases                                                                                            │
│                                                                                                                  │
│ Phase 1: Foundation (Fix bugs + basic frontend) [COMPLETE]                                                       │
│                                                                                                                  │
│ [x] 1. Fix import os bug in api/views.py                                                                         │
│ [x] 2. Set up Docker Compose (Django + Redis + Celery worker)                                                    │
│ [x] 3. Create base template with Tailwind CSS                                                                    │
│ [x] 4. Build upload page with basic form                                                                         │
│ [x] 5. Build reports list page                                                                                   │
│ [x] 6. Build report detail page with table downloads                                                             │
│ [x] 7. Add Celery for async extraction with progress tracking                                                    │
│                                                                                                                  │
│ Files created/modified:                                                                                          │
│ [x] api/views.py - add import os, add template views                                                             │
│ [x] api/tasks.py - Celery task wrapping table_extract.extract()                                                  │
│ [x] tablescan/celery.py - Celery configuration                                                                   │
│ [x] templates/base.html - base layout with nav                                                                   │
│ [x] templates/upload.html - upload page                                                                          │
│ [x] templates/reports/list.html - reports list                                                                   │
│ [x] templates/reports/detail.html - report detail                                                                │
│ [x] templates/reports/_table_card.html - table preview component                                                 │
│ [x] Dockerfile - Django app container                                                                            │
│ [x] docker-compose.yml - Django + Redis + Celery                                                                 │
│                                                                                                                  │
│ Phase 2: Enhanced UX [COMPLETE]                                                                                  │
│                                                                                                                  │
│ [x] 1. Drag-and-drop upload (Alpine.js)                                                                          │
│ [x] 2. Page range selector (start/end inputs)                                                                    │
│ [x] 3. Progress tracking (polling - simpler than SSE, same UX)                                                   │
│ [x] 4. Table preview (render CSV as HTML table)                                                                  │
│ [x] 5. Mobile-responsive design (hamburger nav, stacking layouts)                                                                                      │
│                                                                                                                  │
│ Phase 3: Production Ready                                                                                        │
│                                                                                                                  │
│ 1. User authentication                                                                                           │
│ 2. PostgreSQL migration                                                                                          │
│ 3. Rate limiting                                                                                                 │
│ 4. File validation (size limits, PDF verification)                                                               │
│ 5. Error handling improvements                                                                                   │
│                                                                                                                  │
│ Phase 4: Advanced Features (Optional)                                                                            │
│                                                                                                                  │
│ 1. Batch upload (multiple PDFs)                                                                                  │
│ 2. Table editing before download                                                                                 │
│ 3. Export to Excel                                                                                               │
│ 4. API key auth for programmatic access                                                                          │
│                                                                                                                  │
│ ---                                                                                                              │
│ Architecture                                                                                                     │
│                                                                                                                  │
│ Browser                     Django                      Celery Worker                                            │
│    │                           │                              │                                                  │
│    │──── htmx POST ───────────►│                              │                                                  │
│    │                           │── dispatch task ────────────►│                                                  │
│    │◄─── poll progress ────────│◄── progress updates ─────────│                                                  │
│    │                           │                              │                                                  │
│    │                           │         [table_extract.py]   │                                                  │
│    │                           │         [predict_table.py]   │                                                  │
│    │                           │         [detect_func.py]     │                                                  │
│                                                                                                                  │
│ ---                                                                                                              │
│ File Structure (New Files)                                                                                       │
│                                                                                                                  │
│ ├── api/                                                                                                         │
│ │   ├── views.py          # Fixed import + template views                                                        │
│ │   ├── tasks.py          # Celery tasks                                                                         │
│ │   └── urls.py           # Frontend URL patterns                                                            │
│ ├── tablescan/                                                                                                   │
│ │   ├── settings.py       # Celery config, INSTALLED_APPS                                                        │
│ │   └── celery.py         # Celery app                                                                      │
│ ├── templates/                                                                                                   │
│ │   ├── base.html         # Base with nav, Tailwind, htmx, Alpine.js                                             │
│ │   ├── upload.html       # Upload page with drag-drop, progress                                                 │
│ │   └── reports/                                                                                                 │
│ │       ├── list.html     # Reports list with search/pagination                                                  │
│ │       ├── detail.html   # Report detail with tabs                                                              │
│ │       └── _table_card.html # Table preview component                                                           │
│ ├── requirements.txt      # Added: celery, redis, django-htmx                                                    │
│ ├── Dockerfile            # Django app container                                                                 │
│ └── docker-compose.yml    # Django + Redis + Celery worker                                                  │
│                                                                                                                  │
│ ---                                                                                                              │
│ Verification                                                                                                     │
│                                                                                                                  │
│ # Start the stack                                                                                                │
│ docker-compose up --build                                                                                        │
│                                                                                                                  │
│ # Test the flow                                                                                                  │
│ # 1. Open http://localhost:8000 → upload page loads                                                              │
│ # 2. Upload a PDF → extraction runs in background with progress bar                                              │
│ # 3. View reports list → see uploaded report                                                                     │
│ # 4. Click report → preview tables, download CSV/JSON/ZIP                                                        │
│ # 5. Test on mobile viewport → responsive layout works                                                           │
│                                                                                                                  │
│ ---                                                                                                              │
│ Future Considerations (Post-v1)                                                                                  │
│                                                                                                                  │
│ - User authentication (Django built-in auth)                                                                     │
│ - PostgreSQL migration for production                                                                            │
│ - Cloud deployment (Railway, Render, etc.) 
