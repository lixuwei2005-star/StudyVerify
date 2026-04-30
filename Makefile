# StudyVerify development Makefile
# Wraps `docker compose --env-file .env.docker` so devs don't have to remember
# the flag, and centralizes smoke-test invocation.

SHELL := /usr/bin/env bash

.DEFAULT_GOAL := help

# Compose command with env-file pre-set
COMPOSE := docker compose --env-file .env.docker

# Optional service filter for `make compose-logs` (e.g. `make compose-logs SERVICE=api`).
# Empty default = follow all services.
SERVICE ?=

.PHONY: help compose-up compose-up-infra compose-up-rebuild \
        compose-down compose-down-volumes \
        compose-logs compose-ps compose-config \
        smoke-db smoke-redis smoke-all smoke-stack \
        docker-build docker-build-fresh docker-run-smoke docker-image-size \
        regression-all

help:
	@echo "StudyVerify development commands:"
	@echo ""
	@echo "  make compose-up                - Start full stack (postgres + redis + api)"
	@echo "                                   all 3 services report (healthy)"
	@echo "  make compose-up-infra          - Start infrastructure only for local uvicorn"
	@echo "  make compose-up-rebuild        - Rebuild api image, then start stack"
	@echo "  make compose-down              - Stop containers (data preserved)"
	@echo "  make compose-down-volumes      - Stop AND delete volumes (DESTRUCTIVE)"
	@echo "  make compose-logs              - Tail logs from all services"
	@echo "  make compose-logs SERVICE=api  - Tail logs from one service"
	@echo "  make compose-ps                - List running containers"
	@echo "  make compose-config            - Show resolved compose config"
	@echo "  make smoke-db                  - Run Postgres smoke test"
	@echo "  make smoke-redis               - Run Redis smoke test"
	@echo "  make smoke-all                 - Run both smoke tests"
	@echo "  make smoke-stack               - Full /solve -> /verify smoke (compose stack must be up)"
	@echo ""
	@echo "  make docker-build              - Build studyverify-api image (arm64)"
	@echo "  make docker-build-fresh        - Build with --no-cache"
	@echo "  make docker-run-smoke          - Smoke test: import app.main in image"
	@echo "  make docker-image-size         - Show built image size"
	@echo ""
	@echo "  make regression-all            - Full pytest sweep (requires compose-up-infra)"

compose-up:
	$(COMPOSE) up -d

compose-up-infra:
	@echo "Starting infrastructure only (postgres + redis)..."
	@echo "Use this when running uvicorn locally (cd backend && uv run uvicorn ...)"
	$(COMPOSE) up -d postgres redis

compose-up-rebuild: docker-build
	@echo "Rebuilt image; bringing up full stack..."
	$(COMPOSE) up -d
	@echo ""
	@echo "Stack is starting. Wait ~20-30s, then check:"
	@echo "  make compose-ps      # all 3 services should report (healthy)"
	@echo "  curl localhost:8000/health/db"

compose-down:
	$(COMPOSE) down

# Interactive confirmation gate. NOT safe for CI / non-interactive shells —
# the `read` will hang or fail. CI should call `$(COMPOSE) down -v` directly.
compose-down-volumes:
	@echo "⚠️  This will DELETE all data in Postgres and Redis."
	@read -p "Type 'yes' to continue: " confirm && [ "$$confirm" = "yes" ]
	$(COMPOSE) down -v

compose-logs:
	$(COMPOSE) logs -f $(SERVICE)

compose-ps:
	$(COMPOSE) ps

compose-config:
	$(COMPOSE) config

smoke-db:
	@set -a && source .env.docker && set +a && bash scripts/db-smoke-test.sh

smoke-redis:
	@set -a && source .env.docker && set +a && bash scripts/redis-smoke-test.sh

smoke-all: smoke-db smoke-redis

smoke-stack:
	@echo "Running full-stack smoke (requires 'make compose-up' first)..."
	@bash scripts/smoke-stack.sh

# ═══ Docker image management (Step 3.4.a) ═══

DOCKER_IMAGE := studyverify-api
DOCKER_TAG := dev

docker-build:
	@echo "Building $(DOCKER_IMAGE):$(DOCKER_TAG) for native arm64..."
	docker build \
		--platform=linux/arm64 \
		--provenance=false \
		--sbom=false \
		-t $(DOCKER_IMAGE):$(DOCKER_TAG) \
		.

docker-build-fresh:
	@echo "Building from scratch (no cache)..."
	docker build \
		--platform=linux/arm64 \
		--provenance=false \
		--sbom=false \
		--no-cache \
		-t $(DOCKER_IMAGE):$(DOCKER_TAG) \
		.

docker-run-smoke:
	@echo "Smoke test: import app.main inside the image..."
	docker run --rm $(DOCKER_IMAGE):$(DOCKER_TAG) \
		python -c "import app.main; print('✅ Module imports successfully')"

docker-image-size:
	@docker images $(DOCKER_IMAGE):$(DOCKER_TAG) \
		--format "table {{.Repository}}\t{{.Tag}}\t{{.Size}}"

# ═══ Step 3 closure regression (Step 3.4.c) ═══

regression-all:
	@echo "Running full test regression (unit + integration)..."
	@echo "Pre-requisite: 'make compose-up-infra' must be running"
	@echo "Pre-requisite: backend/.env must have DEEPSEEK_API_KEY"
	@echo ""
	cd backend && uv run pytest -v
