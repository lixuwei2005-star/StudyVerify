# StudyVerify — Step 3.3: SolverAgent Persistence Spec

## Goal
Persist every `/api/v1/solve` invocation into the `solver_sessions` 
table created in 3.2. Add a query endpoint to read past sessions. 
Cleanly factor out a Service layer (orchestration) and a Repository 
layer (DB access) so SolverAgent itself stays storage-agnostic.

This step requires extending the schema (add `retry_used` and 
`total_latency_ms`) via an incremental Alembic migration — the 
first real exercise of "add a column to an existing table."

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│  POST /api/v1/solve                                         │
│       ↓                                                     │
│  api/routes/solver.py     ← thin: parse, call service       │
│       ↓                                                     │
│  services/solver_service.py                                 │
│   .solve_and_persist(input, session)                        │
│       ├─ Track start time for end-to-end latency            │
│       ├─ agent.solve(input) → SolverOutput                  │
│       ├─ Build dict for DB row (Pydantic → ORM data)        │
│       ├─ Add total_latency_ms measured by service           │
│       ├─ repository.create(...)                             │
│       ├─ session.commit() ← explicit, per Step 3.2 contract │
│       └─ return (session_id, solver_output)                 │
│       ↓                                                     │
│  repositories/solver_repository.py                          │
│   .create(data, session) → SolverSession ORM                │
│   .get_by_id(id, session) → SolverSession | None            │
│   .list_by_problem(problem_id, session, limit, offset)      │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│  GET /api/v1/sessions/{id}                                  │
│       ↓                                                     │
│  api/routes/sessions.py                                     │
│       ↓                                                     │
│  repository.get_by_id(id, session)                          │
│       ↓                                                     │
│  Return SolverSessionOut (Pydantic)                         │
│   404 if None                                               │
└─────────────────────────────────────────────────────────────┘
```

## Scope

### 3.3.a — Schema extension
- Add `retry_used: bool` and `total_latency_ms: int` to:
  - `SolverSession` ORM model (`db/models.py`)
- Add `retry_used: bool` to `SolverOutput` Pydantic schema 
  (`agents/solver/schemas.py`)
- Generate incremental migration `0002_add_retry_metrics`
- Modify SolverAgent to track and return `retry_used`
- Measure `total_latency_ms` in the Service layer and persist it 
  directly through the Repository

### 3.3.b — Service + Repository
- Create `app/services/solver_service.py` (orchestration)
- Create `app/repositories/solver_repository.py` (DB access)
- Pydantic models for API I/O: `app/schemas/solver_session.py` 
  (`SolverSessionOut`)
- Wire dependency injection: route receives Service via 
  `Depends(get_solver_service)`

### 3.3.c — Route changes
- Modify existing `POST /api/v1/solve`: response now includes 
  `session_id` (UUID); shape becomes `{"session_id": ..., "output": SolverOutput}`
- New `GET /api/v1/sessions/{id}` returns full `SolverSessionOut` or 404
- New `GET /api/v1/sessions?problem_id=...&limit=10&offset=0` returns 
  paginated list of `SolverSessionOut`

## Out of Scope
- ❌ Verifier-related schema → Step 4
- ❌ User/auth tables → not in this project's scope
- ❌ Pagination cursors → simple offset/limit is fine
- ❌ DELETE endpoints → not needed
- ❌ FastAPI Dockerization → Step 3.4

## Files to Create / Modify

### New files
- `backend/app/services/__init__.py`
- `backend/app/services/solver_service.py`
- `backend/app/repositories/__init__.py`
- `backend/app/repositories/solver_repository.py`
- `backend/app/schemas/solver_session.py`
- `backend/app/api/routes/sessions.py`
- `backend/alembic/versions/<hash>_add_retry_metrics.py` (autogen)
- `backend/tests/services/__init__.py`
- `backend/tests/services/test_solver_service.py` (mocked agent + 
  repo)
- `backend/tests/repositories/__init__.py`
- `backend/tests/repositories/test_solver_repository.py` (SQLite + PG)
- `backend/tests/api/__init__.py`
- `backend/tests/api/test_solve_endpoint.py` (TestClient + 
  dependency override)
- `backend/tests/api/test_sessions_endpoint.py`

### Modified files
- `backend/app/db/models.py` — add `retry_used` + `total_latency_ms` 
  columns (both `nullable=False`, but `retry_used` has 
  `server_default=sa.false()`, `total_latency_ms` no default — 
  service MUST provide it)
- `backend/app/agents/solver/schemas.py` — add `retry_used` to 
  `SolverOutput`
- `backend/app/agents/solver/agent.py` — track `retry_used` (already 
  internal); populate the new SolverOutput field. Do NOT compute 
  `total_latency_ms` in the agent — Service owns end-to-end latency.
- `backend/app/api/routes/solver.py` — switch from direct agent 
  injection to `Depends(get_solver_service)`; response shape changes 
  to `{"session_id": ..., "output": SolverOutput}`
- `backend/app/main.py` — include `sessions` router with the same 
  `/api/v1` prefix owned by main.py:
  ```python
  # app/main.py
  app.include_router(solver.router, prefix="/api/v1")
  app.include_router(sessions.router, prefix="/api/v1")  # ← give sessions /api/v1 too
  app.include_router(health_db.router)  # ← /health/db is not under /api/v1
  ```
- `backend/tests/agents/test_solver.py` — adjust assertions for 
  the new SolverOutput field (`retry_used`)
- `backend/tests/agents/test_solver_integration.py` — assert new 
  `retry_used` field is populated correctly in real-API runs

## Schema Extension Details

### Model column additions

```python
# db/models.py additions to SolverSession

