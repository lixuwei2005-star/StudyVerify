"""Unit tests for VerifierRepository against in-memory SQLite.

Exercises pure DB-access behavior: row creation, retrieval, ordering,
pagination, count, and the flush-not-commit transaction invariant.

FK enforcement is disabled by default in SQLite, so FK violation behavior
is NOT tested here — that belongs in the PG integration tests.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import SolverSession, VerifierSession
from app.repositories.verifier_repository import VerifierRepository

from decimal import Decimal


@pytest.fixture
def repo() -> VerifierRepository:
    return VerifierRepository()


def _solver_seed(sqlite_session: AsyncSession, **overrides) -> SolverSession:
    """Return an unsaved SolverSession for use as FK parent."""
    defaults = dict(
        problem_id="prob_v",
        problem_text="text",
        entry_function="f",
        test_cases=[{"input": "1", "expected": "1", "description": "id"}],
        analysis="-",
        plan_steps=[],
        code="def f(x): return x",
        explanation="-",
        verified=True,
        test_results=[],
        confidence=Decimal("0.90"),
        retry_used=False,
        total_latency_ms=10,
    )
    defaults.update(overrides)
    return SolverSession(**defaults)


def _verifier_kwargs(solver_session_id: uuid.UUID, **overrides) -> dict:
    base = dict(
        solver_session_id=solver_session_id,
        student_code="def f(x): return x",
        verified=True,
        status="all_passed",
        pass_count=1,
        fail_count=0,
        test_results=[{"input": "1", "actual": "1", "passed": True, "duration_ms": 1, "error": None}],
        diagnosis="",
        sandbox_error=None,
        total_latency_ms=42,
    )
    base.update(overrides)
    return base


# ---------- create ----------


async def test_create_returns_row_with_id_and_no_commit(
    sqlite_session: AsyncSession, repo: VerifierRepository
) -> None:
    solver = _solver_seed(sqlite_session)
    sqlite_session.add(solver)
    await sqlite_session.flush()

    row = await repo.create(sqlite_session, **_verifier_kwargs(solver.id))
    assert isinstance(row.id, uuid.UUID)

    # Commit and verify the row is persisted
    await sqlite_session.commit()
    fetched = (await sqlite_session.execute(select(VerifierSession))).scalar_one()
    assert fetched.id == row.id
    assert fetched.verified is True
    assert fetched.total_latency_ms == 42


async def test_flush_not_commit_invariant(
    sqlite_session: AsyncSession, repo: VerifierRepository
) -> None:
    """Repository must flush but not commit. Rollback must wipe the row."""
    solver = _solver_seed(sqlite_session)
    sqlite_session.add(solver)
    await sqlite_session.flush()

    await repo.create(sqlite_session, **_verifier_kwargs(solver.id))
    await sqlite_session.rollback()

    rows = (await sqlite_session.execute(select(VerifierSession))).all()
    assert rows == []


# ---------- get_by_id ----------


async def test_get_by_id_found_and_missing(
    sqlite_session: AsyncSession, repo: VerifierRepository
) -> None:
    solver = _solver_seed(sqlite_session)
    sqlite_session.add(solver)
    await sqlite_session.flush()

    row = await repo.create(sqlite_session, **_verifier_kwargs(solver.id))
    await sqlite_session.commit()

    found = await repo.get_by_id(sqlite_session, row.id)
    assert found is not None
    assert found.id == row.id

    missing = await repo.get_by_id(sqlite_session, uuid.uuid4())
    assert missing is None


# ---------- list + ordering ----------


async def test_list_by_solver_session_orders_by_created_at_desc_with_pagination(
    sqlite_session: AsyncSession, repo: VerifierRepository
) -> None:
    solver = _solver_seed(sqlite_session)
    sqlite_session.add(solver)
    await sqlite_session.flush()

    base = datetime(2026, 4, 1, 12, 0, 0, tzinfo=timezone.utc)
    for delta in (0, 10, 5):
        sqlite_session.add(
            VerifierSession(
                solver_session_id=solver.id,
                student_code="def f(x): return x",
                verified=True,
                status="all_passed",
                pass_count=1,
                fail_count=0,
                test_results=[],
                diagnosis="",
                sandbox_error=None,
                total_latency_ms=1,
                created_at=base + timedelta(seconds=delta),
            )
        )
    await sqlite_session.commit()

    rows = await repo.list_by_solver_session(sqlite_session, solver.id)
    timestamps = [r.created_at for r in rows]
    assert timestamps == sorted(timestamps, reverse=True)

    page1 = await repo.list_by_solver_session(sqlite_session, solver.id, limit=2, offset=0)
    page2 = await repo.list_by_solver_session(sqlite_session, solver.id, limit=2, offset=2)
    assert len(page1) == 2
    assert len(page2) == 1


# ---------- count ----------


async def test_count_by_solver_session_matches_inserted(
    sqlite_session: AsyncSession, repo: VerifierRepository
) -> None:
    solver_a = _solver_seed(sqlite_session, problem_id="a")
    solver_b = _solver_seed(sqlite_session, problem_id="b")
    sqlite_session.add_all([solver_a, solver_b])
    await sqlite_session.flush()

    for _ in range(3):
        await repo.create(sqlite_session, **_verifier_kwargs(solver_a.id))
    await repo.create(sqlite_session, **_verifier_kwargs(solver_b.id))
    await sqlite_session.commit()

    assert await repo.count_by_solver_session(sqlite_session, solver_a.id) == 3
    assert await repo.count_by_solver_session(sqlite_session, solver_b.id) == 1
    assert await repo.count_by_solver_session(sqlite_session, uuid.uuid4()) == 0
