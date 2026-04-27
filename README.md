# StudyVerify

Verification-driven AI learning companion.

## Status
🚧 Week 2 / 12 — Solver Agent operational

### What works
- ✅ FastAPI backend skeleton
- ✅ Solver Agent: 3-stage LLM pipeline (analyze → plan → code)
- ✅ DeepSeek V4 Flash integration with retry/backoff
- ✅ Structured logging with token/latency tracking
- ✅ POST /api/v1/solve endpoint (tested with real API)

### Roadmap
- 🔜 Step 2.3: Sandbox self-verification
- ⬜ Step 3: Database + Docker
- ⬜ Step 4: Verifier Agent
- ⬜ ...

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
