# StudyVerify

Verification-driven AI learning companion.

## Status

🚧 **Week 6 / 12 — RAG retrieval + corpus expansion shipped (Step 6.1 → 6.3)**

### What works
- ✅ FastAPI backend with `/health`, `/health/db`,
  `/api/v1/solve`, `/api/v1/verify`, `/api/v1/hint`, plus
  session-history GET endpoints
- ✅ Solver Agent: 3-stage LLM pipeline + sandbox self-verification
- ✅ Verifier Agent: runs student code in hardened Docker sandbox;
  generates diagnostic feedback that names neither code nor
  algorithm
- ✅ Hint Agent: progressive hints with diagnosis-as-seed for the
  first call; concurrent retry on hint_index race; hard cap of
  5 hints per verifier_session
- ✅ Anti-leak defense in depth across both Verifier and Hint:
  - Schema-level redaction (no `expected` field in any
    student-facing model)
  - Prompt construction never sees `expected` values
  - Algorithm-dictation guard with substring contract (no
    "use a loop", "iterate", "create a variable", "use sum()",
    etc.) enforced by integration tests
- ✅ Postgres + Redis + FastAPI via Docker Compose;
  `make compose-up-rebuild` is clone-and-run
- ✅ SQLAlchemy 2.0 async + Alembic migrations (3-stage backfill
  pattern for required-field additions)
- ✅ 4-layer architecture: Route → Service → Repository → Agent
- ✅ Docker sandbox with 14 hardening flags (network=none,
  cap_drop=ALL, pids_limit, etc.) verified via baseline
  isolation smoke tests
- ✅ Every solve / verify / hint invocation persisted; full
  session history queryable
- ✅ Multi-provider LLM gateway (DeepSeek primary + OpenAI
  fallback) with retry/backoff and provider-failure routing
- ✅ pgvector RAG retrieval over failed verifier sessions —
  past-failure inspiration for the Hint Agent, with
  algorithm-dictation guard applied to retrieved hints
- ✅ RAG corpus seeded from 50 LLM-generated buggy variants
  across 10 problems (84-row dev corpus) with cross-problem
  retrieval boundaries validated by Tier-1 deterministic
  pytest tests and a Tier-2 manual review script
- ✅ 200+ unit tests + 90+ integration tests across mocked,
  SQLite, real Postgres, real DeepSeek, and real Docker layers
- ✅ End-to-end smoke (`make smoke-stack`) covers full
  /solve → /verify → /hint chain

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

To request a progressive hint when verification fails (each call
returns the next hint, more specific than the last, without naming
code or algorithm steps):

```bash
VERIFIER_ID=$(curl -s -X POST http://localhost:8000/api/v1/verify \
  -H "Content-Type: application/json" \
  -d "{\"solver_session_id\": \"$SOLVER_ID\", \"student_code\": \"def sum_list(nums):\\n    return 0\"}" | jq -r .session_id)
curl -X POST http://localhost:8000/api/v1/hint \
  -H "Content-Type: application/json" \
  -d "{\"verifier_session_id\": \"$VERIFIER_ID\"}"
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

First-time PG test setup (one-time): create the `studyverify_test`
database that pg-marked tests use.

```bash
make test-db-create
```

```bash
cd backend

# Unit tests only (fast, no external dependencies)
uv run pytest -v -m "not integration"

# Integration tests (requires `make compose-up-infra` + DEEPSEEK_API_KEY
# + studyverify_test DB; OPENAI_API_KEY optional, enables RAG paths)
uv run pytest -v -m integration

# Slow tests (the full 10-problem solver-against-real-DeepSeek sweep;
# ~5-10 min, ~$0.05). Gated separately to keep the default integration
# suite cheap.
uv run pytest -v -m slow

# Full sweep (unit + integration; excludes slow by default unless added)
uv run pytest -v -m "not slow"
```

Test counts (Week 6):
- Unit: 200+ (mocked LLM, in-memory SQLite)
- Integration: 90+ (real Postgres, real DeepSeek API, real Docker,
  pgvector retrieval-quality)

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
- **Hint layer** (`backend/app/agents/hint/`) — stateless
  progressive-hint agent with concurrent-insert handling and
  diagnosis-as-seed for the first hint
- **Algorithm-dictation guard** — Verifier and Hint prompts share
  a substring contract preventing the LLM from naming control
  structures, built-ins, or stepwise algorithms; enforced by
  integration tests
- **RAG retrieval** (`backend/app/services/retrieval_service.py`)
  — pgvector cosine over `verifier_sessions.failure_embedding`,
  joined to `solver_sessions.problem_id` for cross-problem
  quality assertions; reads only, never commits
- **Corpus operator tools** (`backend/app/scripts/`) —
  `generate_buggy_variants.py` produces LLM-assisted candidate
  buggy implementations (parse-validate-retry, provider-switchable
  via the existing LLM gateway); `seed_failure_corpus.py` drives
  /solve → /verify against the local stack with sha256-based
  idempotency, --dry-run, and a localhost-gated destructive
  reseed flow

## Roadmap

### Completed
- ✅ Step 0-2: Environment, FastAPI skeleton, Solver Agent + sandbox
- ✅ Step 3: Persistence layer (Postgres + Alembic + Service/Repo +
  full Docker Compose stack)
- ✅ Step 4: Verifier Agent (Docker sandbox + diagnostic feedback +
  persistence + REST endpoints)
- ✅ Step 5: Hint Agent + verifier prompt tightening
- ✅ Step 6.1: Multi-provider LLM gateway (DeepSeek + OpenAI fallback)
- ✅ Step 6.2: pgvector RAG retrieval over failed verifier sessions
- ✅ Step 6.3: RAG corpus expansion (10 problems × 5 buggy variants),
  cross-problem retrieval-quality tests, and `RetrievedFailure.problem_id`
  threading

### Upcoming
- ⬜ Step 7: Frontend (Next.js + Monaco)
- ⬜ Step 8: LangGraph orchestration (deferred from Step 6 until
  Step 7 frontend UX clarifies the agent state machine)
- ⬜ Step 9-12: RAG quality evaluation / ML problems / knowledge
  graph / blog / MCP

## License

MIT (LICENSE file to be added).
