# StudyVerify development Makefile
# Wraps `docker compose --env-file .env.docker` so devs don't have to remember
# the flag, and centralizes smoke-test invocation.

SHELL := /usr/bin/env bash

.DEFAULT_GOAL := help

# Compose command with env-file pre-set
COMPOSE := docker compose --env-file .env.docker

.PHONY: help compose-up compose-down compose-down-volumes \
        compose-logs compose-ps compose-config \
        smoke-db smoke-redis smoke-all \
        docker-build docker-build-fresh docker-run-smoke docker-image-size

help:
	@echo "StudyVerify development commands:"
	@echo ""
	@echo "  make compose-up           - Start Postgres + Redis containers"
	@echo "  make compose-down         - Stop containers (data preserved)"
	@echo "  make compose-down-volumes - Stop AND delete volumes (DESTRUCTIVE)"
	@echo "  make compose-logs         - Tail logs from all services"
	@echo "  make compose-ps           - List running containers"
	@echo "  make compose-config       - Show resolved compose config"
	@echo "  make smoke-db             - Run Postgres smoke test"
	@echo "  make smoke-redis          - Run Redis smoke test"
	@echo "  make smoke-all            - Run both smoke tests"
	@echo ""
	@echo "  make docker-build         - Build studyverify-api image (arm64)"
	@echo "  make docker-build-fresh   - Build with --no-cache"
	@echo "  make docker-run-smoke     - Smoke test: import app.main in image"
	@echo "  make docker-image-size    - Show built image size"

compose-up:
	$(COMPOSE) up -d

compose-down:
	$(COMPOSE) down

# Interactive confirmation gate. NOT safe for CI / non-interactive shells —
# the `read` will hang or fail. CI should call `$(COMPOSE) down -v` directly.
compose-down-volumes:
	@echo "⚠️  This will DELETE all data in Postgres and Redis."
	@read -p "Type 'yes' to continue: " confirm && [ "$$confirm" = "yes" ]
	$(COMPOSE) down -v

compose-logs:
	$(COMPOSE) logs -f

compose-ps:
	$(COMPOSE) ps

compose-config:
	$(COMPOSE) config

smoke-db:
	@set -a && source .env.docker && set +a && bash scripts/db-smoke-test.sh

smoke-redis:
	@set -a && source .env.docker && set +a && bash scripts/redis-smoke-test.sh

smoke-all: smoke-db smoke-redis

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
