# StudyVerify

Verification-driven AI learning companion.

## Status

🚧 **Week 3 / 12 — Persistence layer + REST API operational**

### What works
- ✅ FastAPI backend with `/health`, `/health/db`, 
  `/api/v1/solve`, `/api/v1/sessions/{id}`, `/api/v1/sessions`
- ✅ Solver Agent: 3-stage LLM pipeline + sandbox self-verification
- ✅ DeepSeek V4 Flash integration with retry/backoff
- ✅ Postgres + Redis via Docker Compose (Makefile-wrapped)
- ✅ SQLAlchemy 2.0 async + Alembic migrations (incl. 3-stage 
  backfill pattern)
- ✅ 3-layer architecture: Route → Service → Repository + Agent
- ✅ Every solve invocation persisted; full session history queryable
- ✅ 76+ tests across unit (mocked/SQLite) and integration 
  (real PG + real DeepSeek API) layers

### Architecture highlights
- Code/data separation in sandbox (static wrapper + stdin JSON)
- Constructor-injected agents and DB sessions for testability
- Layered sandbox strategy (subprocess now → Docker for Verifier later)
- Async runner via asyncio.to_thread to keep FastAPI worker responsive
- Explicit transaction boundaries (no framework-level auto-commit)
- Schema-isolated integration tests for clean parallel runs
- Param-injected sessions allow stateless service shells per-request

### Roadmap
- 🔜 Step 3.4: FastAPI Dockerization (full-stack `make compose-up`)
- ⬜ Step 4: Verifier Agent (validates student code against ground truth)
- ⬜ Step 5: Hint Agent + LangGraph orchestration
- ⬜ Step 6: Multi-model gateway (Anthropic fallback) + RAG hint retrieval
- ⬜ Step 7: Frontend (Next.js + Monaco)
- ⬜ Step 8-12: ML problems / evaluation / knowledge graph / blog / MCP

## Quick Start

```bash
git clone <repo-url>
cd studyverify/backend
uv sync
uv run uvicorn app.main:app --reload
```

Then visit:
- http://localhost:8000/ — welcome
- http://localhost:8000/health — health check
- http://localhost:8000/docs — OpenAPI Swagger UI

## Quick start with Docker (Postgres + Redis)

```bash
cp .env.docker.example .env.docker   # then edit; replace passwords
make compose-up                       # start Postgres + Redis
make smoke-all                        # verify connectivity
```

See [docs/runbook-docker.md](docs/runbook-docker.md) for prerequisites (brew install libpq redis), daily commands, and troubleshooting.

## License

MIT (LICENSE file to be added).
