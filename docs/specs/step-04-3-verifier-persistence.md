# StudyVerify - Step 4.3: Entry Function + Verifier Persistence Spec

## Goal
Prepare persisted solver sessions for student verification, then wrap
VerifierAgent (Step 4.2) in a service layer with database persistence
and FastAPI routes. This step mirrors the architectural pattern of
Step 3.3 (Solver persistence): Repository -> Service -> Routes with
parameter-injected sessions and explicit transaction boundaries.

Step 4.3 is split into two gated sub-steps:

- **4.3.a Add `entry_function` to `solver_sessions`**: schema extension,
  backfill, and solver-path threading.
- **4.3.b Verifier persistence + routes**: new verifier table,
  repository, service, API schemas, and routes.

4.3.a must complete before 4.3.b begins. The verifier service cannot
compose `VerifierInput` from a persisted solver row until
`SolverSession.entry_function` exists and is populated.

After this step:
- POST `/api/v1/verify` accepts `{solver_session_id, student_code}`
- Verifier session persists to `verifier_sessions` table with FK to
  `solver_sessions`
- GET endpoints retrieve past verifier sessions

## Architecture

```
4.3.a
POST /api/v1/solve
  -> SolverAgent extracts entry_function from generated code
  -> SolverOutput carries entry_function
  -> SolverService persists entry_function on solver_sessions

4.3.b
POST /api/v1/verify
  -> api/routes/verify.py     thin: parse, call service
  -> services/verifier_service.py
     .verify_and_persist(session, solver_session_id, student_code)
      - Fetch solver_session by id (404 if not found)
      - Compose VerifierInput from solver row + student_code
      - agent.verify(input) -> VerifierOutput
      - Build dict for DB row (RedactedTestResult never gains expected)
      - repository.create(...)
      - session.commit()
      - return (db_row, verifier_output)
  -> repositories/verifier_repository.py
     .create / .get_by_id / .list_by_solver_session / .count_by_solver_session
```

## Scope
- Extend `solver_sessions` with `entry_function`
- Thread `entry_function` through SolverOutput, SolverRepository,
  SolverService, and SolverSessionOut
- Add new `verifier_sessions` table with FK to solver_sessions
- Add verifier repository / service / routes following 3.3 patterns
- Add Pydantic API schemas: VerifyRequest, VerifyResponse,
  VerifierSessionOut, VerifierSessionListResponse

## Out of Scope
- End-to-end through compose stack - Step 4.4
- README updates - Step 4.4
- Frontend integration - Step 7
- Multi-turn verifier conversations - Step 5 territory

## Files to Create / Modify

### New - 4.3.a
- `backend/app/agents/solver/extraction.py` - shared entry-function
  extraction helper
- `backend/alembic/versions/<hash>_add_entry_function_to_solver_sessions.py`

### Modified - 4.3.a
- `backend/app/db/models.py` - add `entry_function` column to SolverSession
- `backend/app/agents/solver/schemas.py` - add `entry_function` to SolverOutput
- `backend/app/agents/solver/agent.py` - populate `entry_function` in output
- `backend/app/repositories/solver_repository.py` - accept `entry_function`
  in create
- `backend/app/services/solver_service.py` - pass `output.entry_function`
  to repo
- `backend/app/schemas/solver_session.py` - add `entry_function` to
  SolverSessionOut

### New - 4.3.b
- `backend/alembic/versions/<hash>_add_verifier_sessions.py`
- `backend/app/repositories/verifier_repository.py`
- `backend/app/services/verifier_service.py`
- `backend/app/schemas/verifier_session.py` (API schemas)
- `backend/app/api/routes/verify.py`
- `backend/tests/repositories/test_verifier_repository.py`
- `backend/tests/repositories/test_verifier_repository_integration.py`
- `backend/tests/services/test_verifier_service.py`
- `backend/tests/api/test_verify_endpoint.py`

### Modified - 4.3.b
- `backend/app/db/models.py` - add VerifierSession ORM model
- `backend/app/dependencies.py` - add get_verifier_repository,
  get_verifier_service factories
- `backend/app/main.py` - include verify router
- `backend/app/api/routes/sessions.py` - add
  GET `/api/v1/sessions/{solver_id}/verifier-sessions` endpoint

## 4.3.a - Pre-implementation: Schema Extension on solver_sessions

### Why This Comes First

`VerifierInput` requires `entry_function`:

