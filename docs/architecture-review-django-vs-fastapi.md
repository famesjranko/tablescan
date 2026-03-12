# Architecture Review: Django vs FastAPI Migration

**Date:** 2026-03-12
**Status:** Assessment Complete
**Recommendation:** Stay with Django

---

## Executive Summary

This review evaluates whether migrating from Django to FastAPI would benefit the PDF table extraction API, and whether adopting a stateless architecture is warranted.

**Key Findings:**
- Migration cost: 2-3 weeks for ~70% code rewrite
- Performance gain: Negligible (bottleneck is CPU-bound extraction, not the web framework)
- FastAPI's async advantage is irrelevant — Celery + multiprocessing already handle concurrency correctly
- Going stateless is partially achievable with minimal effort (cloud storage migration)

**Verdict:** Keep Django. Focus optimization efforts on GPU acceleration for YOLO inference instead.

---

## 1. Current Architecture Overview

### Tech Stack
| Layer | Technology |
|-------|------------|
| Web Framework | Django 3.2 + Django REST Framework |
| Database | SQLite/PostgreSQL via Django ORM |
| Task Queue | Celery + Redis |
| ML Inference | PyTorch (YOLOv3-tiny) |
| PDF Processing | Camelot, pdf2image, PyPDF2 |
| Authentication | JWT (simplejwt) |
| Frontend | Django templates + HTMX |

### Request Flow
```
Client → Django API → Celery Task → Multiprocessing Pool
                                         ↓
                              PDF → Image → YOLO → Camelot → CSV/JSON
```

### Key Components
- **3 Django Models:** Report, Extracted, TableSelection
- **21 API Endpoints:** 9 REST, 7 frontend views, 4 auth
- **3 Celery Tasks:** extract_tables_task, detect_tables_for_review, extract_from_selections
- **Admin Interface:** Django admin for operations

---

## 2. Django Feature Usage Analysis

### Heavily Used (High Migration Cost)

| Feature | Usage | Migration Impact |
|---------|-------|------------------|
| ORM | 3 models with ForeignKey relationships | Rewrite with SQLAlchemy + Alembic |
| ViewSets | Full CRUD with custom @action decorators | Manual FastAPI route definitions |
| Serializers | Validation logic, nested serialization | Convert to Pydantic models |
| Authentication | Django User + simplejwt | Implement with python-jose + PassLib |
| Admin Interface | Model management, operations | No equivalent — lose or rebuild |
| Templates | 7 frontend views with Django templates | Migrate to Jinja2 or SPA |
| File Storage | Custom FileSystemStorage class | Rewrite as utility functions |

### Lightly Used (Low Migration Cost)

| Feature | Usage | Migration Impact |
|---------|-------|------------------|
| Permissions | IsAuthenticated, IsReportOwner | FastAPI dependency injection |
| Rate Limiting | UserRateThrottle | slowapi library |
| CORS | corsheaders middleware | FastAPI CORSMiddleware |
| Filtering | DjangoFilterBackend | Manual query params |

### Not Used
- Custom middleware
- Django signals (except django_cleanup)
- Caching
- Custom user model
- Complex permissions

---

## 3. Performance Analysis

### Where Time Is Actually Spent

| Operation | Time per Page | Bound | Framework Impact |
|-----------|---------------|-------|------------------|
| PDF → Image | 0.5-2s | CPU | None |
| YOLO Inference | 1-3s | CPU | None |
| Camelot Extraction | 0.2-1s | CPU | None |
| Database Queries | 5-20ms | I/O | Minimal |
| API Response | 10-50ms | I/O | FastAPI ~10% faster |

**The bottleneck is CPU-bound PDF processing, not the web framework.**

### Async Opportunity Assessment

| Operation | Current | FastAPI Async Gain |
|-----------|---------|-------------------|
| File upload | Blocking I/O | Negligible (SSD bottleneck) |
| Database queries | Django ORM | 5-10% with async SQLAlchemy |
| Celery dispatch | Already async | None |
| PDF processing | Multiprocessing | None (CPU-bound) |

**Verdict:** FastAPI's async capabilities would not provide meaningful speedup for this workload.

---

## 4. Migration Cost Estimate

### By Component

| Component | Lines of Code | Days | Reusable |
|-----------|---------------|------|----------|
| Models/ORM | 291 | 2-3 | 70% |
| Views/Routes | 736 | 3-4 | 60% |
| Serializers | 154 | 1 | 80% |
| Celery Tasks | 480 | 0 | 100% |
| Admin | 27 | 1 | 0% |
| Templates | ~2000 | 2-3 | 90% |
| Extraction Logic | 944 | 0 | 100% |
| **Total** | **~4600** | **10-15** | **~70%** |

### Migration Phases

**Phase 1: Foundation (3-4 days)**
- Set up SQLAlchemy + Alembic
- Rewrite ORM models
- Create Pydantic schemas
- Implement JWT authentication

**Phase 2: API Endpoints (3-4 days)**
- Convert ViewSets to FastAPI routes
- Implement file upload handling
- Integrate Celery task dispatch

**Phase 3: Frontend (2-3 days)**
- Migrate templates to Jinja2 OR
- Build separate SPA (adds 5-7 days)

