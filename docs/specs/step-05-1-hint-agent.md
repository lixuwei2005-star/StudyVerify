# StudyVerify — Step 5.1: Hint Agent + Persistence Spec

## Goal
Add HintAgent — a stateless agent that generates progressive hints 
when a student fails verification. Each service call composes the 
prior feedback the student has already seen, so the Hint Agent can 
generate something genuinely new and progressively more specific 
without trusting client-supplied history.

After this step:
- POST /api/v1/hint accepts {verifier_session_id} and returns the 
  next progressive hint
- hint_sessions persists every hint call with FK to verifier_session
- Anti-leak guarantee from Step 4.2 extends to hints (LLM never 
  sees expected outputs)

## Why Progressive Hints
Step 4.2's Verifier diagnosis is one-shot: "your function returns 
the wrong value for empty input". If the student still doesn't 
understand, we need a more specific second hint, then a more 
specific third. The verifier diagnosis seeds the first hint's 
context, so hint #1 builds on what the student has already seen 
instead of repeating it. Each call:
- Sees the prior public feedback to avoid repetition
- Goes one notch more specific without ever giving the answer
- Anti-leak prompt rules from 4.2 apply identically

A hard cap of 5 hints per verifier_session protects against:
- LLM cost from unbounded repeated hint requests
- Progressive hint drift toward answer leakage as hints become more 
  specific
- Student over-reliance on incremental tutoring instead of attempting 
  a revised solution

The soft prompt rule "I've given as many hints as I can" remains as 
a guideline for the LLM, but the hard service-level cap is the real 
guardrail.

## Scope
- New HintAgent (stateless, mirrors VerifierAgent pattern)
- hint_sessions table with FK to verifier_sessions
- HintRepository + HintService following Step 3.3 / 4.3 patterns
- POST /api/v1/hint route
- GET /api/v1/hint-sessions/{id}
- GET /api/v1/verifier-sessions/{id}/hints (list hints for a 
  given verifier session)

## Out of Scope (this step)
- ❌ Full tutoring flow (Solver→Verifier→Hint chain) — Step 5.2
- ❌ LangGraph orchestration — Step 6+ (when complexity justifies)
- ❌ Frontend integration — Step 7
- ❌ Hint quality evaluation — Step 9 territory

## Architecture

````
HintAgent.generate(input) → HintOutput
  │
  ├─ 1. Receive: problem_text, student_code (latest), 
  │     failed_test_inputs, prior_hints (list[str])
  │
  ├─ 2. Build progressive prompt:
  │     "Student saw these hints already: [...]. 
  │      They still don't understand. Give the next hint, 
  │      one notch more specific. Same rules: no code, no 
  │      expected output reveals."
  │
  ├─ 3. LLM call (temperature=0.4, slightly higher than verifier 
  │     for diversity since we explicitly want NEW phrasing)
  │
  └─ 4. Return: hint_text (str)

HintAgent has no DB access. Service layer composes HintInput from 
persisted verifier_session + prior hints query, then assigns 
hint_index from the DB count of existing hint rows.
````

## Database Schema

`hint_sessions` table:

| Column | Type | Notes |
|---|---|---|
| id | UUID | PK |
| verifier_session_id | UUID | FK → verifier_sessions(id) ON DELETE RESTRICT, indexed |
| hint_index | INTEGER | NOT NULL, 1-based; the Nth hint for this verifier_session |
| hint_text | TEXT | NOT NULL; the generated hint |
| prior_hints_count | INTEGER | NOT NULL; number of prior feedback items shown to the LLM, including the verifier diagnosis seed if present |
| total_latency_ms | INTEGER | NOT NULL; service-measured |
| created_at | TIMESTAMPTZ | NOT NULL DEFAULT now(), indexed |

Indexes:
- `ix_hint_sessions_verifier_session_id` (for list_by_verifier)
- `ix_hint_sessions_created_at` (for ORDER BY)