```python
class VerifierInput(BaseModel):
    problem_id: str
    problem_text: str
    entry_function: str
    test_cases: list[TestCase]
    student_code: str
```

The current solver table persists the generated code and test cases, but
does not persist the function name students must implement. Step 4.3.b
must not ask the client to provide `entry_function` in VerifyRequest,
because a client-supplied function name can drift from the original
solver output.

### Shared Extraction Helper

Move the existing SolverAgent extraction logic into a shared helper:

```python
# app/agents/solver/extraction.py

import re

_DEF_PATTERN = re.compile(r"^def\s+([A-Za-z_]\w*)\s*\(", re.MULTILINE)


class EntryFunctionExtractionError(ValueError):
    pass


def extract_entry_function(code: str, problem_id: str) -> str:
    match = _DEF_PATTERN.search(code.lstrip("\ufeff"))
    if not match:
        raise EntryFunctionExtractionError(
            f"problem_id={problem_id}: no top-level function definition found"
        )
    return match.group(1)
```

Then update `SolverAgent._extract_entry_function` to delegate to this
helper, preserving the existing SolverError behavior. The migration also
imports the same helper. This avoids duplicated regex logic between
runtime code and backfill code.

### Migration: add entry_function to solver_sessions

Migration name: `add entry_function to solver_sessions`

Use the populated-table 3-stage migration pattern from Step 3.3:

1. **Stage 1: add nullable column**
   - `entry_function VARCHAR(128) NULL`
2. **Stage 2: backfill**
   - Use Alembic Python with `op.get_bind()` / `op.execute()` to read
     each row's `code`, call `extract_entry_function(code, problem_id)`,
     and update `entry_function`.
   - If extraction fails for a row, log a warning and leave it NULL.
3. **Stage 3: conditionally enforce NOT NULL**
   - Count rows where `entry_function IS NULL`.
   - If the count is zero, run `ALTER COLUMN entry_function SET NOT NULL`.
   - If any row remains NULL, the migration must NOT enforce NOT NULL.
     Document the failed row IDs in logs and require manual fixup before
     rerunning/enforcing the constraint.

Concrete migration body:

```python
"""add entry_function to solver_sessions"""

from __future__ import annotations

import logging
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

from app.agents.solver.extraction import (
    EntryFunctionExtractionError,
    extract_entry_function,
)


revision: str = "<new_revision>"
down_revision: Union[str, Sequence[str], None] = "d3bd309a15f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

logger = logging.getLogger("alembic.entry_function_backfill")


def upgrade() -> None:
    op.add_column(
        "solver_sessions",
        sa.Column("entry_function", sa.String(length=128), nullable=True),
    )

    bind = op.get_bind()
    rows = bind.execute(
        sa.text("SELECT id, problem_id, code FROM solver_sessions")
    ).mappings()

    for row in rows:
        try:
            entry_function = extract_entry_function(
                row["code"],
                row["problem_id"],
            )
        except EntryFunctionExtractionError as exc:
            logger.warning(
                "entry_function backfill skipped id=%s problem_id=%s error=%s",
                row["id"],
                row["problem_id"],
                exc,
            )
            continue

        op.execute(
            sa.text(
                """
                UPDATE solver_sessions
                SET entry_function = :entry_function
                WHERE id = :id
                """
            ).bindparams(entry_function=entry_function, id=row["id"])
        )

    null_count = bind.execute(
        sa.text(
            "SELECT count(*) FROM solver_sessions "
            "WHERE entry_function IS NULL"
        )
    ).scalar_one()

    if null_count == 0:
        op.alter_column(
            "solver_sessions",
            "entry_function",
            existing_type=sa.String(length=128),
            nullable=False,
        )
    else:
        logger.warning(
            "entry_function remains NULL for %s solver_sessions rows; "
            "manual fixup required before NOT NULL can be enforced",
            null_count,
        )


def downgrade() -> None:
    op.drop_column("solver_sessions", "entry_function")
```

Note: If the migration leaves any NULL values, the ORM should not be
deployed with `nullable=False` until the data is fixed and the constraint
is enforced. In a clean dev/test database, the backfill should succeed and
the final ORM target is non-nullable.

### Solver Path Changes

`app/db/models.py`:

```python
class SolverSession(Base):
    __tablename__ = "solver_sessions"

    # existing fields...
    entry_function: Mapped[str] = mapped_column(String(128), nullable=False)
```