retry_used: Mapped[bool] = mapped_column(
    Boolean, 
    nullable=False, 
    server_default=sa.false(),  # default False at DB level — old code 
                                 # paths can omit it; service should 
                                 # always set it explicitly
    index=False,
)

total_latency_ms: Mapped[int] = mapped_column(
    Integer, 
    nullable=False,
    # No model-level server_default — service layer computes and provides
)
```

### Pydantic additions

```python
# agents/solver/schemas.py — add to SolverOutput

retry_used: bool = Field(
    default=False,
    description="True iff the code-generation step was retried due "
                "to sandbox failure",
)
# total_latency_ms is NOT in SolverOutput. Service layer measures 
# end-to-end latency (including DB write) and supplies it directly 
# to the repository.
```

### Migration generation

```bash
cd backend
uv run alembic revision --autogenerate -m "add retry metrics to solver_sessions"
```

**Manual review of generated migration is mandatory.** Confirm:
- `op.add_column('solver_sessions', sa.Column('retry_used', sa.Boolean(), 
   nullable=False, server_default=sa.false()))`
- `total_latency_ms` uses the 3-stage backfill pattern below, not a 
  direct non-null `add_column`
- `downgrade()` has `op.drop_column(...)` for both
- No spurious changes to other columns
- `down_revision` points to the previous migration's hash

⚠️ **Migration safety: 3-stage backfill pattern**

Even though the table is currently empty in production-equivalent 
state, the migration MUST be safe for populated tables (this is 
an industry-standard discipline). Pattern for `total_latency_ms`:

```python
# upgrade()
op.add_column(
    "solver_sessions", 
    sa.Column("total_latency_ms", sa.Integer(), nullable=True)
)
op.execute(
    "UPDATE solver_sessions SET total_latency_ms = 0 "
    "WHERE total_latency_ms IS NULL"
)
op.alter_column("solver_sessions", "total_latency_ms", nullable=False)
```

For `retry_used`, simpler — server_default=False covers existing 
rows automatically:

```python
op.add_column(
    "solver_sessions", 
    sa.Column(
        "retry_used", sa.Boolean(), 
        nullable=False, 
        server_default=sa.false()
    )
)
```

After autogen produces the migration, manually edit it to use this 
3-stage pattern for `total_latency_ms` (autogen produces a single 
add_column with nullable=False which would fail on populated tables).

The downgrade simply drops both columns.

## Repository Pattern

```python
# repositories/solver_repository.py

