"""Integration tests for SolverSession against real Postgres.

Each test runs in a fresh `test_<uuid>` schema (via the shared `pg_session`
fixture in tests/conftest.py) that is dropped at teardown, so production
tables in the configured database are never touched.

Skip behavior: skipped if DATABASE_URL is empty.
Marker: integration (run with `-m integration`).
"""

import uuid
from decimal import Decimal

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import SolverSession

pytestmark = pytest.mark.integration


async def test_create_and_read_against_postgres(pg_session: AsyncSession) -> None:
    obj = SolverSession(
        problem_id="pg_int_001",
        problem_text="Real Postgres round trip.",
        test_cases=[{"input": 1, "expected": 1}],
        analysis="trivial",
        plan_steps=["return n"],
        code="def f(n):\n    return n\n",
        explanation="identity",
        verified=True,
        test_results=[{"passed": True}],
        confidence=Decimal("0.99"),
        retry_used=True,
        total_latency_ms=4242,
    )
    pg_session.add(obj)
    await pg_session.commit()

    fetched = (await pg_session.execute(select(SolverSession))).scalar_one()
    assert fetched.problem_id == "pg_int_001"
    assert fetched.confidence == Decimal("0.99")
    assert fetched.retry_used is True
    assert fetched.total_latency_ms == 4242


async def test_jsonb_storage_round_trip(pg_session: AsyncSession) -> None:
    payload = [
        {"input": [1, 2, 3], "expected": [3, 2, 1], "tags": {"k": "v"}},
        {"input": [], "expected": []},
    ]
    obj = SolverSession(
        problem_id="pg_int_002",
        problem_text="JSONB nested round trip.",
        test_cases=payload,
        analysis="-",
        plan_steps=["-"],
        code="-",
        explanation="-",
        verified=False,
        test_results=payload,
        confidence=Decimal("0.10"),
        retry_used=False,
        total_latency_ms=0,
    )
    pg_session.add(obj)
    await pg_session.commit()

    fetched = (await pg_session.execute(select(SolverSession))).scalar_one()
    assert fetched.test_cases == payload
    assert fetched.test_results == payload


async def test_uuid_is_native(pg_session: AsyncSession) -> None:
    """Verify the id column is a real Postgres uuid, not CHAR/TEXT."""
    obj = SolverSession(
        problem_id="pg_int_003",
        problem_text="-",
        test_cases=[],
        analysis="-",
        plan_steps=[],
        code="-",
        explanation="-",
        verified=True,
        test_results=[],
        confidence=Decimal("1.00"),
        retry_used=False,
        total_latency_ms=0,
    )
    pg_session.add(obj)
    await pg_session.commit()

    result = await pg_session.execute(
        text(
            "SELECT data_type FROM information_schema.columns "
            "WHERE table_schema = current_schema() "
            "AND table_name = 'solver_sessions' "
            "AND column_name = 'id'"
        )
    )
    data_type = result.scalar_one()
    assert data_type == "uuid"

    fetched = (await pg_session.execute(select(SolverSession))).scalar_one()
    assert isinstance(fetched.id, uuid.UUID)