`app/agents/solver/schemas.py`:

```python
class SolverOutput(BaseModel):
    problem_id: str
    entry_function: str = Field(
        description="Python function name students must implement"
    )
    analysis: str = Field(description="Restatement of what's being asked")
    # existing fields...
```

`app/agents/solver/agent.py`:

```python
entry_function = self._extract_entry_function(code, pid)
sandbox_result = await self._run_sandbox(code, entry_function, test_payload)

# retry may replace code and entry_function
if self._should_retry(sandbox_result):
    retry_used = True
    code, explanation = await self._code_retry(...)
    entry_function = self._extract_entry_function(code, pid)
    sandbox_result = await self._run_sandbox(code, entry_function, test_payload)

output = SolverOutput(
    problem_id=pid,
    entry_function=entry_function,
    analysis=analysis,
    # existing fields...
)
```

`app/repositories/solver_repository.py`:

```python
async def create(
    self,
    session: AsyncSession,
    *,
    problem_id: str,
    problem_text: str,
    entry_function: str,
    test_cases: list[dict],
    # existing args...
) -> SolverSession:
    row = SolverSession(
        problem_id=problem_id,
        problem_text=problem_text,
        entry_function=entry_function,
        test_cases=test_cases,
        # existing fields...
    )
```

`app/services/solver_service.py`:

```python
row = await self.repository.create(
    session,
    problem_id=output.problem_id,
    problem_text=solver_input.problem_text,
    entry_function=output.entry_function,
    test_cases=[tc.model_dump() for tc in solver_input.test_cases],
    # existing fields...
)
```

`app/schemas/solver_session.py`:

```python
class SolverSessionOut(BaseModel):
    model_config = {"from_attributes": True}

    id: UUID
    problem_id: str
    problem_text: str
    entry_function: str
    test_cases: list[TestCase]
    # existing fields...
```

### 4.3.a Verification Gate

Before starting 4.3.b:

1. Migration round-trip: upgrade -> downgrade -> upgrade clean.
2. Existing solver repository/service/API tests updated for
   `entry_function` and passing.
3. Full non-integration regression passes.
4. `SolverAgent.solve()` output successfully extracts `entry_function`
   for all 3 fixture problems.
5. Backfill verification:

```sql
SELECT id, problem_id FROM solver_sessions WHERE entry_function IS NULL;
```

Expected: empty result set before deploying the non-null ORM model.

## 4.3.b - Verifier Database Schema

`verifier_sessions` table:

| Column | Type | Notes |
|---|---|---|
| id | UUID | PK |
| solver_session_id | UUID | FK -> solver_sessions(id) ON DELETE RESTRICT |
| student_code | TEXT | NOT NULL |
| verified | BOOLEAN | NOT NULL |
| status | VARCHAR(16) | "all_passed" / "some_failed" / "error" / "timeout" |
| pass_count | INTEGER | NOT NULL DEFAULT 0 |
| fail_count | INTEGER | NOT NULL DEFAULT 0 |
| test_results | JSONB | List of RedactedTestResult dicts (NO expected field) |
| diagnosis | TEXT | Default empty string; LLM feedback when verified=False |
| sandbox_error | TEXT | NULL when no infra error |
| total_latency_ms | INTEGER | NOT NULL - service-measured verifier execution latency |
| created_at | TIMESTAMPTZ | NOT NULL DEFAULT now() |

Indexes:
- `ix_verifier_sessions_solver_session_id` on solver_session_id
  (for list_by_solver_session)
- `ix_verifier_sessions_created_at` on created_at (for ORDER BY)
- `ix_verifier_sessions_verified` on verified (analytics queries:
  success rate per problem)

FK behavior:
- `ON DELETE RESTRICT`: cannot delete a solver_session if any
  verifier_session references it. This protects against accidental
  cascade deletes destroying student work history.

Status CHECK constraint:

```python
op.create_check_constraint(
    "ck_verifier_sessions_status_valid",
    "verifier_sessions",
    "status IN ('all_passed', 'some_failed', 'error', 'timeout')",
)
```

The Pydantic `SandboxStatus` literal already constrains the type at the
application layer, but a DB-level CHECK provides defense in depth against
direct SQL writes (for example, a future admin script bypassing the ORM).
The CHECK is cheap and matches the `SandboxStatus` literal verbatim.

## ORM Model

