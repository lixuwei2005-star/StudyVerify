# StudyVerify — Step 3.4.c: Healthcheck + Docs + Step 3 Closure Spec

## Goal
Add api container healthcheck, write end-user-facing README "Quick 
Start with Docker" section, and run full Step 1-3 regression to 
confirm everything still works as a unit. After this, Step 3 is 
complete and the project is "clone-and-run" ready.

## Scope
- Healthcheck for api service in docker-compose.yml
- README.md updates: Status section, Quick Start section, 
  Architecture summary
- Full regression sweep across all test markers
- This step's spec is briefer than 3.4.a/b — most heavy work is done.

## Out of Scope
- ❌ CI workflow → later
- ❌ Production hardening (resource limits, log drivers) → later
- ❌ Deployment automation → later

## Files to Modify
- `docker-compose.yml` — add healthcheck to api service
- `README.md` — substantial update (Status, Quick Start, 
  Architecture, Roadmap)
- `Makefile` — add `regression-all` convenience target

## docker-compose.yml — api healthcheck

Add inside the `api:` service block (after `command:`):

````yaml
    healthcheck:
      test:
        - CMD
        - python
        - -c
        - >-
          import urllib.request, sys;
          r = urllib.request.urlopen("http://localhost:8000/health", timeout=2);
          sys.exit(0 if r.status == 200 else 1)
      interval: 10s
      timeout: 5s
      retries: 3
      start_period: 15s
````

Design notes:
- Uses Python urllib (no curl/wget in slim image; avoiding apt-install 
  would bloat image)
- Probes `/health` (liveness), NOT `/health/db` (readiness) — DB 
  unavailability shouldn't be diagnosed as api crash
- `start_period: 15s` accounts for alembic upgrade time on cold start; 
  failures during this window don't count toward `retries`

## README.md — full restructure

Sections in order:

1. **Title + tagline + status badge**
2. **Status block** — current week / what works / what's queued
3. **Quick Start with Docker** (~10 lines)
4. **Develop locally** (~10 lines)
5. **Run tests** (~10 lines)
6. **Architecture overview** — bullet list of layered components
7. **Roadmap** — Step 4-12 outline
8. **License**

Keep total under ~150 lines. Detailed setup goes in 
`docs/runbook-docker.md` (already exists from 3.1).

### Quick Start with Docker block:

````markdown
## Quick Start with Docker

Get the full stack (FastAPI + Postgres + Redis) running in three 
commands.

```bash
# 1. Clone and configure
git clone https://github.com/lixuwei2005-star/StudyVerify.git
cd StudyVerify
cp .env.docker.example .env.docker

# 2. Edit .env.docker — set POSTGRES_PASSWORD and REDIS_PASSWORD
#    (generate with: openssl rand -hex 24)
#    For LLM features, also set DEEPSEEK_API_KEY (optional for /health)

# 3. Start the stack
make compose-up-rebuild
```

First run uses `compose-up-rebuild` to build the image; subsequent 
restarts can use plain `make compose-up`.

After ~20-30 seconds (alembic migrations + healthcheck warmup), the 
stack is healthy:

```bash
make compose-ps                              # all 3 healthy
curl http://localhost:8000/health            # → {"status":"ok",...}
curl http://localhost:8000/health/db         # → {"status":"ok","db":"reachable"}
```

To exercise the Solver Agent end-to-end (requires DEEPSEEK_API_KEY):

```bash
curl -X POST http://localhost:8000/api/v1/solve \
  -H "Content-Type: application/json" \
  -d "$(jq '.[0]' backend/tests/agents/fixtures/sample_problems.json)"
```

Stop with `make compose-down`. See `docs/runbook-docker.md` for 
operations reference.
````

### Develop locally block:

````markdown
## Develop locally (hot reload)

For active backend development, run the FastAPI app on the host 
with infrastructure containerized:

```bash
make compose-up-infra              # postgres + redis only
cd backend && uv run uvicorn app.main:app --reload
```

Edit code → uvicorn auto-reloads. Tests run against the same 
infrastructure.
````

### Run tests block:

````markdown
## Run tests

```bash
cd backend

# Unit tests only (fast, no external dependencies)
uv run pytest -v -m "not integration"

# Integration tests (requires `make compose-up-infra` + DEEPSEEK_API_KEY)
uv run pytest -v -m integration

# Full sweep
uv run pytest -v
```

Test counts (Week 3):
- Unit: 50+ (mocked LLM, in-memory SQLite)
- Integration: 25+ (real Postgres, real DeepSeek API)
````

### Architecture overview block:

````markdown
## Architecture

Layered architecture with clear separation of concerns:

