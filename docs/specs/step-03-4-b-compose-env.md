# StudyVerify — Step 3.4.b: Compose Service + Env Wiring Spec

## Goal
Add the FastAPI image (built in 3.4.a) as a third docker-compose 
service, wire DATABASE_URL for in-network hostname resolution, and 
run alembic migrations automatically on container startup. After 
this step, `make compose-up` brings up the full stack (postgres + 
redis + api) and `curl localhost:8000/health/db` succeeds without 
any local uvicorn running.

## Why So Narrow
Compose service definition + env-var injection + startup migration 
are three independent failure modes. Isolating them from healthcheck 
work (deferred to 3.4.c) keeps debugging tractable.

## Scope
- Add `api` service to `docker-compose.yml`
- Wire `DATABASE_URL` via compose `environment:` for in-network 
  hostname (`postgres`, not `localhost`)
- Set startup `command:` to chain alembic migration + uvicorn
- `depends_on: postgres: condition: service_healthy` so api waits 
  for DB readiness
- Mount nothing volume-wise (image is self-contained)
- Update `.env.docker.example` with new vars the api service needs
- Update Makefile help text

## Out of Scope (this step)
- ❌ Healthcheck for api container → 3.4.c
- ❌ Logging configuration / log volume → 3.4.c
- ❌ README "Quick Start with Docker" → 3.4.c
- ❌ Production hardening (resource limits, restart policies beyond 
  defaults) → later
- ❌ Hot-reload mode for dev (--reload) → optional 3.4.c addition

## Tech Stack Additions
- No new dependencies; uses existing image from 3.4.a

## Files to Modify

- `docker-compose.yml` — add `api` service
- `.env.docker.example` — document new vars (DEEPSEEK_API_KEY etc., 
  noting they live in backend/.env for local mode but are read here 
  for the api container)
- `Makefile` — update help text to mention full-stack `compose-up` 
  semantics; add a convenience target `compose-up-rebuild` that 
  builds image first

## docker-compose.yml — `api` service definition

Append to `services:`:

```yaml
  api:
    image: studyverify-api:dev
    pull_policy: never  # never try to pull from registry; image must
                        # be built locally first via `make docker-build`
                        # or `make compose-up-rebuild`
    container_name: studyverify-api
    restart: unless-stopped
    depends_on:
      postgres:
        condition: service_healthy
      redis:
        condition: service_healthy
    environment:
      # Database URL uses the compose service name 'postgres' as 
      # hostname, NOT localhost. backend/.env's DATABASE_URL is 
      # ignored when running under compose because this var takes 
      # precedence in the container's environment.
      DATABASE_URL: "postgresql+asyncpg://${POSTGRES_USER}:${POSTGRES_PASSWORD}@postgres:5432/${POSTGRES_DB}"
      
      # All other settings: pass through from .env.docker so secrets 
      # never appear in compose YAML literals.
      # Empty default — base stack (postgres/redis/health endpoints) 
      # starts without it. /api/v1/solve will 502 if unset; live LLM 
      # verification requires this var.
      DEEPSEEK_API_KEY: ${DEEPSEEK_API_KEY:-}
      DEEPSEEK_BASE_URL: ${DEEPSEEK_BASE_URL:-https://api.deepseek.com/v1}
      DEEPSEEK_MODEL: ${DEEPSEEK_MODEL:-deepseek-v4-flash}
      DEEPSEEK_REASONING_EFFORT: ${DEEPSEEK_REASONING_EFFORT:-none}
      
      # Application settings
      LOG_LEVEL: ${LOG_LEVEL:-INFO}
      ENV: ${ENV:-development}
      
      # Sandbox limits (future Verifier in Step 4 will use stricter)
      SANDBOX_TIMEOUT_SECONDS: ${SANDBOX_TIMEOUT_SECONDS:-5}
      SANDBOX_MEMORY_MB: ${SANDBOX_MEMORY_MB:-128}
    ports:
      - "${API_PORT:-8000}:8000"
    command: >
      sh -c "alembic upgrade head &&
             exec uvicorn app.main:app --host 0.0.0.0 --port 8000"
```

### Design notes