```python
# app/db/models.py - append to existing file

class VerifierSession(Base):
    __tablename__ = "verifier_sessions"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True, native_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    solver_session_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True, native_uuid=True),
        ForeignKey("solver_sessions.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    student_code: Mapped[str] = mapped_column(Text, nullable=False)
    verified: Mapped[bool] = mapped_column(Boolean, nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    pass_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=sa.text("0")
    )
    fail_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=sa.text("0")
    )
    test_results: Mapped[list] = mapped_column(JSONType, nullable=False)
    diagnosis: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=sa.text("''")
    )
    sandbox_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    total_latency_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        index=True,
    )
```

Use the existing `JSONType` alias from `models.py` so Postgres gets JSONB
and SQLite gets JSON through the same Python interface.

## Migration

```bash
cd backend && uv run alembic revision --autogenerate \
  -m "add verifier_sessions table"
```

Manually verify the autogen:
- All columns match ORM
- FK constraint with `ondelete="RESTRICT"`
- 3 indexes (solver_session_id, created_at, verified)
- CHECK constraint `ck_verifier_sessions_status_valid`
- `down_revision` points to the entry-function migration from 4.3.a
- `downgrade()` drops the CHECK constraint before dropping the table

This is a fresh-table migration, so 3-stage backfill is not needed for
`verifier_sessions`.

Downgrade order:

```python
def downgrade() -> None:
    op.drop_constraint(
        "ck_verifier_sessions_status_valid",
        "verifier_sessions",
        type_="check",
    )
    op.drop_table("verifier_sessions")
```

## Repository

```python
# app/repositories/verifier_repository.py

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import VerifierSession


class VerifierRepository:
    """Pure DB access. Never commits; transaction boundary lives in service."""

    async def create(
        self,
        session: AsyncSession,
        *,
        solver_session_id: UUID,
        student_code: str,
        verified: bool,
        status: str,
        pass_count: int,
        fail_count: int,
        test_results: list[dict],
        diagnosis: str,
        sandbox_error: str | None,
        total_latency_ms: int,
    ) -> VerifierSession:
        row = VerifierSession(
            solver_session_id=solver_session_id,
            student_code=student_code,
            verified=verified,
            status=status,
            pass_count=pass_count,
            fail_count=fail_count,
            test_results=test_results,
            diagnosis=diagnosis,
            sandbox_error=sandbox_error,
            total_latency_ms=total_latency_ms,
        )
        session.add(row)
        await session.flush()
        return row

    async def get_by_id(
        self, session: AsyncSession, session_id: UUID
    ) -> VerifierSession | None:
        result = await session.execute(
            select(VerifierSession).where(VerifierSession.id == session_id)
        )
        return result.scalar_one_or_none()

    async def list_by_solver_session(
        self,
        session: AsyncSession,
        solver_session_id: UUID,
        *,
        limit: int = 10,
        offset: int = 0,
    ) -> list[VerifierSession]:
        result = await session.execute(
            select(VerifierSession)
            .where(VerifierSession.solver_session_id == solver_session_id)
            .order_by(VerifierSession.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(result.scalars().all())

    async def count_by_solver_session(
        self,
        session: AsyncSession,
        solver_session_id: UUID,
    ) -> int:
        result = await session.execute(
            select(func.count())
            .select_from(VerifierSession)
            .where(VerifierSession.solver_session_id == solver_session_id)
        )
        return result.scalar_one()
```

## Service

