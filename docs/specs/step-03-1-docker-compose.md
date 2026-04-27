# StudyVerify — Step 3.1: Docker Compose Infrastructure Spec

## Goal
Stand up Postgres and Redis as Docker Compose services. FastAPI 
remains running locally via `uv run uvicorn` and connects to the 
containers over `localhost`. Verify network connectivity, data 
persistence across `docker compose --env-file .env.docker down`, and 
health checks.

## Why So Narrow
Docker debugging compounds: a misconfigured service + a misconfigured 
client + a misconfigured network = three problems at once. By 
isolating "just get the containers running and reachable" first, any 
later database or cache bug is unambiguously in app code, not infra.

## Scope (this step)
- Docker Compose v2 (`docker compose` not `docker-compose`)
- Postgres 16 (alpine) — official image
- Redis 7 (alpine) — official image
- Named volumes for data persistence
- Health checks on both services
- A `.env`-driven configuration so secrets stay out of compose file
- Smoke-test scripts: `psql` and `redis-cli` accessible from within 
  containers + connectable from host

## Out of Scope (this step)
- ❌ FastAPI Dockerfile / containerization → Step 3.4
- ❌ SQLAlchemy / Alembic / models → Step 3.2
- ❌ Any application schema or tables → Step 3.2
- ❌ pgvector extension setup → Step 6 (when needed)
- ❌ Production tuning (connection pool sizes, autovacuum, etc.) → later
- ❌ Cloud deployment (AWS RDS / Aiven) → way later

