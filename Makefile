.PHONY: help install test test-unit test-quick test-django test-smoke test-all redis-up redis-down redis-flush celery celery-stop services-up services-down clean dev docker-build docker-dev docker-down docker-clean docker-nuke server server-stop migrate

# Default target
help:
	@echo "TableScan 2.0 Development Commands"
	@echo ""
	@echo "Testing:"
	@echo "  make test          - Run all 252 tests with pytest (starts Redis + Celery)"
	@echo "  make test-unit     - Run unit tests only (no services needed)"
	@echo "  make test-quick    - Fast test run, stops on first failure"
	@echo "  make test-django   - Run tests via Django's manage.py test (12 tests)"
	@echo "  make test-smoke    - Run smoke tests against running server (make dev first)"
	@echo ""
	@echo "Services:"
	@echo "  make services-up   - Start Redis + Celery for testing"
	@echo "  make services-down - Stop Redis + Celery"
	@echo "  make redis-up      - Start Redis container only"
	@echo "  make redis-down    - Stop Redis container"
	@echo "  make celery        - Start Celery worker (background)"
	@echo "  make celery-stop   - Stop Celery worker"
	@echo ""
	@echo "Development:"
	@echo "  make install       - Install Python dependencies"
	@echo "  make dev           - Start dev locally (Django + Redis + Celery)"
	@echo "  make docker-build  - Build Docker images"
	@echo "  make docker-dev    - Build and start Docker containers"
	@echo "  make docker-down   - Stop Docker containers"
	@echo "  make docker-clean  - Clean unused Docker resources (safe)"
	@echo "  make docker-nuke   - Remove ALL Docker data (full rebuild needed)"
	@echo "  make server        - Start Django in background (for smoke tests)"
	@echo "  make server-stop   - Stop background Django server"
	@echo "  make migrate       - Run database migrations"
	@echo "  make clean         - Stop all services and clean temp files"
	@echo ""
	@echo "Full Pipeline Test:"
	@echo "  make test-all      - Run unit tests + smoke tests (full validation)"

# Install dependencies
install:
	pip install -r requirements.txt

# Database migrations
migrate:
	python manage.py makemigrations
	python manage.py migrate

# Redis via Docker
redis-up:
	@docker compose up -d redis
	@echo "Waiting for Redis to be ready..."
	@sleep 2
	@docker exec $$(docker compose ps -q redis) redis-cli ping || (echo "Redis failed to start" && exit 1)
	@echo "Redis is ready on localhost:6379"

redis-flush:
	@echo "Flushing Redis (clearing stale tasks)..."
	@docker exec $$(docker compose ps -q redis) redis-cli flushall > /dev/null
	@echo "Redis flushed"

redis-down:
	@docker compose stop redis

# Celery worker
CELERY_PID_FILE := /tmp/tablescan-celery.pid
CELERY_LOG_FILE := /tmp/tablescan-celery.log

celery: redis-up
	@if [ -f $(CELERY_PID_FILE) ] && kill -0 $$(cat $(CELERY_PID_FILE)) 2>/dev/null; then \
		echo "Celery already running (PID: $$(cat $(CELERY_PID_FILE)))"; \
	else \
		echo "Starting Celery worker..."; \
		celery -A tablescan worker --loglevel=info --pool=solo > $(CELERY_LOG_FILE) 2>&1 & \
		echo $$! > $(CELERY_PID_FILE); \
		sleep 3; \
		if kill -0 $$(cat $(CELERY_PID_FILE)) 2>/dev/null; then \
			echo "Celery started (PID: $$(cat $(CELERY_PID_FILE)))"; \
		else \
			echo "Celery failed to start. Check $(CELERY_LOG_FILE)"; \
			exit 1; \
		fi \
	fi

celery-stop:
	@if [ -f $(CELERY_PID_FILE) ]; then \
		kill $$(cat $(CELERY_PID_FILE)) 2>/dev/null || true; \
		rm -f $(CELERY_PID_FILE); \
		echo "Celery stopped"; \
	else \
		pkill -f "celery.*tablescan" 2>/dev/null || true; \
		echo "Celery stopped"; \
	fi

celery-logs:
	@tail -f $(CELERY_LOG_FILE)

# Combined service management
services-up: redis-up redis-flush celery
	@echo "All services ready"

