"""Integration tests for SolverRepository against real Postgres.

Validates behavior that SQLite cannot fully exercise: timezone-aware
created_at ordering, native uuid id, and JSONB round-trips through the
full async-pg driver stack. Schema-isolated via the `pg_session` fixture.
"""

from __future__ import annotations

import asyncio
import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.solver_repository import SolverRepository

pytestmark = pytest.mark.integration


@pytest.fixture
def repo() -> SolverRepository:
    return SolverRepository()


def _create_kwargs(**overrides) -> dict:
    base = dict(
        problem_id="prob_pg",
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


async def test_create_round_trip_against_postgres(
    pg_session: AsyncSession, repo: SolverRepository
) -> None:
    row = await repo.create(pg_session, **_create_kwargs(retry_used=True, total_latency_ms=1234))
    await pg_session.commit()
    await pg_session.refresh(row)

    assert isinstance(row.id, uuid.UUID)
    assert row.created_at is not None
    assert row.created_at.tzinfo is not None  # Postgres returns tz-aware
    assert row.retry_used is True
    assert row.total_latency_ms == 1234


async def test_get_by_id_round_trip_against_postgres(
    pg_session: AsyncSession, repo: SolverRepository
) -> None:
    row = await repo.create(pg_session, **_create_kwargs())
    await pg_session.commit()

    fetched = await repo.get_by_id(pg_session, row.id)
    assert fetched is not None
    assert fetched.id == row.id

    missing = await repo.get_by_id(pg_session, uuid.uuid4())
    assert missing is None


async def test_list_by_problem_orders_desc_against_postgres(
    pg_session: AsyncSession, repo: SolverRepository
) -> None:
    """Real Postgres NOW() resolves to microseconds; insert with small sleeps
    so created_at values are strictly ordered."""
    ids: list[uuid.UUID] = []
    for _ in range(3):
        row = await repo.create(pg_session, **_create_kwargs(problem_id="ord_test"))
        ids.append(row.id)
        await pg_session.commit()
        await asyncio.sleep(0.01)

    rows = await repo.list_by_problem(pg_session, "ord_test")
    assert [r.id for r in rows] == list(reversed(ids))


async def test_list_by_problem_pagination_against_postgres(
    pg_session: AsyncSession, repo: SolverRepository
) -> None:
    for _ in range(5):
        await repo.create(pg_session, **_create_kwargs(problem_id="pg_paginate"))
        await pg_session.commit()
        await asyncio.sleep(0.005)

    page1 = await repo.list_by_problem(pg_session, "pg_paginate", limit=2, offset=0)
    page2 = await repo.list_by_problem(pg_session, "pg_paginate", limit=2, offset=2)
    page3 = await repo.list_by_problem(pg_session, "pg_paginate", limit=2, offset=4)
    assert len(page1) == 2
    assert len(page2) == 2
    assert len(page3) == 1


async def test_count_by_problem_against_postgres(
    pg_session: AsyncSession, repo: SolverRepository
) -> None:
    for _ in range(3):
        await repo.create(pg_session, **_create_kwargs(problem_id="pg_count_a"))
    await repo.create(pg_session, **_create_kwargs(problem_id="pg_count_b"))
    await pg_session.commit()

    assert await repo.count_by_problem(pg_session, "pg_count_a") == 3
    assert await repo.count_by_problem(pg_session, "pg_count_b") == 1
    assert await repo.count_by_problem(pg_session, "pg_count_missing") == 0