Constraint:
- UNIQUE (verifier_session_id, hint_index) — prevents duplicate 
  hint entries for the same step

FK behavior: ON DELETE RESTRICT — same as 4.3, audit history 
preserved.

`hint_index` and `prior_hints_count` intentionally mean different 
things:
- `hint_index` is the Nth persisted hint row for this verifier_session, 
  1-based, assigned by the service from the DB count.
- `prior_hints_count` is the number of prior feedback items the LLM 
  saw. On the first hint request, this may be 1 even when there are 0 
  prior hint rows, because the verifier's one-shot diagnosis can be 
  seeded into prompt context.

## Files to Create / Modify

### New
- `backend/alembic/versions/<hash>_add_hint_sessions.py`
- `backend/app/agents/hint/__init__.py`
- `backend/app/agents/hint/schemas.py` — HintInput, HintOutput
- `backend/app/agents/hint/prompts.py` — progressive hint prompt
- `backend/app/agents/hint/agent.py` — HintAgent class + factory
- `backend/app/repositories/hint_repository.py`
- `backend/app/services/hint_service.py`
- `backend/app/schemas/hint_session.py` — API schemas
- `backend/app/api/routes/hint.py`
- `backend/tests/agents/test_hint.py` — unit tests
- `backend/tests/agents/test_hint_integration.py` — real LLM
- `backend/tests/repositories/test_hint_repository.py`
- `backend/tests/repositories/test_hint_repository_integration.py`
- `backend/tests/services/test_hint_service.py`
- `backend/tests/api/test_hint_endpoint.py`

### Modified
- `backend/app/db/models.py` — add HintSession ORM
- `backend/app/dependencies.py` — get_hint_repository, 
  get_hint_service factories
- `backend/app/api/routes/verify.py` OR `routes/sessions.py` — 
  add GET /verifier-sessions/{id}/hints
- `backend/app/main.py` — include hint router

## Pydantic Schemas (Agent layer)

````python
# app/agents/hint/schemas.py

from pydantic import BaseModel, Field


class HintInput(BaseModel):
    """Stateless input. Service composes from persisted 
    verifier_session + queried prior hints."""
    
    problem_text: str
    student_code: str = Field(
        description="Latest version of student code at time of "
                    "verification failure"
    )
    failed_test_inputs: list[str] = Field(
        description="Inputs of tests that failed; used for context "
                    "without revealing expected outputs"
    )
    prior_hints: list[str] = Field(
        default_factory=list,
        description="Hints already shown to the student in this "
                    "verifier_session, oldest first. May include "
                    "the verifier's one-shot diagnosis as a seeded "
                    "entry on the first hint request."
    )


class HintOutput(BaseModel):
    hint_text: str = Field(
        description="The next progressive hint, one notch more "
        "specific than the last in prior_hints"
    )
````

## Progressive Hint Prompt

````python
# app/agents/hint/prompts.py

HINT_SYSTEM_PROMPT = """You are a coding tutor giving a student 
their next hint. They have already seen earlier hints below but 
still haven't solved the problem. Your job is to give the NEXT 
hint, slightly more specific than the previous ones, in 1-2 
sentences.

CRITICAL RULES:
1. DO NOT write any code, pseudocode, or function signatures.
2. DO NOT reveal expected outputs for any failing test.
3. DO NOT repeat or paraphrase what previous hints already said.
4. Each hint should be one step more specific than the last:
   - 1st hint: high-level conceptual nudge
   - 2nd hint: point at the specific case or operation
   - 3rd hint: closer to the structural fix without giving it
   - 4th+ hint: increasingly specific, but still no code
5. Keep it short. 1-2 sentences. No greetings, no encouragement 
   filler.

Note that the system imposes a hard limit on the number of hints 
per attempt. If you're truly out of useful hints to give without 
crossing into giving code or answers BEFORE that limit, say so 
explicitly: "I've given as many hints as I can without revealing 
the answer. Please review the problem statement carefully." This is 
acceptable and preferable to crossing the line.

Example progression for an empty-list bug:
1. "Your function's behavior on edge inputs differs from the 
   problem requirement. Re-read the spec carefully."
2. "Specifically, think about what your function does when the 
   input list contains no elements."
3. "Empty inputs need special handling. Check if your accumulator 
   has a sensible starting value."
4. "Walk through your code mentally with an empty list as input. 
   What does each step do?"
"""


