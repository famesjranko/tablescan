# Phase 3: Production Ready - Implementation Plan

## Status: COMPLETED (2026-03-10)

All sub-phases implemented and tested. See "Implementation Notes" section below for details.

---

## Context

Phases 1 (Foundation) and 2 (Enhanced UX) are **confirmed complete**. The frontend has:
- Celery + Redis async extraction with progress polling
- Drag-and-drop upload with page range selection
- Table previews rendered as HTML
- Mobile-responsive Tailwind design

Phase 3 as originally written bundles major architectural changes:
1. User authentication
2. PostgreSQL migration
3. Rate limiting
4. File validation
5. Error handling

**Problem:** These are not independent tasks. Authentication requires user ownership on models, which affects database schema. This needs careful sequencing.

---

## Sub-Phase Breakdown

### Phase 3A: Database & Model Foundation ✅
**Goal:** Add user ownership to models while still on SQLite (simpler debugging)

1. Add `owner` ForeignKey to `Report` model (nullable initially for migration)
2. Add `created_at`, `updated_at` timestamps
3. Create data migration assigning existing reports to superuser
4. Make `owner` non-nullable
5. Update `Extracted` to inherit ownership from parent Report (no separate FK needed)

**Files:** `api/models.py`, `api/migrations/0002-0004`

---

### Phase 3B: Authentication System ✅
**Goal:** JWT-based auth with login/register

1. Add `djangorestframework-simplejwt` to requirements
2. Add JWT endpoints: `/api/auth/register/`, `/api/auth/login/`, `/api/auth/refresh/`
3. Add user registration serializer
4. Configure `REST_FRAMEWORK` default authentication classes
5. Create login/register frontend pages
6. Store token in localStorage, include in API requests

**Files:** `requirements.txt`, `tablescan/settings.py`, `api/serializers_auth.py`, `api/views_auth.py`, `api/urls.py`, `templates/auth/`

---

### Phase 3C: Permission Enforcement ✅
**Goal:** Lock down all endpoints to authenticated users

1. Add `IsAuthenticated` permission to all viewsets
2. Filter querysets by `request.user` (users see only their reports)
3. Add `LoginRequiredMixin` to frontend template views
4. Create custom `IsReportOwner` permission for detail views
5. Update upload flow to set `report.owner = request.user`

**Files:** `api/views.py`, `api/permissions.py`

---

### Phase 3D: PostgreSQL Migration ✅
**Goal:** Production-ready database

1. Add `psycopg2-binary` to requirements
2. Add environment variable configuration (`python-decouple`)
3. Update `settings.py` DATABASES with env var fallback
4. Update `docker-compose.yml` with PostgreSQL service
5. Create `.env.example` with database config template

**Files:** `requirements.txt`, `tablescan/settings.py`, `docker-compose.yml`, `.env.example`

---

### Phase 3E: Rate Limiting & File Validation ✅
**Goal:** Protect system from abuse

1. Add DRF built-in throttling
2. Create throttle classes: `100/hour` API, `10/hour` uploads
3. Add file size limit (50MB) in upload view
4. Add PDF magic number validation (`%PDF-` header check)
5. Return user-friendly error messages

**Files:** `api/throttles.py`, `api/views.py`, `tablescan/settings.py`

---

## Architectural Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Authentication | **JWT** (`simplejwt`) | Stateless, API-friendly, supports refresh tokens |
| User Model | **Built-in User** | Simpler for v1, can extend later |
| Storage Quotas | **Skip for now** | Rate limiting sufficient, add in Phase 4 if needed |
| PostgreSQL timing | **After auth (3D)** | Develop auth on SQLite for simpler debugging |

---

## Implementation Notes (For Future Developers)

### Dual Authentication: JWT + Session

The frontend uses Django's `LoginRequiredMixin` for template views, which requires session auth. But the API uses JWT. To solve this, **both login and register endpoints create a Django session alongside the JWT tokens**.

