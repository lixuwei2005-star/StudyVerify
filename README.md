# StudyVerify

Verification-driven AI learning companion.

## Status

🚧 **Week 4 / 12 — Verifier Agent + Docker sandbox operational**

### What works
- ✅ FastAPI backend with `/health`, `/health/db`,
  `/api/v1/solve`, `/api/v1/verify`, `/api/v1/sessions/...`,
  `/api/v1/verifier-sessions/...`
- ✅ Solver Agent: 3-stage LLM pipeline + sandbox self-verification
- ✅ Verifier Agent: runs student code in hardened Docker sandbox;
  generates LLM-based diagnostic feedback when tests fail
- ✅ Anti-leak contract: redacted student-facing schemas at three
  layers (Pydantic, prompt construction, DB write)
- ✅ Postgres + Redis + FastAPI via Docker Compose; all 3 services
  report (healthy)
- ✅ SQLAlchemy 2.0 async + Alembic migrations (3-stage backfill
  pattern for required-field additions)
- ✅ 4-layer architecture: Route → Service → Repository + Agent
- ✅ Docker sandbox with 14 hardening flags (network=none,
  cap_drop=ALL, pids_limit, etc.) verified via baseline
  isolation smoke tests
- ✅ Every solve and verify invocation persisted; full session
  history queryable
- ✅ 89+ unit tests + 30+ integration tests across mocked,
  SQLite, real Postgres, real DeepSeek, and real Docker layers

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

To submit student code against a solved problem:

```bash
SOLVER_ID=$(curl -s -X POST http://localhost:8000/api/v1/solve \
  -H "Content-Type: application/json" \
  -d "$(jq '.[0]' backend/tests/agents/fixtures/sample_problems.json)" | jq -r .session_id)
curl -X POST http://localhost:8000/api/v1/verify \
  -H "Content-Type: application/json" \
  -d "{\"solver_session_id\": \"$SOLVER_ID\", \"student_code\": \"def sum_list(nums):\\n    return sum(nums)\"}"
```

For an automated end-to-end check:

```bash
make smoke-stack
```

Stop with `make compose-down`. See [docs/runbook-docker.md](docs/runbook-docker.md)
for operations reference.

## Develop locally (hot reload)

For active backend development, run the FastAPI app on the host
with infrastructure containerized:

```bash
make compose-up-infra              # postgres + redis only
cd backend && uv run uvicorn app.main:app --reload
```

Edit code → uvicorn auto-reloads. Tests run against the same
infrastructure.

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

Test counts (Week 4):
- Unit: 89+ (mocked LLM, in-memory SQLite)
- Integration: 30+ (real Postgres, real DeepSeek API, real Docker)

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
- **Verifier layer** (`backend/app/agents/verifier/`) — stateless
  agent runs student code in Docker sandbox; LLM generates
  diagnostic feedback with strict anti-leak prompt construction
- **Docker sandbox** (`backend/app/sandbox/docker_runner.py`) —
  14-flag hardened container with bind-mount payload delivery
  (cross-platform reliable)
- **Anti-leak defense** — RedactedTestResult schema + prompt
  construction omits expected values + DB JSONB never stores
  expected key; verified via Pydantic reflection tests +
  end-to-end LLM behavior tests

## Roadmap

### Completed
- ✅ Step 0-2: Environment, FastAPI skeleton, Solver Agent + sandbox
- ✅ Step 3: Persistence layer (Postgres + Alembic + Service/Repo +
  full Docker Compose stack)
- ✅ Step 4: Verifier Agent (Docker sandbox + diagnostic feedback +
  persistence + REST endpoints)

### Upcoming
- ⬜ Step 5: Hint Agent + LangGraph orchestration
- ⬜ Step 6: Multi-model gateway (Anthropic fallback) + RAG
- ⬜ Step 7: Frontend (Next.js + Monaco)
- ⬜ Step 8-12: ML problems / evaluation / knowledge graph /
  blog / MCP

## License

MIT (LICENSE file to be added).
