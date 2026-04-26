# StudyVerify — Step 1: Project Skeleton Spec

## Goal
Set up a clean Python backend skeleton that runs a "Hello FastAPI" endpoint.
This is the foundation for all subsequent Agent work.

## Tech Stack (DO NOT change without asking)
- Python 3.11 (use `python3.11` explicitly, NOT default `python3`)
- Package manager: **uv** (https://docs.astral.sh/uv/) — install via `pip install uv` if not present
- Web framework: FastAPI
- ASGI server: uvicorn
- Lint/format: ruff
- Type check: mypy (configured but not strict yet)
- Test: pytest

## Directory Structure (create exactly this)

```
studyverify/
├── backend/
│   ├── app/
│   │   ├── __init__.py
│   │   ├── main.py              # FastAPI entry point
│   │   ├── agents/              # Agent modules (empty for now, just __init__.py)
│   │   │   └── __init__.py
│   │   ├── api/
│   │   │   ├── __init__.py
│   │   │   └── routes/
│   │   │       ├── __init__.py
│   │   │       └── health.py    # /health endpoint
│   │   ├── core/
│   │   │   ├── __init__.py
│   │   │   ├── config.py        # Settings via pydantic-settings
│   │   │   └── logging.py       # Basic logging config
│   │   └── schemas/             # Pydantic models (empty for now)
│   │       └── __init__.py
│   ├── tests/
│   │   ├── __init__.py
│   │   └── test_health.py       # Test /health endpoint
│   ├── pyproject.toml           # uv-managed dependencies
│   ├── .python-version          # Pin to 3.11
│   └── README.md                # Backend-specific README
├── docs/
│   └── specs/
│       └── step-01-skeleton.md  # This file (already exists)
├── .gitignore                   # Python + macOS standard
├── CLAUDE.md                    # Project conventions (see below)
└── README.md                    # Top-level project README
```

## Endpoints to Implement

### `GET /health`
Returns:
```json
{
  "status": "ok",
  "service": "studyverify-backend",
  "version": "0.1.0"
}
```

### `GET /`
Returns:
```json
{
  "message": "StudyVerify API. See /docs for OpenAPI spec."
}
```

## Configuration Requirements

`app/core/config.py` should use `pydantic-settings` to load:
- `APP_NAME` (default: "studyverify-backend")
- `APP_VERSION` (default: "0.1.0")
- `LOG_LEVEL` (default: "INFO")
- `ENV` (default: "development")

Settings should be loadable from `.env` file (which is gitignored).

## Test Requirements

`tests/test_health.py` must:
- Use `pytest` and `httpx.AsyncClient` (or `fastapi.testclient.TestClient`)
- Test `GET /health` returns 200 and correct JSON shape
- Test `GET /` returns 200 and the welcome message

## CLAUDE.md Content (project conventions, read by Claude Code every session)

Create `CLAUDE.md` at project root with:
- Project: StudyVerify — Verification-driven AI learning companion
- Python: 3.11 only, managed by uv
- Style: ruff format + ruff check, line length 100
- Imports: use absolute imports from `app.*`
- Commit style: conventional commits (feat:, fix:, docs:, refactor:, test:, chore:)
- Testing: every new feature requires a test; run `pytest -v` before committing
- DO NOT commit: `.env`, `__pycache__`, `.venv`, IDE files

## .gitignore

Standard Python + macOS .gitignore. Must include:
- `__pycache__/`, `*.pyc`
- `.venv/`, `venv/`
- `.env`, `.env.local`
- `.DS_Store`
- `.pytest_cache/`, `.ruff_cache/`, `.mypy_cache/`
- `*.egg-info/`, `dist/`, `build/`

## Top-level README.md

Brief content:
- Project name + tagline ("Verification-driven AI learning companion")
- Status: "🚧 Week 1 / 12 — Skeleton in place"
- Quick start (clone, cd backend, `uv sync`, `uv run uvicorn app.main:app --reload`)
- License: MIT (we'll add LICENSE file later)

## Verification Checklist (Claude Code must verify all pass)

1. `cd backend && uv sync` succeeds, creates `.venv/`
2. `uv run uvicorn app.main:app --reload` starts on port 8000
3. `curl http://localhost:8000/health` returns the expected JSON
4. `curl http://localhost:8000/` returns the welcome message
5. `uv run pytest -v` passes both tests
6. `uv run ruff check .` passes with no errors
7. Browser visit `http://localhost:8000/docs` shows OpenAPI Swagger UI

## What NOT to do (common AI mistakes to avoid)
- DO NOT use `pip` directly — use `uv add` / `uv sync`
- DO NOT use `requirements.txt` — use `pyproject.toml` only
- DO NOT add database, auth, or Agent code — that's later steps
- DO NOT add Docker — that's Step 3
- DO NOT initialize git or make commits — user will do this manually
- DO NOT install global packages — everything in `.venv`

## Out of Scope (explicitly NOT this step)
- Database (PostgreSQL, Redis, Chroma) → Step 3
- Frontend (Next.js) → Step 7
- Any Agent logic → Step 2 onward
- Authentication / users → Step 4
- Docker → Step 3