See `api/views_auth.py`:
- `LoginView` - authenticates, creates session via `login(request, user)`, returns JWT
- `RegisterView` - creates user, creates session, returns JWT

This means:
- Frontend template views use session cookies (automatic via middleware)
- API calls can use JWT Bearer tokens in Authorization header
- Both work simultaneously

### Database Configuration

Uses `python-decouple` for env vars with SQLite fallback:

```python
# settings.py
DATABASES = {
    'default': {
        'ENGINE': config('DB_ENGINE', default='django.db.backends.sqlite3'),
        'NAME': config('DB_NAME', default=str(BASE_DIR / 'db.sqlite3')),
        ...
    }
}
```

- **Local dev (no .env):** Uses SQLite automatically
- **Docker:** Uses PostgreSQL via environment variables in docker-compose.yml
- **Production:** Set env vars or create `.env` file from `.env.example`

### Orphan File Handling

The `table_extract.py` script had an issue where it assumed files on disk always had matching database records. Fixed by wrapping the lookup in try/except:

```python
try:
    original_report_db = Report.objects.get(document__endswith=original_file_name)
    # ... handle duplicate
except Report.DoesNotExist:
    # File exists on disk but no DB record - delete orphan
    Path(original_file_path).unlink(missing_ok=True)
```

This can happen when:
- Database is reset but `documents_data` volume persists
- Switching between SQLite and PostgreSQL

### Rate Limits

| Scope | Rate | Applied To |
|-------|------|------------|
| `anon` | 20/hour | Unauthenticated requests |
| `user` | 100/hour | Authenticated requests |
| `upload` | 10/hour | PDF uploads |
| `burst` | 5/minute | Rapid-fire protection |

### File Validation

Before processing uploads:
1. **Size check:** Max 50MB (`MAX_UPLOAD_SIZE` in settings)
2. **Magic number:** First 5 bytes must be `%PDF-`

See `validate_pdf_file()` in `api/views.py`.

### Docker Startup

The web service runs migrations automatically on startup:
```yaml
command: sh -c "python manage.py migrate && python manage.py runserver 0.0.0.0:8000"
```

---

## Verification Checklist

- [x] **3A:** Migrations run, `owner`/`created_at`/`updated_at` columns exist
- [x] **3B:** Register → get JWT, login → get JWT + session cookie
- [x] **3C:** `/api/reports/` without auth → 401; with auth → only user's reports
- [x] **3D:** `docker-compose up` connects to PostgreSQL, migrations apply
- [x] **3E:** Upload validates PDF header; throttle limits enforced

---

## Files Changed

### New Files
- `api/permissions.py` - IsReportOwner permission
- `api/throttles.py` - UploadRateThrottle, BurstRateThrottle
- `api/serializers_auth.py` - UserRegistrationSerializer
- `api/views_auth.py` - RegisterView, LoginView, LogoutView
- `api/migrations/0001_initial_squashed.py` - Base migration
- `api/migrations/0002_add_owner_and_timestamps.py`
- `api/migrations/0003_assign_owner_to_reports.py`
- `api/migrations/0004_make_owner_required.py`
- `templates/auth/login.html`
- `templates/auth/register.html`
- `.env.example`

### Modified Files
- `api/models.py` - Added owner FK, timestamps
- `api/views.py` - Permissions, throttles, file validation, LoginRequiredMixin
- `api/serializers.py` - Added owner field
- `api/urls.py` - Auth endpoints
- `api/scripts/table_extract.py` - Orphan file handling
- `tablescan/settings.py` - JWT, throttling, PostgreSQL, decouple
- `tablescan/urls.py` - Auth frontend routes
- `docker-compose.yml` - PostgreSQL service, auto-migrate
- `requirements.txt` - simplejwt, psycopg2, decouple
- `templates/base.html` - User info + logout link in navbar