from uuid import UUID
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.models import SolverSession

class SolverRepository:
    """Pure DB access for solver_sessions table.
    
    Does NOT know about Agent, Service, or Pydantic schemas.
    Receives plain dicts / primitives, returns ORM rows.
    """

    async def create(
        self,
        session: AsyncSession,
        *,
        problem_id: str,
        problem_text: str,
        test_cases: list[dict],
        analysis: str,
        plan_steps: list[dict],
        code: str,
        explanation: str,
        verified: bool,
        test_results: list[dict],
        confidence: float,
        retry_used: bool,
        total_latency_ms: int,
    ) -> SolverSession:
        row = SolverSession(
            problem_id=problem_id,
            problem_text=problem_text,
            test_cases=test_cases,
            analysis=analysis,
            plan_steps=plan_steps,
            code=code,
            explanation=explanation,
            verified=verified,
            test_results=test_results,
            confidence=confidence,
            retry_used=retry_used,
            total_latency_ms=total_latency_ms,
        )
        session.add(row)
        await session.flush()  # populate row.id without committing
        return row

    async def get_by_id(
        self, session: AsyncSession, session_id: UUID
    ) -> SolverSession | None:
        result = await session.execute(
            select(SolverSession).where(SolverSession.id == session_id)
        )
        return result.scalar_one_or_none()

    async def list_by_problem(
        self,
        session: AsyncSession,
        problem_id: str,
        limit: int = 10,
        offset: int = 0,
    ) -> list[SolverSession]:
        result = await session.execute(
            select(SolverSession)
            .where(SolverSession.problem_id == problem_id)
            .order_by(SolverSession.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(result.scalars().all())

    async def count_by_problem(
        self, session: AsyncSession, problem_id: str
    ) -> int:
        """Count sessions for a given problem_id (for pagination total)."""
        result = await session.execute(
            select(func.count())
            .select_from(SolverSession)
            .where(SolverSession.problem_id == problem_id)
        )
        return result.scalar_one()
```

Key design choices:
- **Stateless class** — no instance state; safe to share. Could be 
  a module of free functions instead, but a class lets us mock 
  cleanly via constructor injection in service tests.
- **Keyword-only args in `create`** — prevents accidental positional 
  mistakes when many fields share the same type.
- **`session.flush()` not `session.commit()`** — repository never 
  commits; commit is the service's responsibility (explicit 
  transaction boundary, per Step 3.2 contract).
- **`scalar_one_or_none`** — explicit "0 or 1 row" semantic; raises 
  if multiple rows match (which would indicate a bug, since `id` 
  is PK).

## Service Layer

```python
# services/solver_service.py

import time
from sqlalchemy.ext.asyncio import AsyncSession
from app.agents.solver.agent import SolverAgent
from app.agents.solver.schemas import SolverInput, SolverOutput
from app.repositories.solver_repository import SolverRepository
from app.db.models import SolverSession

class SolverService:
    def __init__(
        self, agent: SolverAgent, repository: SolverRepository
    ):
        self.agent = agent
        self.repository = repository

    async def solve_and_persist(
        self, session: AsyncSession, solver_input: SolverInput
    ) -> tuple[SolverSession, SolverOutput]:
        """Solve a problem and persist the result.
        
        Returns (db_row, solver_output). The output contains retry_used 
        because the agent populates it. The service measures 
        total_latency_ms for persistence. The db_row provides the 
        persisted id and created_at.
        """
        start = time.perf_counter()
        
        output = await self.agent.solve(solver_input)
        
        total_latency_ms = int((time.perf_counter() - start) * 1000)
        
        row = await self.repository.create(
            session,
            problem_id=output.problem_id,
            problem_text=solver_input.problem_text,
            test_cases=[tc.model_dump() for tc in solver_input.test_cases],
            analysis=output.analysis,
            plan_steps=[ps.model_dump() for ps in output.plan_steps],
            code=output.code,
            explanation=output.explanation,
            verified=output.verified,
            test_results=[tr.model_dump() for tr in output.test_results],
            confidence=output.confidence,
            retry_used=output.retry_used,
            total_latency_ms=total_latency_ms,
        )
        await session.commit()  # explicit, end of business transaction
        await session.refresh(row)  # populate created_at, id
        return row, output
```

Notes:
- **Pydantic model_dump()** for nested types — JSONB columns store 
  them as plain JSON arrays of dicts
- **Service owns commit** — Repository never calls commit; this 
  matches Step 3.2's "no auto-commit in dependency" rule
- **`session.refresh()`** after commit pulls server-generated 
  defaults (`created_at`, `id`) back into the Python object so 
  the response can include them

## API Schemas (`app/schemas/solver_session.py`)

```python
from datetime import datetime
from uuid import UUID
from pydantic import BaseModel, Field
from app.agents.solver.schemas import SolverOutput

class SolverSessionOut(BaseModel):
    """API representation of a SolverSession DB row.
    
    Pydantic v2 with `from_attributes=True` lets us construct from 
    SQLAlchemy ORM objects via .model_validate(row).
    """
    model_config = {"from_attributes": True}

    id: UUID
    problem_id: str
    problem_text: str
    test_cases: list[dict]
    analysis: str
    plan_steps: list[dict]
    code: str
    explanation: str
    verified: bool
    test_results: list[dict]
    confidence: float  # cast from Decimal at validation; float precision 
                       # is sufficient for the [0.0, 1.0] range. Pydantic 
                       # handles Decimal→float automatically when 
                       # from_attributes=True.
    retry_used: bool
    total_latency_ms: int
    created_at: datetime


class SolveResponse(BaseModel):
    """Response shape for POST /api/v1/solve."""
    session_id: UUID
    output: SolverOutput   # full nested schema for OpenAPI docs


class SessionListResponse(BaseModel):
    items: list[SolverSessionOut]
    total: int  # for pagination UI; from a separate COUNT query
    limit: int
    offset: int
```

## Route Changes

### `app/api/routes/solver.py` (modified)

```python
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.solver import SolverError
from app.agents.solver.schemas import SolverInput
from app.db.session import get_db_session
from app.services.solver_service import SolverService
from app.schemas.solver_session import SolveResponse
# Use the existing get_solver_agent() factory; new factory below
from app.dependencies import get_solver_service

# routes/solver.py — DO NOT include /api/v1 prefix here; main.py owns it
router = APIRouter(tags=["solver"])

@router.post("/solve", response_model=SolveResponse)
async def solve(
    solver_input: SolverInput,
    service: SolverService = Depends(get_solver_service),
    session: AsyncSession = Depends(get_db_session),
):
    try:
        row, output = await service.solve_and_persist(session, solver_input)
    except SolverError as e:
        raise HTTPException(status_code=502, detail=str(e))
    # ... existing LLMTimeout / LLMError mappings unchanged
    
    return SolveResponse(
        session_id=row.id,
        output=output,
    )
```

### `app/api/routes/sessions.py` (new)

```python
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db_session
from app.repositories.solver_repository import SolverRepository
from app.schemas.solver_session import SolverSessionOut, SessionListResponse
from app.dependencies import get_solver_repository

# routes/sessions.py — DO NOT include /api/v1 prefix; main.py prepends it
router = APIRouter(prefix="/sessions", tags=["sessions"])

@router.get("/{session_id}", response_model=SolverSessionOut)
async def get_session(
    session_id: UUID,
    session: AsyncSession = Depends(get_db_session),
    repository: SolverRepository = Depends(get_solver_repository),
):
    row = await repository.get_by_id(session, session_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return SolverSessionOut.model_validate(row)


@router.get("", response_model=SessionListResponse)
async def list_sessions(
    problem_id: str = Query(..., description="Filter by problem_id"),
    limit: int = Query(10, ge=1, le=100),
    offset: int = Query(0, ge=0),
    session: AsyncSession = Depends(get_db_session),
    repository: SolverRepository = Depends(get_solver_repository),
):
    items = await repository.list_by_problem(
        session, problem_id, limit=limit, offset=offset
    )
    total = await repository.count_by_problem(session, problem_id)
    return SessionListResponse(
        items=[SolverSessionOut.model_validate(i) for i in items],
        total=total,
        limit=limit,
        offset=offset,
    )
```

## Dependency Injection (`app/dependencies.py` — new)

Centralize the factory functions to avoid duplicating across routes:

```python
from functools import lru_cache
from fastapi import Depends
from app.agents.solver.agent import SolverAgent
from app.agents.solver.schemas import (...)  # existing factory
from app.repositories.solver_repository import SolverRepository
from app.services.solver_service import SolverService

@lru_cache
def get_solver_repository() -> SolverRepository:
    return SolverRepository()  # stateless, safe to cache

# get_solver_agent already exists from Step 2 — reuse it

def get_solver_service(
    agent: SolverAgent = Depends(get_solver_agent),
    repository: SolverRepository = Depends(get_solver_repository),
) -> SolverService:
    return SolverService(agent=agent, repository=repository)
```

## Test Strategy

### Unit tests
- **`test_solver_repository.py`** — SQLite in-memory + 
  schema-isolated PG. Test create, get_by_id (found + 404), 
  list_by_problem (with pagination)
- **`test_solver_service.py`** — Mock both `SolverAgent` and 
  `SolverRepository` (no real DB or LLM). Verify the orchestration: 
  agent called once, repo.create called with correct kwargs, 
  session.commit called exactly once. Test that exceptions in 
  agent propagate without committing.

### Integration tests (real PG, gated by marker)
- **`test_solve_endpoint.py`** — Full TestClient flow:
  - POST /api/v1/solve with mock agent (override 
    `get_solver_agent`) → assert 200, `session_id` returned, row 
    exists in DB
  - GET /api/v1/sessions/{id} returns the row
  - DB cleanup via schema isolation

- **`test_sessions_endpoint.py`** — Direct DB seeding (insert via 
  repository fixture, query via TestClient):
  - GET /api/v1/sessions/{id} → 200 with full data
  - GET /api/v1/sessions/{nonexistent_uuid} → 404
  - GET /api/v1/sessions?problem_id=X with paginated data → 
    correct items, total, limit, offset

### Existing test updates
- `test_solver.py`: existing tests that assert SolverOutput must 
  also account for the new field in returned objects (just update 
  expected dicts to include `retry_used: False`)

### TestClient + dependency override pattern

```python
# tests/conftest.py addition

@pytest.fixture
def app_with_overrides(test_session_factory):
    """FastAPI app with DB session overridden. 
    
    Saves and restores existing dependency_overrides to avoid 
    clobbering overrides set by other fixtures.
    """
    from app.main import app
    from app.db.session import get_db_session
    
    old_overrides = app.dependency_overrides.copy()
    
    async def override_get_session():
        async with test_session_factory() as session:
            yield session
    
    app.dependency_overrides[get_db_session] = override_get_session
    yield app
    app.dependency_overrides = old_overrides  # restore, do NOT clear()


@pytest.fixture
def client(app_with_overrides):
    """Sync TestClient. Uses `with` context manager to trigger 
    FastAPI lifespan (engine.dispose() etc.)."""
    from fastapi.testclient import TestClient
    with TestClient(app_with_overrides) as c:
        yield c
```

⚠️ Note: fixtures are synchronous (`def`, not `async def`). 
pytest-asyncio handles cooperation with async tests.

## Verification Checklist

1. `uv run ruff check .` clean
2. `uv run alembic check` — no drift after model + migration applied
3. New migration `0002_<hash>_add_retry_metrics`:
   - Manually reviewed (`retry_used` add_column uses `server_default`, 
     `total_latency_ms` uses 3-stage backfill, proper down_revision, 
     downgrade drops both)
   - `uv run alembic upgrade head` succeeds
   - `\d solver_sessions` shows 13 columns now
   - `uv run alembic downgrade -1` cleanly drops the columns
   - `uv run alembic upgrade head` re-applies cleanly
4. Unit tests:
   - `pytest tests/repositories/ -v -m "not integration"` passes 
     (SQLite-based)
   - `pytest tests/services/ -v` passes (mocked, no DB or LLM)
   - `pytest tests/agents/ -v -m "not integration"` still passes 
     (existing solver tests adjusted for new fields)
5. Integration tests:
   - `pytest tests/repositories/ -v -m integration` passes (real PG)
   - `pytest tests/api/ -v -m integration` passes (TestClient + 
     real PG with override)
6. End-to-end smoke:
   - `make compose-up`
   - `uv run uvicorn app.main:app --reload`
   - `curl -X POST http://localhost:8000/api/v1/solve -d "$(jq '.[0]' backend/tests/agents/fixtures/sample_problems.json)" -H "Content-Type: application/json"` 
     returns `{"session_id": "...", "output": {...}}`
   - `curl http://localhost:8000/api/v1/sessions/{that-uuid}` 
     returns the full row
   - `curl "http://localhost:8000/api/v1/sessions?problem_id=py-001-sum-list&limit=5"` 
     returns the list
   - Verify in psql: `SELECT id, problem_id, verified, retry_used, 
     total_latency_ms FROM solver_sessions ORDER BY created_at DESC 
     LIMIT 5;` — see the row(s) just inserted
7. Full regression: `pytest -v -m "not integration"` — all green 
   (Step 2 + Step 3.2 + Step 3.3 unit tests)

## What NOT to do
- DO NOT add `retry_used` / `total_latency_ms` as `nullable=True` 
  in the model — service layer must always supply them
- DO NOT call `session.commit()` from the Repository — Service owns 
  transaction boundaries
- DO NOT include the user's actual problem text in error messages 
  (could leak student data in logs) — use `problem_id` only
- DO NOT skip the `session.refresh(row)` after commit — without it, 
  `row.created_at` may be None on the response
- DO NOT couple SolverAgent to AsyncSession — the agent's signature 
  is `solve(input) -> output`, period. Service does the persistence.
- DO NOT regenerate the migration if autogen looks weird — first 
  inspect why; usually it's a model field type mismatch
- DO NOT use `APIRouter(prefix="/api/v1")` in route modules. main.py 
  owns the `/api/v1` prefix. Route modules use just `/solve` or 
  `/sessions` + sub-paths. This avoids `/api/v1/api/v1/...` 
  double-prefix bugs.
- DO NOT add a non-null column directly. Use 3-stage backfill: add 
  nullable → backfill UPDATE → alter to nullable=False. Even if the 
  table is currently empty, write the migration as if it has data; 
  future-proofing is free now, expensive later.
- DO NOT type API response fields as `dict` when a Pydantic model 
  exists for that data. You lose OpenAPI docs and validation.
- DO NOT measure latency in two layers. Pick one. We measure in 
  Service for end-to-end view. Agent only tracks retry_used.
- DO NOT `clear()` dependency_overrides in test fixtures. Save and 
  restore — `clear()` can wipe overrides set by parallel fixtures.

## Estimated Time
- Schema extension + migration round-trip: 30 min
- Repository + tests: 45 min
- Service + tests: 30 min
- Routes (modify solve, new sessions): 30 min
- TestClient + override pattern: 45 min (this is the trickiest)
- End-to-end smoke: 20 min
- Debug buffer: 30-60 min
- **Total: ~3.5-4.5 hours active work**