def build_hint_prompt(input: "HintInput") -> dict[str, str]:
    """Returns {'system': ..., 'user': ...}."""
    
    prior_block = "\n".join(
        f"  Hint {i+1}: {h}" for i, h in enumerate(input.prior_hints)
    ) if input.prior_hints else "  (none yet — this is the first hint)"
    
    failed_inputs_block = "\n".join(
        f"  - {inp}" for inp in input.failed_test_inputs[:3]
    )
    
    user_message = f"""PROBLEM:
{input.problem_text}

STUDENT'S CURRENT CODE:
```python
{input.student_code}
```

FAILED TEST INPUTS:
{failed_inputs_block}

HINTS ALREADY SHOWN:
{prior_block}

Generate the next hint per the rules in the system message."""
    
    return {
        "system": HINT_SYSTEM_PROMPT,
        "user": user_message,
    }
````

⚠️ **Anti-leak parity with Step 4.2**:
- LLM never sees expected outputs (only failed inputs + student code)
- Failed test descriptions deliberately omitted (they may state 
  expected behavior literally)
- Prior feedback block contains only already-public LLM text: prior 
  HintAgent hints and, on the first request, the Verifier diagnosis

## HintAgent Class

````python
# app/agents/hint/agent.py

import logging
from functools import lru_cache

from app.agents.hint.schemas import HintInput, HintOutput
from app.agents.hint.prompts import build_hint_prompt
from app.llm.client import DeepSeekClient, get_llm_client
from app.llm.exceptions import LLMError, LLMTimeoutError

logger = logging.getLogger(__name__)


# Fallback when LLM is unreachable
LLM_FALLBACK_HINT = (
    "Hint service is temporarily unavailable. Please review the "
    "problem statement carefully and consider what your code does "
    "for edge-case inputs."
)


class HintError(Exception):
    """Raised when hint generation fails at infra level."""


class HintAgent:
    """Stateless. Mirrors VerifierAgent's pattern: param-injected 
    LLM client, single .generate() method, graceful LLM degradation.
    """
    
    def __init__(self, llm_client: DeepSeekClient):
        self.llm = llm_client
    
    async def generate(self, input: HintInput) -> HintOutput:
        prompt = build_hint_prompt(input)
        
        try:
            response = await self.llm.chat(
                messages=[
                    {"role": "system", "content": prompt["system"]},
                    {"role": "user", "content": prompt["user"]},
                ],
                temperature=0.4,
                json_mode=False,
            )
            hint_text = response.strip()
        except (LLMError, LLMTimeoutError) as exc:
            logger.warning(
                "LLM unavailable for hint generation: %s", exc
            )
            hint_text = LLM_FALLBACK_HINT
        
        return HintOutput(
            hint_text=hint_text,
        )


@lru_cache
def get_hint_agent() -> HintAgent:
    return HintAgent(llm_client=get_llm_client())
````

## ORM Model

````python
# Append to app/db/models.py