## Tech Stack Additions
- `docker-compose.yml` (v2 syntax, no `version:` key — that's deprecated)
- New env vars in `.env.docker` for DB/Redis credentials
- `Makefile` convenience targets for routine Docker Compose and smoke-test commands
- No new Python dependencies yet (those come in 3.2)

## Files to Create / Modify

### New files
- `docker-compose.yml` (project root)
- `.env.docker.example` — separate env file for compose, in case 
  Postgres-specific vars conflict with backend's `.env`. Documents 
  POSTGRES_*, REDIS_* vars.
- `scripts/db-smoke-test.sh` — bash script: connects to Postgres 
  via psql in the container, runs `SELECT 1`, prints version
- `scripts/redis-smoke-test.sh` — bash script: PING and SET/GET test
- `docs/runbook-docker.md` — Brief runbook with commands for: 
  starting, stopping, viewing logs, accessing psql/redis-cli, 
  resetting volumes (when needed)
- `Makefile` (project root) — convenient targets that wrap docker 
  compose with the --env-file flag baked in.

### Modified files
- `.gitignore` — ADD these lines to ensure ALL env file variants 
  are ignored:
  ```gitignore
  .env.docker
  .env.docker.local
  **/.env.docker
  ```
  Existing `**/.env` does NOT match `.env.docker`. Verify after with 
  `git check-ignore -v .env.docker`. Also ensure 
  `docker-compose.override.yml` is gitignored (devs may need local 
  overrides).
- `README.md` — add a "Quick start with Docker" section pointing to 
  `docker compose --env-file .env.docker up -d` and the smoke test 
  scripts

## docker-compose.yml Structure

```yaml
services:
  postgres:
    image: postgres:16-alpine
    container_name: studyverify-postgres
    restart: unless-stopped
    environment:
      POSTGRES_DB: ${POSTGRES_DB:-studyverify}
      POSTGRES_USER: ${POSTGRES_USER:-studyverify}
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:?POSTGRES_PASSWORD required}
    ports:
      - "${POSTGRES_PORT:-5432}:5432"
    volumes:
      - postgres-data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U ${POSTGRES_USER:-studyverify} -d ${POSTGRES_DB:-studyverify}"]
      interval: 5s
      timeout: 5s
      retries: 10
      start_period: 10s

  redis:
    image: redis:7-alpine
    container_name: studyverify-redis
    restart: unless-stopped
    command: redis-server --appendonly yes --requirepass ${REDIS_PASSWORD:?REDIS_PASSWORD required}
    ports:
      - "${REDIS_PORT:-6379}:6379"
    volumes:
      - redis-data:/data
    healthcheck:
      test: ["CMD", "redis-cli", "-a", "${REDIS_PASSWORD}", "ping"]
      interval: 5s
      timeout: 3s
      retries: 5
      start_period: 5s

volumes:
  postgres-data:
    name: studyverify-postgres-data
  redis-data:
    name: studyverify-redis-data
```

Key design decisions in this YAML:
1. **No `version:` key** — Compose v2 doesn't need it
2. **`container_name`** — fixed names so `docker exec studyverify-postgres ...` works predictably
3. **`${VAR:?error message}`** — fails loudly if .env is missing 
   required vars instead of silently using defaults
4. **`restart: unless-stopped`** — survives Mac reboots / Docker 
   Desktop restarts, but `docker compose --env-file .env.docker down` 
   still stops them cleanly
5. **Named volumes (not bind mounts)** — Docker manages location, 
   no host-OS permission issues
6. **Healthchecks before deps** — when 3.4 adds the API service, it 
   will use `depends_on: postgres: condition: service_healthy`

## .env.docker.example Content

```bash
# Postgres
POSTGRES_DB=studyverify
POSTGRES_USER=studyverify
POSTGRES_PASSWORD=change_me_locally
POSTGRES_PORT=5432

# Redis
REDIS_PASSWORD=change_me_locally
REDIS_PORT=6379
```

User instructions:
1. Copy `.env.docker.example` to `.env.docker` (NOT to `.env` — 
   that file is reserved for backend application secrets like 
   DEEPSEEK_API_KEY).
2. Replace both passwords with strong random values. Suggested:
   `openssl rand -base64 24` for each.
3. When running compose commands, ALWAYS pass `--env-file .env.docker`:
   - `docker compose --env-file .env.docker up -d`
   - `docker compose --env-file .env.docker down`
   - `docker compose --env-file .env.docker logs -f`
   This keeps backend/.env (app secrets) and .env.docker (infra 
   credentials) in separate, non-conflicting namespaces.
4. Alternative: create a shell alias or Makefile target like 
   `make compose-up` that wraps the --env-file flag.

## Smoke Test Scripts

### `scripts/db-smoke-test.sh`
```bash
#!/usr/bin/env bash
set -euo pipefail

# Requires POSTGRES_PASSWORD and related vars to be exported first:
# set -a && source .env.docker && set +a

# Test from inside the container (proves postgres is alive)
docker exec studyverify-postgres pg_isready -U "${POSTGRES_USER:-studyverify}"

# Test connection from host (proves port mapping works)
PGPASSWORD="${POSTGRES_PASSWORD}" psql \
  -h localhost \
  -U "${POSTGRES_USER:-studyverify}" \
  -d "${POSTGRES_DB:-studyverify}" \
  -c "SELECT version();"

echo "✅ Postgres smoke test passed"
```

Note: requires `psql` on host. Add note: `brew install libpq && 
brew link --force libpq` if missing.

### `scripts/redis-smoke-test.sh`
```bash
#!/usr/bin/env bash
set -euo pipefail

# Requires REDIS_PASSWORD and related vars to be exported first:
# set -a && source .env.docker && set +a

# PING via redis-cli inside container
docker exec studyverify-redis redis-cli -a "${REDIS_PASSWORD}" ping

# SET/GET roundtrip from host
redis-cli -h localhost -p "${REDIS_PORT:-6379}" -a "${REDIS_PASSWORD}" \
  SET smoke-test "hello-$(date +%s)"
redis-cli -h localhost -p "${REDIS_PORT:-6379}" -a "${REDIS_PASSWORD}" \
  GET smoke-test
redis-cli -h localhost -p "${REDIS_PORT:-6379}" -a "${REDIS_PASSWORD}" \
  DEL smoke-test

echo "✅ Redis smoke test passed"
```

Note: requires `redis-cli` on host. Add note: `brew install redis` 
installs both server and CLI; we only need the CLI here.

Both scripts must be `chmod +x` after creation.
Smoke test scripts depend on exported environment variables 
(`POSTGRES_PASSWORD`, `REDIS_PASSWORD`, etc.), so source `.env.docker` 
before running them:
`set -a && source .env.docker && set +a`.

## Runbook (`docs/runbook-docker.md`)

Sections to include:
1. **First-time setup** — copy env file, generate passwords, 
   `docker compose --env-file .env.docker pull`, 
   `docker compose --env-file .env.docker up -d`
2. **Daily commands** — 
   `docker compose --env-file .env.docker up -d`, 
   `docker compose --env-file .env.docker down`, 
   `docker compose --env-file .env.docker logs -f`, 
   `docker compose --env-file .env.docker ps`
3. **Connect interactively** — `docker exec -it studyverify-postgres psql -U studyverify`, 
   `docker exec -it studyverify-redis redis-cli -a $REDIS_PASSWORD`
4. **View logs** — `docker compose --env-file .env.docker logs -f postgres`
5. **Reset all data (destructive!)** — 
   `docker compose --env-file .env.docker down -v` 
   then re-up; warn that this drops volumes
6. **Troubleshooting** — port conflicts (5432 already in use), 
   "permission denied" on volume, container restarting in a loop
7. **Smoke tests** — source env first with 
   `set -a && source .env.docker && set +a`, then run 
   `bash scripts/db-smoke-test.sh` and 
   `bash scripts/redis-smoke-test.sh`

Keep it short and scannable, not a tutorial. Aim for 1-2 pages.

## Verification Checklist (must all pass)

1. **Files exist**:
   - `docker-compose.yml`
   - `.env.docker.example`
   - `.env.docker` (NOT committed — verify `git check-ignore -v .env.docker` succeeds)
   - `scripts/db-smoke-test.sh` and `scripts/redis-smoke-test.sh` 
     are executable
   - `docs/runbook-docker.md` exists

   Before continuing, run `git check-ignore -v .env.docker`. If it 
   does not print the matching ignore rule, immediately fix 
   `.gitignore` before creating or using `.env.docker`.

2. **Docker compose lints clean**: 
   `docker compose --env-file .env.docker config` outputs the resolved 
   YAML with no errors

3. **Containers start healthy**:
   - `docker compose --env-file .env.docker up -d`
   - `docker compose --env-file .env.docker ps` shows both with `(healthy)` status within 30s
   - `docker compose --env-file .env.docker logs postgres | tail -20` shows "database system 
     is ready to accept connections"
   - `docker compose --env-file .env.docker logs redis | tail -10` shows "Ready to accept 
     connections"

4. **Smoke tests pass**:
   - Source the env: `set -a && source .env.docker && set +a`
   - Run `bash scripts/db-smoke-test.sh` → exit 0, prints version
   - Run `bash scripts/redis-smoke-test.sh` → exit 0, prints "PONG" 
     and "hello-..."

5. **Persistence verification**:
   - In container: `docker exec studyverify-postgres psql -U studyverify -c "CREATE TABLE smoke_test (id INT); INSERT INTO smoke_test VALUES (42);"`
   - `docker compose --env-file .env.docker down` (no `-v`)
   - `docker compose --env-file .env.docker up -d`, wait for healthy
   - `docker exec studyverify-postgres psql -U studyverify -c "SELECT * FROM smoke_test;"` 
     should return the row with `42`
   - Cleanup: `DROP TABLE smoke_test`

6. **Reset behavior verified**:
   - `docker compose --env-file .env.docker down -v` (note the `-v` flag)
   - `docker volume ls | grep studyverify` should show NO volumes
   - `docker compose --env-file .env.docker up -d`, wait for healthy
   - Postgres should be a fresh empty database (CREATE DATABASE 
     ran from scratch)

7. **Port conflict handling**:
   - If host already has Postgres on 5432, document changing 
     `POSTGRES_PORT` in `.env.docker` (does not require code change)

## What NOT to do
- DO NOT use `version: "3.x"` at the top of compose file (deprecated)
- DO NOT bind-mount `./postgres-data` to host filesystem (permission 
  hell on Mac)
- DO NOT skip healthchecks ("it works on my machine" until 3.4 wires 
  depends_on)
- DO NOT commit `.env.docker` — only `.env.docker.example`
- DO NOT use `latest` tag for images — pin to major version 
  (postgres:16-alpine, redis:7-alpine)
- DO NOT expose Postgres password in compose file literals — must 
  flow via env
- DO NOT run `docker compose --env-file .env.docker up` without `-d` 
  for routine work — blocks the terminal; use `-d` then 
  `docker compose --env-file .env.docker logs -f` if you need output
- DO NOT use `network_mode: host` — explicit ports more portable

## Notes on Apple Silicon
Both `postgres:16-alpine` and `redis:7-alpine` have native arm64 
images, so they run without Rosetta emulation. No special config 
needed for M-series Macs. If you see "platform mismatch" warnings, 
double-check `docker version` shows `arm64`.

## Makefile Content

```makefile
# Makefile

# Use bash, not sh
SHELL := /usr/bin/env bash

# Default target
.DEFAULT_GOAL := help

# Compose command with env-file pre-set
COMPOSE := docker compose --env-file .env.docker

.PHONY: help compose-up compose-down compose-down-volumes \
        compose-logs compose-ps compose-config \
        smoke-db smoke-redis smoke-all

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

compose-up:
	$(COMPOSE) up -d

compose-down:
	$(COMPOSE) down

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
```

Benefits:
- Developers can run `make compose-up` instead of remembering the full 
  `docker compose --env-file .env.docker up -d` command.
- `make compose-down-volumes` includes a confirmation prompt to reduce 
  accidental data loss.
- `make help` documents the common development commands in one place.
- This standardizes the dev workflow and keeps compose usage consistent 
  across README, runbook, and scripts.

## Estimated Time
- Writing compose + scripts: 30 min
- First `docker compose --env-file .env.docker pull` (download images): 1-2 min
- Verification end-to-end: 15-20 min
- Runbook writing: 15 min
- **Total: ~1 hour active work**

(But save half a day in your planning for inevitable Docker 
mysteries.)