```python
# app/services/verifier_service.py

import time
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.solver.schemas import TestCase
from app.agents.verifier.agent import VerifierAgent
from app.agents.verifier.schemas import VerifierInput, VerifierOutput
from app.db.models import VerifierSession
from app.repositories.solver_repository import SolverRepository
from app.repositories.verifier_repository import VerifierRepository


class SolverSessionNotFoundError(Exception):
    """Raised when verify request references a missing solver_session_id."""


class DataIntegrityError(Exception):
    """Raised when persisted solver data is malformed for verifier input."""


class VerifierService:
    """Orchestrates VerifierAgent + VerifierRepository inside one DB transaction."""

    def __init__(
        self,
        agent: VerifierAgent,
        repository: VerifierRepository,
        solver_repository: SolverRepository,
    ) -> None:
        self.agent = agent
        self.repository = repository
        self.solver_repository = solver_repository

    async def verify_and_persist(
        self,
        session: AsyncSession,
        solver_session_id: UUID,
        student_code: str,
    ) -> tuple[VerifierSession, VerifierOutput]:
        solver_row = await self.solver_repository.get_by_id(
            session, solver_session_id
        )
        if solver_row is None:
            raise SolverSessionNotFoundError(
                f"solver_session {solver_session_id} not found"
            )

        try:
            test_cases = [TestCase(**tc) for tc in solver_row.test_cases]
        except (TypeError, ValidationError) as exc:
            raise DataIntegrityError(
                "persisted solver_session has malformed test_cases"
            ) from exc

        verifier_input = VerifierInput(
            problem_id=solver_row.problem_id,
            problem_text=solver_row.problem_text,
            entry_function=solver_row.entry_function,
            test_cases=test_cases,
            student_code=student_code,
        )

        start = time.perf_counter()
        output = await self.agent.verify(verifier_input)
        total_latency_ms = int((time.perf_counter() - start) * 1000)

        row = await self.repository.create(
            session,
            solver_session_id=solver_session_id,
            student_code=student_code,
            verified=output.verified,
            status=output.status,
            pass_count=output.pass_count,
            fail_count=output.fail_count,
            test_results=[tr.model_dump() for tr in output.test_results],
            diagnosis=output.diagnosis,
            sandbox_error=output.sandbox_error,
            total_latency_ms=total_latency_ms,
        )
        await session.commit()
        await session.refresh(row)
        return row, output
```

## API Schemas

```python
# app/schemas/verifier_session.py

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel

from app.agents.verifier.schemas import RedactedTestResult, VerifierOutput
from app.sandbox.schemas import SandboxStatus


class VerifyRequest(BaseModel):
    """API input - references existing solver_session by ID."""

    solver_session_id: UUID
    student_code: str


class VerifyResponse(BaseModel):
    """API output for POST /verify."""

    session_id: UUID
    output: VerifierOutput


class VerifierSessionOut(BaseModel):
    """Persistent record representation."""

    model_config = {"from_attributes": True}

    id: UUID
    solver_session_id: UUID
    student_code: str
    verified: bool
    status: SandboxStatus
    pass_count: int
    fail_count: int
    test_results: list[RedactedTestResult]
    diagnosis: str
    sandbox_error: str | None
    total_latency_ms: int
    created_at: datetime


class VerifierSessionListResponse(BaseModel):
    items: list[VerifierSessionOut]
    total: int
    limit: int
    offset: int
```

## Routes

```python
# app/api/routes/verify.py

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.verifier.agent import VerifierError
from app.db.session import get_db_session
from app.dependencies import get_verifier_repository, get_verifier_service
from app.repositories.verifier_repository import VerifierRepository
from app.schemas.verifier_session import (
    VerifyRequest,
    VerifyResponse,
    VerifierSessionOut,
)
from app.services.verifier_service import (
    DataIntegrityError,
    SolverSessionNotFoundError,
    VerifierService,
)

router = APIRouter(tags=["verifier"])


@router.post("/verify", response_model=VerifyResponse)
async def verify(
    request: VerifyRequest,
    service: VerifierService = Depends(get_verifier_service),
    session: AsyncSession = Depends(get_db_session),
) -> VerifyResponse:
    try:
        row, output = await service.verify_and_persist(
            session,
            request.solver_session_id,
            request.student_code,
        )
    except SolverSessionNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    except DataIntegrityError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="persisted solver_session has malformed test_cases",
        ) from exc
    except VerifierError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Verifier infrastructure unavailable: {exc}",
        ) from exc

    return VerifyResponse(session_id=row.id, output=output)


@router.get(
    "/verifier-sessions/{session_id}",
    response_model=VerifierSessionOut,
)
async def get_verifier_session(
    session_id: UUID,
    session: AsyncSession = Depends(get_db_session),
    repository: VerifierRepository = Depends(get_verifier_repository),
) -> VerifierSessionOut:
    row = await repository.get_by_id(session, session_id)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Session not found",
        )
    return VerifierSessionOut.model_validate(row)
```

For the "list verifier sessions for a given solver_session" endpoint,
extend `app/api/routes/sessions.py`:

```python
# Append to app/api/routes/sessions.py

from app.dependencies import get_verifier_repository
from app.repositories.verifier_repository import VerifierRepository
from app.schemas.verifier_session import (
    VerifierSessionListResponse,
    VerifierSessionOut,
)


@router.get(
    "/{solver_session_id}/verifier-sessions",
    response_model=VerifierSessionListResponse,
)
async def list_verifier_sessions(
    solver_session_id: UUID,
    limit: int = Query(10, ge=1, le=100),
    offset: int = Query(0, ge=0),
    session: AsyncSession = Depends(get_db_session),
    repository: VerifierRepository = Depends(get_verifier_repository),
) -> VerifierSessionListResponse:
    items = await repository.list_by_solver_session(
        session, solver_session_id, limit=limit, offset=offset
    )
    total = await repository.count_by_solver_session(
        session, solver_session_id
    )
    return VerifierSessionListResponse(
        items=[VerifierSessionOut.model_validate(i) for i in items],
        total=total,
        limit=limit,
        offset=offset,
    )
```

The existing sessions router has `prefix="/sessions"` already, so this
route segment must be relative. Final URL is
`/api/v1/sessions/{solver_session_id}/verifier-sessions` because
`main.py` adds `/api/v1` and the sessions router adds `/sessions`.

## DI Updates

Append to the existing `app/dependencies.py`:

```python
from app.agents.verifier.agent import get_verifier_agent
from app.repositories.verifier_repository import VerifierRepository
from app.services.verifier_service import VerifierService


@lru_cache
def get_verifier_repository() -> VerifierRepository:
    return VerifierRepository()


def get_verifier_service(
    agent=Depends(get_verifier_agent),
    repository: VerifierRepository = Depends(get_verifier_repository),
    solver_repository=Depends(get_solver_repository),
) -> VerifierService:
    return VerifierService(
        agent=agent,
        repository=repository,
        solver_repository=solver_repository,
    )
```

`get_solver_repository` is already defined locally in this file from
Step 3.3. No import is needed; reuse the existing local function.

`main.py`:

```python
from app.api.routes import health, health_db, sessions, solver, verify

app.include_router(verify.router, prefix="/api/v1")
```

## Test Strategy

### 4.3.a Tests

Update existing solver tests:
- SolverAgent unit tests assert `SolverOutput.entry_function` is populated.
- SolverService tests assert `entry_function` is passed to
  `SolverRepository.create`.
- SolverRepository tests assert create/read round-trips `entry_function`.
- SolverSessionOut API tests assert `entry_function` appears in responses.
- Migration test or manual migration check verifies NULL backfill detection.

### Unit tests (mocked)

**`test_verifier_repository.py`** (SQLite, ~5 tests):
- create returns row with id
- get_by_id (found + None)
- list_by_solver_session ordering DESC by created_at + limit/offset
- count_by_solver_session
- flush-not-commit invariant

SQLite FK enforcement is disabled by default. The verifier_repository unit
tests run against SQLite where FK violations would silently succeed. The FK
invariant is verified in the PG integration tests where it actually matters
at runtime. Do not add `PRAGMA foreign_keys=ON` to the shared SQLite fixture
for this task; that risks breaking unrelated tests.

**`test_verifier_service.py`** (fully mocked, ~9 tests):
1. happy path orchestration order (solver_repo.get -> agent.verify ->
   repo.create -> commit -> refresh)
2. SolverSessionNotFoundError when solver_repo returns None
3. VerifierError propagates from agent
4. agent raises -> no commit called
5. repo raises -> no commit called
6. total_latency_ms measured around agent call
7. TestCase round-trip (solver row's test_cases list[dict] ->
   TestCase objects in VerifierInput)
8. `test_malformed_persisted_test_cases_raises_clear_error`
   - Mock solver_repository.get_by_id returns a SolverSession-like object
     whose test_cases is malformed, for example missing required fields or
     wrong types.
   - Assert `TestCase(**tc)` construction failure is surfaced as
     `DataIntegrityError`, not an uncontrolled raw exception.
   - Route handler maps `DataIntegrityError` -> 500 with detail
     `"persisted solver_session has malformed test_cases"`.
9. `test_service_persists_only_redacted_results`
   - Mock agent.verify returns VerifierOutput with
     `test_results: list[RedactedTestResult]`.
   - Capture repository.create call kwargs.
   - Assert each item in `test_results` kwarg has no `expected` key.
   - Locks the DB-level redaction contract.

### Integration tests (real PG, gated)

**`test_verifier_repository_integration.py`** (~6 tests):
- create + retrieve round-trip with real PG
- FK ON DELETE RESTRICT actually blocks deletion
- FK violation with non-existent solver_session_id raises
- ordering by created_at DESC
- pagination with limit/offset
- count_by_solver_session