services-down: celery-stop redis-down
	@echo "All services stopped"

# Testing
test: services-up
	@echo "Running all tests..."
	pytest api/tests/ -v --tb=short
	@echo ""
	@echo "Tests complete. Run 'make services-down' to stop services."

test-unit:
	@echo "Running unit tests (no services required)..."
	pytest api/tests/ -v --tb=short -k "not E2E and not Integration" --ignore=api/tests/test_phase1_e2e.py --ignore=api/tests/test_phase2_e2e.py

test-quick: services-up
	@echo "Running tests (fail fast)..."
	pytest api/tests/ -x -q

test-django: services-up
	@echo "Running Django tests (APITestCase-based only)..."
	python manage.py test api.tests -v 2

test-smoke:
	@echo "Running smoke tests against server..."
	@curl -s http://localhost:8000/api/ > /dev/null 2>&1 || (echo "Server not running. Start with: make dev" && exit 1)
	python scripts/smoke_test.py

# Background server for smoke tests
SERVER_PID_FILE := /tmp/tablescan-server.pid
SERVER_LOG_FILE := /tmp/tablescan-server.log

server: services-up migrate
	@if [ -f $(SERVER_PID_FILE) ] && kill -0 $$(cat $(SERVER_PID_FILE)) 2>/dev/null; then \
		echo "Server already running (PID: $$(cat $(SERVER_PID_FILE)))"; \
	else \
		echo "Starting Django server..."; \
		python manage.py runserver 0.0.0.0:8000 > $(SERVER_LOG_FILE) 2>&1 & \
		echo $$! > $(SERVER_PID_FILE); \
		sleep 3; \
		if curl -s http://localhost:8000/api/ > /dev/null 2>&1; then \
			echo "Server started (PID: $$(cat $(SERVER_PID_FILE)))"; \
		else \
			echo "Server failed to start. Check $(SERVER_LOG_FILE)"; \
			exit 1; \
		fi \
	fi

server-stop:
	@if [ -f $(SERVER_PID_FILE) ]; then \
		kill $$(cat $(SERVER_PID_FILE)) 2>/dev/null || true; \
		rm -f $(SERVER_PID_FILE); \
		echo "Server stopped"; \
	fi

# Full pipeline test (unit + smoke)
test-all: server
	@echo ""
	@echo "=========================================="
	@echo "Running unit tests..."
	@echo "=========================================="
	pytest api/tests/ -v --tb=short
	@echo ""
	@echo "=========================================="
	@echo "Running smoke tests..."
	@echo "=========================================="
	python scripts/smoke_test.py
	@echo ""
	@echo "All tests complete!"

# Development server (foreground, local Python)
dev: services-up migrate
	@echo "Starting Celery worker in background..."
	@make celery
	@echo "Starting Django server..."
	python manage.py runserver 0.0.0.0:8000

# Docker-based development (includes torch for full pipeline)
docker-build:
	@echo "Building Docker images..."
	@echo "Flushing Redis to clear stale tasks..."
	@docker compose up -d redis 2>/dev/null || true
	@docker exec $$(docker compose ps -q redis 2>/dev/null) redis-cli flushall 2>/dev/null || true
	@docker compose stop redis 2>/dev/null || true
	docker compose build

docker-dev:
	@echo "Starting Docker containers..."
	docker compose up

docker-down:
	@echo "Stopping Docker containers..."
	docker compose down

# Clean Docker cache (safe - only unused images/containers)
docker-clean:
	@echo "Cleaning unused Docker resources..."
	docker system prune -f
	docker builder prune -f
	@echo "Freed disk space. Run 'docker system df' to see usage."

# Nuclear option - removes EVERYTHING (will require full rebuild)
docker-nuke:
	@echo "WARNING: This removes ALL Docker images, containers, volumes, and build cache"
	@read -p "Are you sure? [y/N] " confirm && [ "$$confirm" = "y" ]
	docker compose down -v --rmi all
	docker system prune -af --volumes
	docker builder prune -af
	@echo "Docker wiped clean."

# Cleanup
clean: server-stop services-down
	@rm -f $(CELERY_LOG_FILE) $(CELERY_PID_FILE) $(SERVER_LOG_FILE) $(SERVER_PID_FILE)
	@find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	@find . -type f -name "*.pyc" -delete 2>/dev/null || true
	@echo "Cleaned up"