- **API layer** (`backend/app/api/routes/`) — thin handlers
- **Service layer** (`backend/app/services/`) — orchestration; 
  parameter-injected sessions allow stateless service shells
- **Repository layer** (`backend/app/repositories/`) — pure DB 
  access, never commits
- **Agent layer** (`backend/app/agents/`) — Solver with 3-stage 
  LLM pipeline + sandbox self-verification
- **Sandbox** (`backend/app/sandbox/`) — subprocess isolation with 
  rlimits + JSON-over-stdin (code/data separation)
- **Data layer** (`backend/app/db/`) — SQLAlchemy 2.0 async + 
  Alembic migrations
- **LLM layer** (`backend/app/llm/`) — DeepSeek client with typed 
  exceptions and retry/backoff
````

### Roadmap block:

````markdown
## Roadmap

### Completed
- ✅ Step 0-2: Environment, FastAPI skeleton, Solver Agent + sandbox
- ✅ Step 3: Persistence layer (Postgres + Alembic + Service/Repo + 
  full Docker Compose stack)

### Upcoming
- ⬜ Step 4: Verifier Agent (validates student code against 
  Solver ground truth, Docker sandbox)
- ⬜ Step 5: Hint Agent + LangGraph orchestration
- ⬜ Step 6: Multi-model gateway (Anthropic fallback) + RAG
- ⬜ Step 7: Frontend (Next.js + Monaco)
- ⬜ Step 8: ML problem support (incremental adapter)
- ⬜ Step 9: Evaluation suite (RAGAS-style)
- ⬜ Step 10: Knowledge graph + spaced repetition
- ⬜ Step 11: Optimization + technical blog
- ⬜ Step 12: Open-source release + MCP server
````

## Makefile addition

Add convenience target for the full regression:

````makefile
regression-all:
	@echo "Running full test regression (unit + integration)..."
	@echo "Pre-requisite: 'make compose-up-infra' must be running"
	@echo "Pre-requisite: backend/.env must have DEEPSEEK_API_KEY"
	@echo ""
	cd backend && uv run pytest -v
````

## Verification Checklist

1. **Healthcheck wires up**:
   - `make compose-down && make compose-up`
   - Wait ~20s for `start_period` + first interval
   - `make compose-ps` shows all 3 services as `(healthy)` — 
     including api now
   - `docker inspect studyverify-api --format '{{.State.Health.Status}}'` 
     shows `healthy`

2. **Healthcheck failure mode**:
   - With api running, `docker exec studyverify-api kill 1` 
     (or stop the uvicorn process)
   - Within ~30s, `docker compose ps` should show api as unhealthy 
     OR restarting (depends on restart policy)
   - Restore: `make compose-down && make compose-up`

3. **README renders cleanly on GitHub**:
   - Push and visit the repo page
   - Quick Start commands are copy-pasteable
   - Architecture and Roadmap sections render properly

4. **Full regression: unit tests**:
   - `make compose-down && make compose-up-infra`
   - `cd backend && uv run pytest -v -m "not integration"` 
   - All pass (target: 50+ tests)

5. **Full regression: integration tests** (requires 
   DEEPSEEK_API_KEY):
   - With infra still up, `cd backend && uv run pytest -v -m integration`
   - All pass (target: 25+ tests)

6. **Full stack end-to-end** (cleanup proof):
   - `make compose-down` (preserves volume)
   - `make compose-up` (full stack)
   - All 3 healthy
   - `curl POST /api/v1/solve` → 200 with verified=true
   - `curl GET /api/v1/sessions/{returned_id}` → 200 with full data
   - `curl GET /api/v1/sessions?problem_id=...` → 200 with list
   - `make compose-down`
   - This proves: container restart preserves data + endpoints work 
     after restart

7. **Final state**:
   - `make compose-down` — clean shutdown, no zombie containers
   - `git status` clean (no surprise changes)

## What NOT to do
- DO NOT use curl in the healthcheck — image doesn't have it, and 
  installing it bloats the image for marginal benefit
- DO NOT probe `/health/db` — that's readiness, not liveness; DB 
  blip should not show api as crashed
- DO NOT skip `start_period` — alembic on cold start takes longer 
  than the default healthcheck assumes
- DO NOT bloat README beyond ~150 lines — it's an entry point, not 
  a manual; detailed ops belong in `docs/runbook-docker.md`
- DO NOT move existing content from CLAUDE.md / runbook-docker.md 
  into README — keep documentation hierarchy intact

## Estimated Time
- Healthcheck addition + verify: 15 min
- README rewrite: 30 min
- Full regression run: 15 min
- Final cleanup + commit: 15 min
- **Total: ~75 min active**
