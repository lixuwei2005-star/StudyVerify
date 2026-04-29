# StudyVerify

Verification-driven AI learning companion.

## Status

🚧 **Week 3 / 12 — Persistence layer + REST API operational, full Docker stack ready**

### What works
- ✅ FastAPI backend with `/health`, `/health/db`,
  `/api/v1/solve`, `/api/v1/sessions/{id}`, `/api/v1/sessions`
- ✅ Solver Agent: 3-stage LLM pipeline + sandbox self-verification
- ✅ DeepSeek V4 Flash integration with retry/backoff
- ✅ Postgres + Redis + FastAPI via Docker Compose (Makefile-wrapped),
  all three services report `(healthy)`
- ✅ SQLAlchemy 2.0 async + Alembic migrations (incl. 3-stage
  backfill pattern); migrations auto-run on api container start
- ✅ 3-layer architecture: Route → Service → Repository + Agent
- ✅ Every solve invocation persisted; full session history queryable

### Up next
- 🔜 Step 4: Verifier Agent (validates student code against ground truth)

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

Test counts (Week 3):
- Unit: 50+ (mocked LLM, in-memory SQLite)
- Integration: 25+ (real Postgres, real DeepSeek API)

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

## License

MIT (LICENSE file to be added).
