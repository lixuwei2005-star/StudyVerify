"""Integration tests for VerifierRepository against real Postgres.

Tests FK ON DELETE RESTRICT behavior, JSONB round-trips, timezone-aware
created_at ordering, and pagination — things SQLite cannot fully exercise.

Marker: integration. Skipped if DATABASE_URL not set.
"""

from __future__ import annotations

import asyncio
import uuid
from decimal import Decimal

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import SolverSession, VerifierSession
from app.repositories.solver_repository import SolverRepository
from app.repositories.verifier_repository import VerifierRepository

pytestmark = pytest.mark.integration


@pytest.fixture
def repo() -> VerifierRepository:
    return VerifierRepository()


@pytest.fixture
def solver_repo() -> SolverRepository:
    return SolverRepository()


def _solver_kwargs(**overrides) -> dict:
    base = dict(
        problem_id="prob_vi",
        problem_text="Verify something.",
        entry_function="f",
        test_cases=[{"input": "1", "expected": "1", "description": "id"}],
        analysis="-",
        plan_steps=[{"step_number": 1, "action": "a", "rationale": "r"}],
        code="def f(x): return x",
        explanation="-",
        verified=True,
        test_results=[],
        confidence=0.9,
        retry_used=False,
        total_latency_ms=10,
    )
    base.update(overrides)
    return base


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


async def test_create_and_retrieve_round_trip_pg(
    pg_session: AsyncSession,
    repo: VerifierRepository,
    solver_repo: SolverRepository,
) -> None:
    solver = await solver_repo.create(pg_session, **_solver_kwargs())
    await pg_session.commit()

    row = await repo.create(pg_session, **_verifier_kwargs(solver.id))
    await pg_session.commit()
    await pg_session.refresh(row)

    assert isinstance(row.id, uuid.UUID)
    assert row.created_at is not None
    assert row.created_at.tzinfo is not None
    assert row.solver_session_id == solver.id
    assert row.verified is True
    assert row.total_latency_ms == 42
    assert row.test_results == [{"input": "1", "actual": "1", "passed": True, "duration_ms": 1, "error": None}]

    fetched = await repo.get_by_id(pg_session, row.id)
    assert fetched is not None
    assert fetched.id == row.id


async def test_fk_on_delete_restrict_blocks_solver_deletion(
    pg_session: AsyncSession,
    repo: VerifierRepository,
    solver_repo: SolverRepository,
) -> None:
    """ON DELETE RESTRICT: deleting a solver_session with child verifier_sessions must fail."""
    solver = await solver_repo.create(pg_session, **_solver_kwargs())
    await pg_session.commit()

    await repo.create(pg_session, **_verifier_kwargs(solver.id))
    await pg_session.commit()

    with pytest.raises(IntegrityError):
        await pg_session.execute(
            text("DELETE FROM solver_sessions WHERE id = :id").bindparams(id=solver.id)
        )
        await pg_session.flush()


async def test_fk_violation_with_nonexistent_solver_session_raises(
    pg_session: AsyncSession,
    repo: VerifierRepository,
) -> None:
    """Inserting a verifier_session with a bogus solver_session_id must fail."""
    with pytest.raises(IntegrityError):
        await repo.create(pg_session, **_verifier_kwargs(uuid.uuid4()))
        await pg_session.flush()


async def test_list_orders_by_created_at_desc_real_time(
    pg_session: AsyncSession,
    repo: VerifierRepository,
    solver_repo: SolverRepository,
) -> None:
    solver = await solver_repo.create(pg_session, **_solver_kwargs())
    await pg_session.commit()

    ids: list[uuid.UUID] = []
    for _ in range(3):
        row = await repo.create(pg_session, **_verifier_kwargs(solver.id))
        ids.append(row.id)
        await pg_session.commit()
        await asyncio.sleep(0.01)

    rows = await repo.list_by_solver_session(pg_session, solver.id)
    assert [r.id for r in rows] == list(reversed(ids))


async def test_pagination_limit_offset(
    pg_session: AsyncSession,
    repo: VerifierRepository,
    solver_repo: SolverRepository,
) -> None:
    solver = await solver_repo.create(pg_session, **_solver_kwargs())
    await pg_session.commit()

    for _ in range(5):
        await repo.create(pg_session, **_verifier_kwargs(solver.id))
        await pg_session.commit()
        await asyncio.sleep(0.005)

    page1 = await repo.list_by_solver_session(pg_session, solver.id, limit=2, offset=0)
    page2 = await repo.list_by_solver_session(pg_session, solver.id, limit=2, offset=2)
    page3 = await repo.list_by_solver_session(pg_session, solver.id, limit=2, offset=4)
    assert len(page1) == 2
    assert len(page2) == 2
    assert len(page3) == 1


async def test_count_by_solver_session_pg(
    pg_session: AsyncSession,
    repo: VerifierRepository,
    solver_repo: SolverRepository,
) -> None:
    solver_a = await solver_repo.create(pg_session, **_solver_kwargs(problem_id="a"))
    solver_b = await solver_repo.create(pg_session, **_solver_kwargs(problem_id="b"))
    await pg_session.commit()

    for _ in range(3):
        await repo.create(pg_session, **_verifier_kwargs(solver_a.id))
    await repo.create(pg_session, **_verifier_kwargs(solver_b.id))
    await pg_session.commit()

    assert await repo.count_by_solver_session(pg_session, solver_a.id) == 3
    assert await repo.count_by_solver_session(pg_session, solver_b.id) == 1
    assert await repo.count_by_solver_session(pg_session, uuid.uuid4()) == 0