**Phase 4: Testing (2-3 days)**
- Database migration verification
- Celery task execution
- File handling edge cases

**Total: 2-3 weeks** for a developer with FastAPI experience.

---

## 5. Stateless Architecture Assessment

### Current State Management

| State Type | Current Approach | Stateless? |
|------------|------------------|------------|
| Database | PostgreSQL/SQLite | N/A (external) |
| File Storage | Local filesystem | **No** |
| Task Queue | Redis via Celery | Yes |
| Sessions | JWT tokens | Yes |
| Worker State | Celery workers | Yes (ephemeral) |

### Path to Stateless

The application is **already 80% stateless**. The only blocker is local file storage.

**Required Changes:**
1. Replace `FileSystemStorage` with `django-storages` + S3/GCS
2. Update file path references in extraction pipeline
3. Ensure workers can access cloud storage

**Effort:** ~1 day

**Benefits:**
- Horizontal scaling (multiple Django instances)
- Kubernetes-ready deployment
- Disaster recovery (files in durable storage)

---

## 6. Risk Assessment

### Migration Risks

| Risk | Severity | Mitigation |
|------|----------|------------|
| Data loss during ORM migration | High | Full backup, test with prod dump |
| File path handling breaks | Medium | Test with existing documents/ structure |
| Celery task coupling | Medium | Abstract model access, use IDs |
| Admin interface loss | Medium | Document operations, build minimal tooling |
| Template rendering breaks | Low | Jinja2 is nearly identical to Django templates |

### Staying with Django Risks

| Risk | Severity | Mitigation |
|------|----------|------------|
| Framework becomes unmaintained | Very Low | Django has strong LTS support |
| Performance ceiling | Low | Bottleneck is extraction, not framework |
| Hiring difficulty | Low | Django developers are common |

---

## 7. Recommendations

### Primary Recommendation: Stay with Django

**Rationale:**
- Migration provides negligible performance benefit
- 2-3 weeks of work with no user-facing improvement
- Loss of admin interface increases operational burden
- Django is well-suited for this workload

### If You Want Performance Gains

**Enable GPU acceleration for YOLO inference:**
```python
# In api/scripts/YOLOV3/utils/detect_func.py
parameters['device'] = 'cuda:0'  # Instead of 'cpu'
```
- Expected speedup: 10-50x on detection phase
- Effort: 1 hour (plus GPU provisioning)

### If You Need Horizontal Scaling

**Migrate to cloud storage:**
```python
# settings.py
DEFAULT_FILE_STORAGE = 'storages.backends.s3boto3.S3Boto3Storage'
AWS_STORAGE_BUCKET_NAME = 'your-bucket'
```
- Enables multiple Django instances
- Effort: ~1 day

### If You're Starting Fresh

FastAPI would be a reasonable choice for a **new** service with:
- Pure REST API (no admin, no templates)
- WebSocket requirements
- Microservices architecture
- Team already fluent in FastAPI

---

## 8. When to Reconsider

Revisit this decision if:
- Django REST Framework introduces breaking changes
- You need WebSocket streaming of extraction progress
- You're rebuilding the frontend as a separate SPA anyway
- Team composition shifts to FastAPI expertise

---

## Appendix A: Code Comparison

### Django (Current)
```python
class ReportViewSet(viewsets.ModelViewSet):
    queryset = Report.objects.all()
    serializer_class = ReportSerializer
    permission_classes = [IsAuthenticated, IsReportOwner]
    filter_backends = [DjangoFilterBackend]

    @action(detail=True, methods=['post'])
    def extract_selections(self, request, pk=None):
        report = self.get_object()
        approved = report.selections.filter(status='approved').count()
        if approved == 0:
            return Response({'error': 'No approved selections'}, status=400)
        task = extract_from_selections.delay(report.id)
        return Response({'task_id': task.id})
```

### FastAPI (Equivalent)
```python
@app.post("/api/reports/{report_id}/extract-selections/")
async def extract_selections(
    report_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user)
):
    report = db.query(Report).filter(
        Report.id == report_id,
        Report.owner_id == user.id
    ).first()
    if not report:
        raise HTTPException(status_code=404)

    approved = db.query(TableSelection).filter(
        TableSelection.report_id == report_id,
        TableSelection.status == 'approved'
    ).count()

    if approved == 0:
        raise HTTPException(status_code=400, detail="No approved selections")

    task = extract_from_selections.delay(report_id)
    return {"task_id": task.id}
```

**Observation:** The FastAPI version is more explicit but not meaningfully better for this use case.

---

## Appendix B: Framework Comparison

| Aspect | Django | FastAPI |
|--------|--------|---------|
| Maturity | 19 years | 6 years |
| Admin Interface | Built-in | None |
| ORM | Django ORM | SQLAlchemy (separate) |
| Async Support | Django 4.1+ | Native |
| API Documentation | DRF + drf-spectacular | OpenAPI built-in |
| Learning Curve | Moderate | Low |
| Memory Footprint | Higher | Lower |
| Startup Time | Slower | Faster |
| Ecosystem | Larger | Growing |
| LTS Support | Strong | Community-driven |

---

## Document History

| Date | Author | Changes |
|------|--------|---------|
| 2026-03-12 | Claude | Initial assessment |
