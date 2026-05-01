"""Unit tests for HintRepository against in-memory SQLite.

Exercises pure DB-access behavior: create, get_by_id, list ordering,
count, and the flush-not-commit transaction invariant.

FK enforcement and UNIQUE constraint are disabled by default in SQLite;
those behaviors are tested in test_hint_repository_integration.py (PG).
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import HintSession, SolverSession, VerifierSession
from app.repositories.hint_repository import HintRepository

from decimal import Decimal


@pytest.fixture
def repo() -> HintRepository:
    return HintRepository()


def _solver_seed(**overrides) -> SolverSession:
    defaults = dict(
        problem_id="prob_h",
        problem_text="Return the sum of a list.",
        entry_function="sum_list",
        test_cases=[{"input": "[1,2,3]", "expected": "6", "description": "basic"}],
        analysis="-",
        plan_steps=[],
        code="def sum_list(nums): return sum(nums)",
        explanation="-",
        verified=True,
        test_results=[],
        confidence=Decimal("0.90"),
        retry_used=False,
        total_latency_ms=10,
    )
    defaults.update(overrides)
    return SolverSession(**defaults)


def _verifier_seed(solver_session_id: uuid.UUID, **overrides) -> VerifierSession:
    defaults = dict(
        solver_session_id=solver_session_id,
        student_code="def sum_list(nums): return 0",
        verified=False,
        status="some_failed",
        pass_count=0,
        fail_count=1,
        test_results=[{"input": "[1,2,3]", "actual": "0", "passed": False, "duration_ms": 1, "error": None}],
        diagnosis="Your function always returns 0.",
        sandbox_error=None,
        total_latency_ms=42,
    )
    defaults.update(overrides)
    return VerifierSession(**defaults)


def _hint_kwargs(verifier_session_id: uuid.UUID, **overrides) -> dict:
    base = dict(
        verifier_session_id=verifier_session_id,
        hint_index=1,
        hint_text="Think about what your function does for any input.",
        prior_hints_count=1,
        total_latency_ms=100,
    )
    base.update(overrides)
    return base


async def _seed_parents(session: AsyncSession) -> uuid.UUID:
    """Persist solver + verifier rows; return verifier.id."""
    solver = _solver_seed()
    session.add(solver)
    await session.flush()

    verifier = _verifier_seed(solver.id)
    session.add(verifier)
    await session.flush()

    return verifier.id


# ---------------------------------------------------------------------------
# 1. create + get_by_id round trip
# ---------------------------------------------------------------------------
async def test_create_and_get_by_id_round_trip(
    sqlite_session: AsyncSession, repo: HintRepository
) -> None:
    vid = await _seed_parents(sqlite_session)

    row = await repo.create(sqlite_session, **_hint_kwargs(vid))
    assert isinstance(row.id, uuid.UUID)

    await sqlite_session.commit()
    found = await repo.get_by_id(sqlite_session, row.id)
    assert found is not None
    assert found.hint_text == "Think about what your function does for any input."
    assert found.hint_index == 1
    assert found.prior_hints_count == 1
    assert found.total_latency_ms == 100

    missing = await repo.get_by_id(sqlite_session, uuid.uuid4())
    assert missing is None


# ---------------------------------------------------------------------------
# 2. list_by_verifier_session orders by hint_index ASC
# ---------------------------------------------------------------------------
async def test_list_by_verifier_session_orders_by_hint_index_asc(
    sqlite_session: AsyncSession, repo: HintRepository
) -> None:
    vid = await _seed_parents(sqlite_session)

    # Insert out-of-order
    for idx in (3, 1, 2):
        sqlite_session.add(
            HintSession(
                verifier_session_id=vid,
                hint_index=idx,
                hint_text=f"Hint {idx}",
                prior_hints_count=idx - 1,
                total_latency_ms=10,
            )
        )
    await sqlite_session.commit()

    rows = await repo.list_by_verifier_session(sqlite_session, vid)
    assert [r.hint_index for r in rows] == [1, 2, 3]


# ---------------------------------------------------------------------------
# 3. count_by_verifier_session
# ---------------------------------------------------------------------------
async def test_count_by_verifier_session(
    sqlite_session: AsyncSession, repo: HintRepository
) -> None:
    vid = await _seed_parents(sqlite_session)

    assert await repo.count_by_verifier_session(sqlite_session, vid) == 0

    await repo.create(sqlite_session, **_hint_kwargs(vid, hint_index=1))
    await repo.create(sqlite_session, **_hint_kwargs(vid, hint_index=2, prior_hints_count=2))
    await sqlite_session.commit()

    assert await repo.count_by_verifier_session(sqlite_session, vid) == 2


# ---------------------------------------------------------------------------
# 4. flush-not-commit invariant
# ---------------------------------------------------------------------------
async def test_flush_not_commit_invariant(
    sqlite_session: AsyncSession, repo: HintRepository
) -> None:
    """Repository must flush but not commit. Rollback must wipe the row."""
    vid = await _seed_parents(sqlite_session)

    await repo.create(sqlite_session, **_hint_kwargs(vid))
    await sqlite_session.rollback()

    rows = (await sqlite_session.execute(select(HintSession))).all()
    assert rows == []


# ---------------------------------------------------------------------------
# 5. list returns empty for unknown verifier_session_id
# ---------------------------------------------------------------------------
async def test_list_returns_empty_for_unknown_verifier_session(
    sqlite_session: AsyncSession, repo: HintRepository
) -> None:
    await _seed_parents(sqlite_session)

    rows = await repo.list_by_verifier_session(sqlite_session, uuid.uuid4())
    assert rows == []