class HintSession(Base):
    __tablename__ = "hint_sessions"
    
    id: Mapped[UUID] = mapped_column(
        sa.Uuid, primary_key=True, default=uuid4
    )
    verifier_session_id: Mapped[UUID] = mapped_column(
        sa.Uuid,
        ForeignKey("verifier_sessions.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    hint_index: Mapped[int] = mapped_column(Integer, nullable=False)
    hint_text: Mapped[str] = mapped_column(Text, nullable=False)
    prior_hints_count: Mapped[int] = mapped_column(
        Integer, nullable=False
    )
    total_latency_ms: Mapped[int] = mapped_column(
        Integer, nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        index=True,
    )
    
    __table_args__ = (
        sa.UniqueConstraint(
            "verifier_session_id", "hint_index",
            name="uq_hint_sessions_verifier_index",
        ),
    )
````

## Migration

Standard autogen + manual review:
- 7 columns
- FK ondelete RESTRICT
- 2 indexes (verifier_session_id, created_at)
- 1 UNIQUE constraint (verifier_session_id, hint_index)
- down_revision = current head (`f3541344b480` from 4.3)

3-stage backfill not needed (fresh table, no existing rows).

## Repository

````python
# app/repositories/hint_repository.py

from uuid import UUID
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import HintSession


class HintRepository:
    """Pure DB access. Never commits."""
    
    async def create(
        self,
        session: AsyncSession,
        *,
        verifier_session_id: UUID,
        hint_index: int,
        hint_text: str,
        prior_hints_count: int,
        total_latency_ms: int,
    ) -> HintSession:
        row = HintSession(
            verifier_session_id=verifier_session_id,
            hint_index=hint_index,
            hint_text=hint_text,
            prior_hints_count=prior_hints_count,
            total_latency_ms=total_latency_ms,
        )
        session.add(row)
        await session.flush()
        return row
    
    async def get_by_id(
        self, session: AsyncSession, session_id: UUID
    ) -> HintSession | None:
        result = await session.execute(
            select(HintSession).where(HintSession.id == session_id)
        )
        return result.scalar_one_or_none()
    
    async def list_by_verifier_session(
        self,
        session: AsyncSession,
        verifier_session_id: UUID,
    ) -> list[HintSession]:
        """Returns ALL hints for a verifier_session, oldest first."""
        result = await session.execute(
            select(HintSession)
            .where(HintSession.verifier_session_id == verifier_session_id)
            .order_by(HintSession.hint_index.asc())
        )
        return list(result.scalars().all())
    
    async def count_by_verifier_session(
        self,
        session: AsyncSession,
        verifier_session_id: UUID,
    ) -> int:
        result = await session.execute(
            select(func.count())
            .select_from(HintSession)
            .where(HintSession.verifier_session_id == verifier_session_id)
        )
        return result.scalar_one()
````

## Service

````python
# app/services/hint_service.py

import time
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.hint.agent import HintAgent
from app.agents.hint.schemas import HintInput, HintOutput
from app.agents.verifier.schemas import RedactedTestResult
from app.db.models import HintSession
from app.repositories.hint_repository import HintRepository
from app.repositories.verifier_repository import VerifierRepository
from app.repositories.solver_repository import SolverRepository


MAX_HINTS_PER_VERIFIER_SESSION = 5


class VerifierSessionNotFoundError(Exception):
    pass


class VerifierSessionPassedError(Exception):
    """Raised when student requests hint for a verifier_session 
    that already passed (verified=True). No hint needed."""


class HintLimitExceededError(Exception):
    """Raised when max hints have already been provided."""


class HintConcurrencyError(Exception):
    """Raised when concurrent hint inserts race on hint_index."""


class DataIntegrityError(Exception):
    """Raised when persisted verifier data is malformed for hint input."""


class HintService:
    """Orchestration. Composes HintInput from persisted 
    verifier_session + prior hints, runs the agent, persists."""
    
    def __init__(
        self,
        agent: HintAgent,
        repository: HintRepository,
        verifier_repository: VerifierRepository,
        solver_repository: SolverRepository,
    ):
        self.agent = agent
        self.repository = repository
        self.verifier_repository = verifier_repository
        self.solver_repository = solver_repository
    
    async def generate_and_persist(
        self,
        session: AsyncSession,
        verifier_session_id: UUID,
    ) -> tuple[HintSession, HintOutput]:
        # 1. Fetch verifier_session
        verifier_row = await self.verifier_repository.get_by_id(
            session, verifier_session_id
        )
        if verifier_row is None:
            raise VerifierSessionNotFoundError(
                f"verifier_session {verifier_session_id} not found"
            )
        
        # 2. If already verified, no hint needed
        if verifier_row.verified:
            raise VerifierSessionPassedError(
                f"verifier_session {verifier_session_id} already passed; "
                "no hint required"
            )
        
        # 3. Fetch parent solver_session for problem context
        solver_row = await self.solver_repository.get_by_id(
            session, verifier_row.solver_session_id
        )
        if solver_row is None:
            # Should be impossible due to FK RESTRICT, but defensive
            raise VerifierSessionNotFoundError(
                "Inconsistent state: verifier exists but solver missing"
            )
        
        # 4. Fetch prior hints in order
        prior_hint_rows = await self.repository.list_by_verifier_session(
            session, verifier_session_id
        )
        prior_hints = [h.hint_text for h in prior_hint_rows]
        actual_prior_hint_count = await self.repository.count_by_verifier_session(
            session, verifier_session_id
        )
        
        # First hint should not repeat the Verifier's one-shot diagnosis.
        # Seed the prior_hints list with it so the LLM produces something
        # genuinely different on the first call. This seeded entry is only
        # prompt context; it is NOT persisted to hint_sessions.
        if not prior_hints and verifier_row.diagnosis:
            prior_hints = [verifier_row.diagnosis]
        
        if actual_prior_hint_count >= MAX_HINTS_PER_VERIFIER_SESSION:
            raise HintLimitExceededError(
                f"Maximum {MAX_HINTS_PER_VERIFIER_SESSION} hints already "
                f"provided for verifier_session {verifier_session_id}. "
                "Please review the problem statement carefully or attempt "
                "a different solution."
            )
        
        # 5. Compose HintInput
        # Pull failed test inputs from verifier's redacted test_results.
        # Validate persisted JSONB before trusting its shape.
        try:
            redacted_results = [
                RedactedTestResult.model_validate(tr)
                for tr in verifier_row.test_results
            ]
        except (ValueError, TypeError) as e:
            raise DataIntegrityError(
                f"verifier_session {verifier_session_id} has malformed "
                f"test_results: {e}"
            ) from e
        
        failed_test_inputs = [
            tr.input for tr in redacted_results if not tr.passed
        ]
        
        hint_input = HintInput(
            problem_text=solver_row.problem_text,
            student_code=verifier_row.student_code,
            failed_test_inputs=failed_test_inputs,
            prior_hints=prior_hints,
        )
        
        # 6. Generate (agent has internal LLM fallback, no exception)
        start = time.perf_counter()
        output = await self.agent.generate(hint_input)
        total_latency_ms = int((time.perf_counter() - start) * 1000)
        llm_prior_hints_count = len(prior_hints)
        output_hint_index = actual_prior_hint_count + 1
        
        # 7. Persist. UNIQUE (verifier_session_id, hint_index) protects
        # against concurrent requests that compute the same next index.
        for attempt in range(2):  # one retry on IntegrityError
            try:
                row = await self.repository.create(
                    session,
                    verifier_session_id=verifier_session_id,
                    hint_index=output_hint_index,
                    hint_text=output.hint_text,
                    prior_hints_count=llm_prior_hints_count,
                    total_latency_ms=total_latency_ms,
                )
                await session.commit()
                await session.refresh(row)
                return row, output
            except IntegrityError:
                await session.rollback()
                if attempt == 1:
                    raise HintConcurrencyError(
                        "Concurrent hint requests for verifier_session "
                        f"{verifier_session_id}; please retry"
                    )
                
                # Refetch hints and recompute index for retry. Do NOT call
                # the LLM again; the race is on insert, not generation.
                prior_hint_rows = await self.repository.list_by_verifier_session(
                    session, verifier_session_id
                )
                output_hint_index = len(prior_hint_rows) + 1
        
        raise HintConcurrencyError(
            "Concurrent hint requests for verifier_session "
            f"{verifier_session_id}; please retry"
        )
````

## API Schemas

````python
# app/schemas/hint_session.py

from datetime import datetime
from uuid import UUID
from pydantic import BaseModel


class HintRequest(BaseModel):
    """API input. Service queries prior hints itself; client 
    doesn't pass them — single source of truth is the DB."""
    verifier_session_id: UUID


class HintResponse(BaseModel):
    session_id: UUID
    hint_index: int
    hint_text: str


class HintSessionOut(BaseModel):
    model_config = {"from_attributes": True}
    
    id: UUID
    verifier_session_id: UUID
    hint_index: int
    hint_text: str
    prior_hints_count: int
    total_latency_ms: int
    created_at: datetime


class HintSessionListResponse(BaseModel):
    items: list[HintSessionOut]
    total: int
````

## Routes

````python
# app/api/routes/hint.py

from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db_session
from app.dependencies import get_hint_service, get_hint_repository
from app.repositories.hint_repository import HintRepository
from app.schemas.hint_session import (
    HintRequest, HintResponse, HintSessionOut,
)
from app.services.hint_service import (
    DataIntegrityError,
    HintConcurrencyError,
    HintLimitExceededError,
    HintService,
    VerifierSessionNotFoundError,
    VerifierSessionPassedError,
)

router = APIRouter(tags=["hint"])


@router.post("/hint", response_model=HintResponse)
async def request_hint(
    request: HintRequest,
    service: HintService = Depends(get_hint_service),
    session: AsyncSession = Depends(get_db_session),
):
    try:
        row, output = await service.generate_and_persist(
            session, request.verifier_session_id
        )
    except VerifierSessionNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except VerifierSessionPassedError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except HintConcurrencyError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except HintLimitExceededError as e:
        raise HTTPException(status_code=429, detail=str(e))
    except DataIntegrityError as e:
        raise HTTPException(status_code=500, detail=str(e))
    
    return HintResponse(
        session_id=row.id,
        hint_index=row.hint_index,
        hint_text=output.hint_text,
    )


@router.get("/hint-sessions/{session_id}", response_model=HintSessionOut)
async def get_hint_session(
    session_id: UUID,
    session: AsyncSession = Depends(get_db_session),
    repository: HintRepository = Depends(get_hint_repository),
):
    row = await repository.get_by_id(session, session_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return HintSessionOut.model_validate(row)
````

For the list endpoint, append to existing `verify.py` router. These 
imports go at the top of `verify.py` alongside existing imports — 
they're listed here in the snippet for clarity but should be merged 
into the existing import block.

````python
# app/api/routes/verify.py — append

from app.dependencies import get_hint_repository
from app.repositories.hint_repository import HintRepository
from app.schemas.hint_session import (
    HintSessionListResponse,
    HintSessionOut,
)

@router.get(
    "/verifier-sessions/{verifier_session_id}/hints",
    response_model=HintSessionListResponse,
)
async def list_hints_for_verifier_session(
    verifier_session_id: UUID,
    session: AsyncSession = Depends(get_db_session),
    repository: HintRepository = Depends(get_hint_repository),
):
    items = await repository.list_by_verifier_session(
        session, verifier_session_id
    )
    return HintSessionListResponse(
        items=[HintSessionOut.model_validate(i) for i in items],
        total=len(items),
    )
````

Status-code rationale:
- `VerifierSessionPassedError` maps to 409 Conflict because the 
  resource state (`verified=True`) precludes creating the requested 
  sub-resource (`hint`). 400 would imply the client malformed the 
  request; here the request is valid, but the verifier_session is not 
  hint-eligible.
- `HintConcurrencyError` also maps to 409 Conflict because concurrent 
  requests created a temporary resource-state conflict. The detail 
  message distinguishes it from the already-passed case.
- `HintLimitExceededError` maps to 429 Too Many Requests because the 
  verifier_session has reached its resource-level hint limit.

## DI Updates

Append to `app/dependencies.py`:

````python
from app.agents.hint.agent import get_hint_agent
from app.repositories.hint_repository import HintRepository
from app.services.hint_service import HintService


@lru_cache
def get_hint_repository() -> HintRepository:
    return HintRepository()


def get_hint_service(
    agent=Depends(get_hint_agent),
    repository: HintRepository = Depends(get_hint_repository),
    verifier_repository=Depends(get_verifier_repository),
    solver_repository=Depends(get_solver_repository),
) -> HintService:
    return HintService(
        agent=agent,
        repository=repository,
        verifier_repository=verifier_repository,
        solver_repository=solver_repository,
    )
````

`main.py`: include hint router with prefix `/api/v1`.

## Test Strategy

### Unit (mocked)

**`test_hint.py`** (~10 tests):
- happy path: generate first hint (prior_hints=[]), verify hint text 
  returned and no hint_index field is assigned by the agent
- second hint: prior_hints=[h1], verify prior hint appears in prompt
- prompt does NOT include any "expected" value (sentinel test like 
  Step 4.2 #12)
- prompt does include all prior hints in the system context
- LLM error → fallback hint text returned, no exception
- prompt builds without crash on empty failed_test_inputs
- prompt caps failed_test_inputs at 3 (token budget)
- temperature=0.4 (locked to prevent drift)
- chat method called, .complete does not exist (lock contract)
- HintInput with 0 prior_hints produces "first hint" framing

**`test_hint_service.py`** (~16 tests):
- happy path orchestration order
- VerifierSessionNotFoundError raised when verifier missing
- VerifierSessionPassedError raised when verified=True
- Solver missing → defensive error (FK should prevent but tested)
- prior hints fetched in order (assert ORDER BY hint_index)
- failed_test_inputs extracted from verifier_row.test_results 
  (only failed ones)
- hint_index calculated from DB count of actual hint rows
- agent raises → no commit
- repo raises → no commit
- concurrent insert retries once on IntegrityError:
  mock repository.create to raise IntegrityError on first call, then 
  succeed; assert two list_by_verifier_session calls (initial + 
  refetch), one LLM call only, and no exception to caller
- concurrent insert raises after retry exhausted:
  mock repository.create to raise IntegrityError both times; assert 
  HintConcurrencyError and exactly 2 create attempts
- max hints exceeded raises before LLM call:
  seed 5 prior hint rows (= MAX_HINTS_PER_VERIFIER_SESSION); assert 
  HintLimitExceededError and no LLM call
- malformed persisted test_results raises DataIntegrityError:
  mock verifier_row.test_results with malformed dict missing `input`; 
  assert DataIntegrityError and no LLM call
- first hint seeds prior_hints with diagnosis:
  prior_hint_rows empty, verifier_row.diagnosis set; capture prompt 
  and assert diagnosis appears in HINTS ALREADY SHOWN
- first hint with no diagnosis has no seeding:
  prior_hint_rows empty, verifier_row.diagnosis empty; capture prompt 
  and assert "(none yet — this is the first hint)" appears
- hint_index uses DB count, not seeded prior count:
  0 actual hint rows, diagnosis seeded, repository count returns 0; 
  assert created row uses hint_index=1, not 2

**`test_hint_repository.py`** (~5 tests, SQLite):
- create + get_by_id round trip
- list_by_verifier_session orders by hint_index ASC
- count_by_verifier_session
- flush-not-commit
- (FK & UNIQUE moved to PG integration — SQLite doesn't enforce 
  by default)

### Integration

**`test_hint_repository_integration.py`** (~5 tests, PG):
- FK ON DELETE RESTRICT works
- UNIQUE (verifier_session_id, hint_index) actually rejects 
  duplicates
- create + retrieve round trip with real PG
- list ordering with real timestamps
- count

**`test_hint_endpoint.py`** (~10 tests, TestClient + PG):
- POST /hint with valid verifier_session_id (verified=False) → 
  200 with hint
- POST /hint with non-existent verifier_session_id → 404
- POST /hint with verified=True verifier_session_id → 409, detail 
  mentions "already passed"
- POST /hint twice → second has hint_index=2, prior_hints_count=1
- GET /hint-sessions/{id} found / 404
- GET /verifier-sessions/{id}/hints returns ordered list
- POST /hint at limit with 5 existing hint_sessions → 429, detail 
  mentions the limit
- POST /hint concurrent 409:
  hard to test end-to-end; manually create a UNIQUE violation 
  mid-flight with a session hook or mocked repository. May be skipped 
  if too complex; unit tests provide the primary concurrency coverage.
- POST /hint does not accept client prior_hints:
  send extra field `prior_hints: ["fake"]`; Pydantic may ignore extra 
  fields by default or reject them if schema config is strict. In the 
  ignore case, assert response/persisted prior_hints_count reflects 
  actual DB context, not the fake client list.

**`test_hint_integration.py`** (~3 tests, real LLM):
- correct prompt produces hint that doesn't contain code (regex 
  same as Step 4.2)
- second call with prior_hint produces DIFFERENT text
- 4th call (3 prior hints) — agent may produce "out of hints" 
  fallback, or another specific hint; either is acceptable as 
  long as no code/answer leaks

## Verification Checklist

1. Migration round-trip clean
2. \d hint_sessions shows 7 cols + FK + 2 indexes + 1 UNIQUE
3. Unit tests pass: 10 + 16 + 5 = 31 new
4. Integration tests pass: 5 + 10 + 3 = 18 new
5. Full regression: 89 + 31 = 120 unit + 1 skipped
6. End-to-end smoke (manual):
   - POST /solve → SOLVER_ID
   - POST /verify (buggy code) → VERIFIER_ID (verified=False)
   - POST /hint {verifier_session_id: VERIFIER_ID} → hint #1 
     does not repeat verifier diagnosis verbatim
   - POST /hint again → hint #2 (different from #1)
   - GET /verifier-sessions/{VERIFIER_ID}/hints → list of 2
7. Anti-leak verification: psql query shows no expected values 
   leaked into hint_text:
   SELECT COUNT(*) FROM hint_sessions h
   JOIN verifier_sessions v ON h.verifier_session_id = v.id
   JOIN solver_sessions s ON v.solver_session_id = s.id,
   jsonb_array_elements(s.test_cases) tc
   WHERE h.hint_text LIKE '%' || (tc->>'expected') || '%';
   Expected: 0

## What NOT to do
- DO NOT pass prior_hints from client — service queries DB. 
  Client-provided list could be tampered to bypass progressive 
  logic.
- DO NOT include test_case.expected anywhere in HintInput or 
  prompt (parity with Step 4.2 anti-leak)
- DO NOT include test_case.description (may state expected 
  behavior literally)
- DO NOT raise on LLM error; degrade with fallback hint
- DO NOT cache hint outputs — each call generates fresh, even 
  for identical prior state (LLM may produce useful variation)
- DO NOT remove the UNIQUE (verifier_session_id, hint_index) 
  constraint — it prevents race conditions where two concurrent 
  POST /hint calls insert duplicate hint_index
- DO NOT call the LLM twice on retry. The race is on insert, not on 
  generation. Reuse the text and just fix hint_index.

## Estimated Time
- Migration + ORM + repository: 30 min
- Service + agent + prompts: 45 min
- Routes + DI + schemas: 25 min
- Unit tests (31): 60 min
- Integration tests (18): 55 min
- Debug + smoke: 30 min
- Concurrency handling + max-cap + diagnosis seeding: 30 min
- **Total: ~4 hours**