- **`image: studyverify-api:dev`** — uses pre-built image; doesn't 
  re-build inside compose. To rebuild, user runs `make docker-build` 
  first (or `make compose-up-rebuild` which we'll add).

- **`pull_policy: never`** — avoids surprising registry pulls for 
  a local-only dev image. If the image does not exist yet, compose 
  fails clearly and the developer should run `make docker-build` or 
  `make compose-up-rebuild`.

- **`depends_on` with `condition: service_healthy`** — leverages 
  the healthchecks set up in Step 3.1 for postgres and redis. The 
  api won't start until both are reporting healthy, eliminating 
  "connection refused" race conditions on first launch.

- **`DATABASE_URL` interpolated from POSTGRES_* vars** — single 
  source of truth (`.env.docker`) for credentials. The hostname 
  `postgres` is the compose service name, which docker-compose 
  registers in its internal DNS for sibling containers.

- **`${VAR:-}` for DEEPSEEK_API_KEY** — keeps the base stack usable 
  for `/health` and `/health/db` even when no LLM key is configured. 
  Live `/api/v1/solve` verification still requires the key and should 
  fail clearly if it is absent.

- **`${VAR:-default}` for non-secret defaults** — base URL, model 
  name, log level: sensible defaults so users don't need to set 
  every var.

- **`ports: "${API_PORT:-8000}:8000"`** — host port configurable 
  in case 8000 is taken locally; container always uses 8000.

- **`command:` with `sh -c` + `exec`** — `sh` exits after spawning 
  uvicorn via `exec`, so PID 1 in the container is uvicorn (proper 
  signal handling for SIGTERM on `compose down`).

### Limitation: depends_on is startup-only

`condition: service_healthy` only gates initial container creation 
— it is not continuous supervision. If postgres becomes unhealthy 
AFTER api has started, compose does not re-gate the api. With 
`restart: unless-stopped`, api will exit on connection loss and 
auto-restart, which is acceptable for development.

Production-grade resilience (api health-self-check + connection 
retry with backoff) is out of scope for 3.4.b; basic api healthcheck 
arrives in 3.4.c.

## .env.docker.example — additions

Add to the existing file:

```bash
# Generate secure passwords with: openssl rand -hex 24
# (NOT base64 — base64 includes / which breaks URL passwords)

# ─── Application (api container) ───
# These mirror values from backend/.env but are explicitly listed 
# here because docker-compose passes them into the api container.
# Do NOT commit real values. Copy to .env.docker locally and fill in.

# Required for live /api/v1/solve only; base health checks work empty.
DEEPSEEK_API_KEY=

# Optional, with sensible defaults; uncomment to override
# DEEPSEEK_BASE_URL=https://api.deepseek.com/v1
# DEEPSEEK_MODEL=deepseek-v4-flash
# DEEPSEEK_REASONING_EFFORT=none
# LOG_LEVEL=INFO
# ENV=development
# SANDBOX_TIMEOUT_SECONDS=5
# SANDBOX_MEMORY_MB=128

# Host port the api binds to (container always 8000)
# API_PORT=8000
```

User instructions in spec:
1. Copy `DEEPSEEK_API_KEY` value from `backend/.env` to `.env.docker`
2. Other vars optional; defaults work for development
3. If `DEEPSEEK_API_KEY` is missing, compose still starts the base 
   stack; `/api/v1/solve` should return a clear 502 until the key is 
   restored.

## Makefile — additions

Add new targets and update help:

```makefile
# Add to existing .PHONY line
.PHONY: help compose-up compose-up-infra compose-up-rebuild compose-down ...

compose-up-infra:
	@echo "Starting infrastructure only (postgres + redis)..."
	@echo "Use this when running uvicorn locally (cd backend && uv run uvicorn ...)"
	$(COMPOSE) up -d postgres redis

compose-up-rebuild: docker-build
	@echo "Rebuilt image; bringing up full stack..."
	$(COMPOSE) up -d
	@echo ""
	@echo "Stack is starting. Wait ~10s, then check:"
	@echo "  make compose-ps      # postgres + redis healthy; api healthcheck arrives in 3.4.c"
	@echo "  curl localhost:8000/health/db"
```

### Update existing `compose-logs` to accept SERVICE arg

Modify the existing target in Makefile (was added in 3.1):

```makefile
SERVICE ?=

compose-logs:
	$(COMPOSE) logs -f $(SERVICE)
```

Default `SERVICE=""` follows all services (backward compatible). 
Override with `make compose-logs SERVICE=api` to follow only one.

Update help text:
```makefile
help:
	@echo "StudyVerify development commands:"
	@echo ""
	@echo "  make compose-up           - Start full stack (postgres + redis + api)"
	@echo "                              postgres + redis show (healthy);"
	@echo "                              api healthcheck arrives in 3.4.c"
	@echo "  make compose-up-infra     - Start infrastructure only for local uvicorn"
	@echo "  make compose-up-rebuild   - Rebuild api image, then start stack"
	@echo "  make compose-logs                  - Tail logs from all services"
	@echo "  make compose-logs SERVICE=api      - Tail logs from one service"
	# ... (rest unchanged)
```

## Verification Checklist

Pre-flight:
- `make compose-down` — ensure clean slate (any leftover containers 
  stopped)
- `make docker-build` — confirm api image exists (was 269 MB after 
  3.4.a)
- For live `/api/v1/solve` verification only: 
  `cat .env.docker | grep DEEPSEEK_API_KEY` — must show a real key, 
  not blank

1. **Compose config lints clean**:
   - `make compose-config` — exits 0, resolved YAML shows api 
     service with DATABASE_URL containing `@postgres:5432`, all env 
     vars resolved (no `${...}` literals leaking through)

2. **Stack starts cleanly with `make compose-up`**:
   - All 3 containers listed in `docker compose ps`
   - postgres healthy first (~5s), redis healthy soon after
   - api starts AFTER both are healthy (depends_on respected)
   - Watch logs: `make compose-logs` — should see:
     - `INFO  [alembic.runtime.migration] Will assume transactional DDL`
     - Migration "0b3015bfb3f1 -> d3bd309a15f6" applies if not 
       already at head, OR "Already at head" if reusing existing volume
     - Then `INFO: Uvicorn running on http://0.0.0.0:8000`
   - If api never becomes healthy or keeps restarting:
     - Check `make compose-logs SERVICE=api` immediately
     - Common cause: alembic migration failure (e.g., model out of 
       sync, password URL-unsafe). Migration errors print to stderr 
       before uvicorn would start.
     - A persistent migration bug + `restart: unless-stopped` 
       produces a restart loop — `compose ps` will show api status 
       flipping between Created / Restarting.

3. **Health endpoints reachable from host**:
   - `curl http://localhost:8000/` returns the welcome message
   - `curl http://localhost:8000/health` returns service info
   - `curl http://localhost:8000/health/db` returns 
     `{"status":"ok","db":"reachable"}`
   - These prove: port mapping works + api ↔ postgres in-network 
     resolution works

4. **End-to-end POST /solve** through containerized stack:
   - `curl -X POST http://localhost:8000/api/v1/solve \
       -H "Content-Type: application/json" \
       -d "$(jq '.[0]' backend/tests/agents/fixtures/sample_problems.json)"`
   - Response: `{"session_id": "...", "output": {..., "verified": true}}`
   - Real DeepSeek API was called (api container has DEEPSEEK_API_KEY)
   - Real PG insert happened (api connected to postgres container)

5. **Verify the row landed in containerized PG**:
   - Use env vars from inside the container so this works regardless 
     of POSTGRES_USER / POSTGRES_DB customization:
     ```bash
     docker exec studyverify-postgres sh -c \
       'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c \
        "SELECT id, problem_id, verified, total_latency_ms FROM solver_sessions ORDER BY created_at DESC LIMIT 3;"'
     ```
   - Should see the row from step 4

6. **/solve degrades gracefully without DEEPSEEK_API_KEY** (optional):
   - Comment out DEEPSEEK_API_KEY in .env.docker
   - `make compose-down && make compose-up`
   - Stack starts normally (no compose-level error)
   - `/health` and `/health/db` return 200
   - `POST /api/v1/solve` returns 502 with clear error message about 
     missing API key
   - Restore the var for end-to-end testing

7. **`compose-up-rebuild` works**:
   - `make compose-down`
   - `make compose-up-rebuild` — should rebuild image (cached layers, 
     ~3s) and bring stack up

8. **No regression on local-uvicorn workflow**:
   - `make compose-down`
   - `make compose-up-infra`
   - `cd backend && uv run uvicorn app.main:app --reload`
   - This still works because `backend/.env` still has 
     `DATABASE_URL=postgresql+asyncpg://...@localhost:5432/...`
   - `curl localhost:8000/health/db` returns ok
   - Stop local uvicorn

## What NOT to do

- DO NOT use `localhost` as hostname in container's DATABASE_URL 
  — that's the container's own loopback, not Mac's
- DO NOT remove backend/.env or change its localhost-based 
  DATABASE_URL — it's still needed for local-uvicorn workflow
- DO NOT bake DEEPSEEK_API_KEY into compose YAML literally — env 
  var interpolation only
- DO NOT use `condition: service_started` (default) — that races 
  with postgres init; must be `service_healthy`
- DO NOT skip `exec` in the command shell — without it, sh stays 
  PID 1 and forwards SIGTERM poorly
- DO NOT add `volumes: - ./backend:/app/backend` for live reload — 
  that's a 3.4.c optional dev-mode pattern, premature here
- DO NOT include `tty: true` or `stdin_open: true` — not interactive
- DO NOT change the api image build context (still uses 3.4.a's 
  image as-is)

## Implementation Notes

Pre-implementation safety check:

POSTGRES_PASSWORD is URL-critical: it's interpolated into 
DATABASE_URL=postgresql+asyncpg://user:PASSWORD@host:5432/db, where 
'/', '+', '=' from base64 output break URL parsing in asyncpg.

- Inspect existing .env.docker. If POSTGRES_PASSWORD contains '/', 
  '+', '=', or other URL-unsafe characters (likely if generated 
  with `openssl rand -base64 ...` per the original 3.1 spec), 
  REGENERATE it with `openssl rand -hex 24` before proceeding.
- REDIS_PASSWORD is passed as a CLI argument (`redis-cli -a ...`) 
  or as a Python kwarg, NOT embedded in a URL. URL-unsafe chars 
  there don't break parsing, but regenerating both with 
  `openssl rand -hex 24` is recommended for consistency — it 
  establishes "all secrets are hex" as a uniform project invariant.
- After regenerating, verify by running `make compose-up-infra` 
  and connecting via psql; if connection fails with URL parse 
  errors, the password still has issues.

## Estimated Time
- Writing compose addition + .env.docker.example update: 20 min
- Makefile updates: 5 min
- First `make compose-up` and verification: 30 min
- Debug buffer (if alembic / network issues): 30 min
- **Total: ~1.5 hours active work**