**`test_verify_endpoint.py`** (TestClient + real PG, ~7 tests):
1. POST /verify with valid solver_session_id -> 200, row exists
2. POST /verify with non-existent solver_session_id -> 404
3. POST /verify with bad student_code (syntax error) -> 200
   (sandbox catches), verified=false
4. GET /verifier-sessions/{id} found
5. GET /verifier-sessions/{id} missing -> 404
6. GET /sessions/{solver_id}/verifier-sessions returns list,
   ordering, pagination
7. `test_dependency_construction_failure_returns_503`
   - Use FastAPI dependency override to simulate verifier construction
     failure, such as Docker unavailable from `docker.from_env()`.
   - Assert POST /verify returns 503 with clear detail.
   - FastAPI dependency construction occurs before the route body, so a
     try/except inside the route does not catch constructor failures. The
     test should document that limitation. If the current app surfaces the
     override exception as an unhandled TestClient error, add a small wrapper
     dependency that maps construction-time verifier failures to
     `HTTPException(status_code=503)` and test that wrapper directly.

`test_verifier_sessions_endpoint.py` is redundant with the endpoint tests
above; fold coverage into `test_verify_endpoint.py`.

## 4.3.b Verification Gate

1. Migration round-trip: upgrade -> downgrade -> upgrade clean.
2. `\d verifier_sessions` shows 12 columns with FK, CHECK constraint,
   and 3 indexes.
3. Repository unit tests pass (SQLite-based, no FK assertion).
4. Service unit tests pass, including DataIntegrityError and redaction
   persistence coverage.
5. Repository integration tests pass in PG, including FK restriction and
   FK violation behavior.
6. Endpoint integration tests pass, including exact route path
   `/api/v1/sessions/{solver_session_id}/verifier-sessions`.
7. Full regression: `pytest -v -m "not integration"` = previous baseline
   + new unit tests.
8. End-to-end smoke:
   - POST `/api/v1/solve` -> get solver_session_id S
   - POST `/api/v1/verify` `{solver_session_id: S, student_code: "..."}`
     -> returns verified result
   - GET `/api/v1/verifier-sessions/{returned_id}` -> full row
   - GET `/api/v1/sessions/{S}/verifier-sessions` -> list including
     just-created row
9. ORM-level redaction check: query `test_results` JSONB directly in PG,
   confirm no `expected` key in stored dicts.
10. ORM-level redaction integrity via psql:

```sql
SELECT jsonb_path_query(test_results, '$[*].expected')
FROM verifier_sessions
LIMIT 5;
```

Expected: empty result set; no `expected` keys exist anywhere in stored
JSONB.

## What NOT to do
- DO NOT start 4.3.b before 4.3.a is migrated, threaded, and verified.
- DO NOT ask the client to provide `entry_function` in VerifyRequest as
  the main design; it can drift from the solver row.
- DO NOT use `ondelete="CASCADE"` on the FK; it destroys student history
  if a solver row is deleted.
- DO NOT add `expected` to verifier `test_results` JSONB; that violates
  the anti-leak contract from Step 4.2.
- DO NOT call agent.verify directly from route handler; service layer owns
  the transaction boundary.
- DO NOT compute latency in agent; service measures around
  `agent.verify(...)` so sandbox and diagnosis latency are captured outside
  the agent object.
- DO NOT use `Decimal` types for new verifier numeric fields.
- DO NOT prefix new routes in `routes/sessions.py` with `/sessions/`; the
  router itself already owns that prefix. The `/api/v1` prefix is added by
  `main.py`. Compose paths relatively.
- DO NOT add SQLite FK expectations to verifier_repository unit tests
  unless the fixture explicitly enables `PRAGMA foreign_keys=ON`.

## Estimated Time
- 4.3.a entry_function migration + threading: +60 min
- 4.3.b migration + ORM: 25 min
- 4.3.b repository + service: 40 min
- 4.3.b schemas + routes + DI: 30 min
- 4.3.b unit + integration tests: 45 min
- 4.3.b debug + smoke: 30 min
- **Total revised: ~3.5 hours**

## Critical Pre-implementation Check

Verify `SolverAgent.solve()` output successfully extracts `entry_function`
for all 3 fixture problems. If extraction logic differs across problem
types, the migration backfill needs to handle each case before enforcing
`solver_sessions.entry_function` as NOT NULL.
