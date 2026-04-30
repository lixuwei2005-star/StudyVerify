"""SolverSession ORM tests against in-memory SQLite (aiosqlite).

These cover the data-layer contract that Step 3.3 will rely on: round-trip,
indexed lookups, JSONType variant, and server-default timestamps.
"""

import uuid
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import SolverSession


def _make_session_obj(**overrides) -> SolverSession:
    defaults = dict(
        problem_id="prob_001",
        problem_text="Compute fib(n).",
        entry_function="fib",
        test_cases=[{"input": 5, "expected": 5}, {"input": 10, "expected": 55}],
        analysis="Iterate n times.",
        plan_steps=["init a=0,b=1", "loop n times", "return a"],
        code="def fib(n):\n    a,b=0,1\n    for _ in range(n): a,b=b,a+b\n    return a\n",
        explanation="O(n) time, O(1) space.",
        verified=True,
        test_results=[{"passed": True}, {"passed": True}],
        confidence=Decimal("0.95"),
        retry_used=False,
        total_latency_ms=1234,
    )
    defaults.update(overrides)
    return SolverSession(**defaults)


async def test_create_and_read_round_trip(sqlite_session: AsyncSession) -> None:
    obj = _make_session_obj()
    sqlite_session.add(obj)
    await sqlite_session.commit()

    fetched = (await sqlite_session.execute(select(SolverSession))).scalar_one()
    assert isinstance(fetched.id, uuid.UUID)
    assert fetched.problem_id == "prob_001"
    assert fetched.problem_text == "Compute fib(n)."
    assert fetched.test_cases == [
        {"input": 5, "expected": 5},
        {"input": 10, "expected": 55},
    ]
    assert fetched.plan_steps == ["init a=0,b=1", "loop n times", "return a"]
    assert fetched.verified is True
    assert fetched.confidence == Decimal("0.95")
    assert fetched.retry_used is False
    assert fetched.total_latency_ms == 1234


async def test_filter_by_problem_id(sqlite_session: AsyncSession) -> None:
    sqlite_session.add_all(
        [
            _make_session_obj(problem_id="prob_a"),
            _make_session_obj(problem_id="prob_b"),
            _make_session_obj(problem_id="prob_a"),
        ]
    )
    await sqlite_session.commit()

    rows = (
        (
            await sqlite_session.execute(
                select(SolverSession).where(SolverSession.problem_id == "prob_a")
            )
        )
        .scalars()
        .all()
    )
    assert len(rows) == 2
    assert all(r.problem_id == "prob_a" for r in rows)


async def test_filter_by_verified_false(sqlite_session: AsyncSession) -> None:
    sqlite_session.add_all(
        [
            _make_session_obj(verified=True),
            _make_session_obj(verified=False),
            _make_session_obj(verified=False),
        ]
    )
    await sqlite_session.commit()

    rows = (
        (
            await sqlite_session.execute(
                select(SolverSession).where(SolverSession.verified.is_(False))
            )
        )
        .scalars()
        .all()
    )
    assert len(rows) == 2
    assert all(r.verified is False for r in rows)


async def test_update_verified(sqlite_session: AsyncSession) -> None:
    obj = _make_session_obj(verified=False)
    sqlite_session.add(obj)
    await sqlite_session.commit()

    obj.verified = True
    await sqlite_session.commit()

    fetched = (await sqlite_session.execute(select(SolverSession))).scalar_one()
    assert fetched.verified is True


async def test_created_at_auto_populated(sqlite_session: AsyncSession) -> None:
    obj = _make_session_obj()
    sqlite_session.add(obj)
    await sqlite_session.commit()
    await sqlite_session.refresh(obj)

    assert obj.created_at is not None


async def test_jsontype_variant_round_trip(sqlite_session: AsyncSession) -> None:
    """Storing nested list-of-dicts works on SQLite via the JSONType variant."""
    payload = [
        {"input": [1, 2, 3], "expected": [3, 2, 1], "meta": {"weight": 1.0}},
        {"input": [], "expected": [], "meta": {"weight": 0.5}},
    ]
    obj = _make_session_obj(test_results=payload)
    sqlite_session.add(obj)
    await sqlite_session.commit()

    fetched = (await sqlite_session.execute(select(SolverSession))).scalar_one()
    assert fetched.test_results == payload


async def test_retry_used_true_round_trip(sqlite_session: AsyncSession) -> None:
    obj = _make_session_obj(retry_used=True, total_latency_ms=9876)
    sqlite_session.add(obj)
    await sqlite_session.commit()

    fetched = (await sqlite_session.execute(select(SolverSession))).scalar_one()
    assert fetched.retry_used is True
    assert fetched.total_latency_ms == 9876
