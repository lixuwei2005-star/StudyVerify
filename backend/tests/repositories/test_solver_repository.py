"""Unit tests for SolverRepository against in-memory SQLite.

These exercise pure DB-access behavior: shape of rows returned, ordering,
pagination, count, and the flush-not-commit transaction invariant. The
Postgres-specific equivalents live alongside under -m integration.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import SolverSession
from app.repositories.solver_repository import SolverRepository


@pytest.fixture
def repo() -> SolverRepository:
    return SolverRepository()


def _create_kwargs(**overrides) -> dict:
    base = dict(
        problem_id="prob_x",
        problem_text="text",
        entry_function="f",
        test_cases=[{"input": "1", "expected": "1", "description": "id"}],
        analysis="analysis",
        plan_steps=[{"step_number": 1, "action": "a", "rationale": "r"}],
        code="def f(x):\n    return x\n",
        explanation="identity",
        verified=True,
        test_results=[{"test_index": 0, "passed": True}],
        confidence=0.9,
        retry_used=False,
        total_latency_ms=42,
    )
    base.update(overrides)
    return base


def _seed_row(problem_id: str, created_at: datetime, **overrides) -> SolverSession:
    """Direct ORM construction so callers can pin created_at for ordering tests
    (SolverRepository.create relies on the server default, which can collide
    on fast inserts in SQLite)."""
    return SolverSession(
        problem_id=problem_id,
        problem_text="-",
        entry_function="f",
        test_cases=[],
        analysis="-",
        plan_steps=[],
        code="-",
        explanation="-",
        verified=True,
        test_results=[],
        confidence=Decimal("0.50"),
        retry_used=False,
        total_latency_ms=0,
        created_at=created_at,
        **overrides,
    )


# ---------- create ----------


async def test_create_persists_row_and_returns_id_after_flush(
    sqlite_session: AsyncSession, repo: SolverRepository
) -> None:
    row = await repo.create(sqlite_session, **_create_kwargs(problem_id="prob_a"))
    assert isinstance(row.id, uuid.UUID)

    await sqlite_session.commit()
    fetched = (await sqlite_session.execute(select(SolverSession))).scalar_one()
    assert fetched.id == row.id
    assert fetched.problem_id == "prob_a"
    assert fetched.retry_used is False
    assert fetched.total_latency_ms == 42


async def test_create_flushes_but_does_not_commit(
    sqlite_session: AsyncSession, repo: SolverRepository
) -> None:
    """Repository owns no transaction boundary. After create() the row is
    visible inside the open transaction (flushed) but a rollback wipes it,
    proving Service is responsible for commit."""
    await repo.create(sqlite_session, **_create_kwargs(problem_id="prob_b"))
    await sqlite_session.rollback()

    fetched = (await sqlite_session.execute(select(SolverSession))).all()
    assert fetched == []


# ---------- get_by_id ----------


async def test_get_by_id_returns_row_when_present(
    sqlite_session: AsyncSession, repo: SolverRepository
) -> None:
    row = await repo.create(sqlite_session, **_create_kwargs())
    await sqlite_session.commit()

    fetched = await repo.get_by_id(sqlite_session, row.id)
    assert fetched is not None
    assert fetched.id == row.id


async def test_get_by_id_returns_none_when_missing(
    sqlite_session: AsyncSession, repo: SolverRepository
) -> None:
    fetched = await repo.get_by_id(sqlite_session, uuid.uuid4())
    assert fetched is None


# ---------- list_by_problem ----------


async def test_list_by_problem_orders_created_at_desc(
    sqlite_session: AsyncSession, repo: SolverRepository
) -> None:
    base = datetime(2026, 4, 1, 12, 0, 0, tzinfo=timezone.utc)
    sqlite_session.add_all(
        [
            _seed_row("p1", base + timedelta(seconds=0)),
            _seed_row("p1", base + timedelta(seconds=10)),
            _seed_row("p1", base + timedelta(seconds=5)),
        ]
    )
    await sqlite_session.commit()

    rows = await repo.list_by_problem(sqlite_session, "p1")
    timestamps = [r.created_at for r in rows]
    assert timestamps == sorted(timestamps, reverse=True)


async def test_list_by_problem_filters_problem_id(
    sqlite_session: AsyncSession, repo: SolverRepository
) -> None:
    base = datetime(2026, 4, 1, 12, 0, 0, tzinfo=timezone.utc)
    sqlite_session.add_all(
        [
            _seed_row("alpha", base),
            _seed_row("beta", base),
            _seed_row("alpha", base),
        ]
    )
    await sqlite_session.commit()

    rows = await repo.list_by_problem(sqlite_session, "alpha")
    assert len(rows) == 2
    assert all(r.problem_id == "alpha" for r in rows)


async def test_list_by_problem_respects_limit_and_offset(
    sqlite_session: AsyncSession, repo: SolverRepository
) -> None:
    base = datetime(2026, 4, 1, 12, 0, 0, tzinfo=timezone.utc)
    # 5 rows, increasing timestamps → DESC order is row4, row3, row2, row1, row0
    sqlite_session.add_all(
        [_seed_row("p", base + timedelta(seconds=i)) for i in range(5)]
    )
    await sqlite_session.commit()

    page1 = await repo.list_by_problem(sqlite_session, "p", limit=2, offset=0)
    page2 = await repo.list_by_problem(sqlite_session, "p", limit=2, offset=2)
    page3 = await repo.list_by_problem(sqlite_session, "p", limit=2, offset=4)

    assert len(page1) == 2
    assert len(page2) == 2
    assert len(page3) == 1
    # page1 holds the two newest, page3 holds the oldest. Strip tz before
    # comparison: SQLite drops tzinfo on read, but Postgres preserves it —
    # assertions on relative ordering hold across both, and the absolute
    # equality below is on naive components only.
    page1_t = [r.created_at.replace(tzinfo=None) for r in page1]
    page2_t = [r.created_at.replace(tzinfo=None) for r in page2]
    page3_t = [r.created_at.replace(tzinfo=None) for r in page3]
    assert page1_t[0] > page1_t[1] > page2_t[0]
    assert page3_t[0] == base.replace(tzinfo=None)


async def test_list_by_problem_empty_when_no_match(
    sqlite_session: AsyncSession, repo: SolverRepository
) -> None:
    rows = await repo.list_by_problem(sqlite_session, "nonexistent")
    assert rows == []


# ---------- count_by_problem ----------


async def test_count_by_problem_counts_only_matching_rows(
    sqlite_session: AsyncSession, repo: SolverRepository
) -> None:
    base = datetime(2026, 4, 1, 12, 0, 0, tzinfo=timezone.utc)
    sqlite_session.add_all(
        [
            _seed_row("alpha", base),
            _seed_row("alpha", base),
            _seed_row("alpha", base),
            _seed_row("beta", base),
        ]
    )
    await sqlite_session.commit()

    assert await repo.count_by_problem(sqlite_session, "alpha") == 3
    assert await repo.count_by_problem(sqlite_session, "beta") == 1
    assert await repo.count_by_problem(sqlite_session, "missing") == 0
