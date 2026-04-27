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
        test_cases=[{"input": 5, "expected": 5}, {"input": 10, "expected": 55}],
        analysis="Iterate n times.",
        plan_steps=["init a=0,b=1", "loop n times", "return a"],
        code="def fib(n):\n    a,b=0,1\n    for _ in range(n): a,b=b,a+b\n    return a\n",
        explanation="O(n) time, O(1) space.",
        verified=True,
        test_results=[{"passed": True}, {"passed": True}],
        confidence=Decimal("0.95"),
    )
    defaults.update(overrides)
    return SolverSession(**defaults)


async def test_create_and_read_round_trip(session: AsyncSession) -> None:
    obj = _make_session_obj()
    session.add(obj)
    await session.commit()

    fetched = (await session.execute(select(SolverSession))).scalar_one()
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


async def test_filter_by_problem_id(session: AsyncSession) -> None:
    session.add_all(
        [
            _make_session_obj(problem_id="prob_a"),
            _make_session_obj(problem_id="prob_b"),
            _make_session_obj(problem_id="prob_a"),
        ]
    )
    await session.commit()

    rows = (
        (await session.execute(select(SolverSession).where(SolverSession.problem_id == "prob_a")))
        .scalars()
        .all()
    )
    assert len(rows) == 2
    assert all(r.problem_id == "prob_a" for r in rows)


async def test_filter_by_verified_false(session: AsyncSession) -> None:
    session.add_all(
        [
            _make_session_obj(verified=True),
            _make_session_obj(verified=False),
            _make_session_obj(verified=False),
        ]
    )
    await session.commit()

    rows = (
        (await session.execute(select(SolverSession).where(SolverSession.verified.is_(False))))
        .scalars()
        .all()
    )
    assert len(rows) == 2
    assert all(r.verified is False for r in rows)


async def test_update_verified(session: AsyncSession) -> None:
    obj = _make_session_obj(verified=False)
    session.add(obj)
    await session.commit()

    obj.verified = True
    await session.commit()

    fetched = (await session.execute(select(SolverSession))).scalar_one()
    assert fetched.verified is True


async def test_created_at_auto_populated(session: AsyncSession) -> None:
    obj = _make_session_obj()
    session.add(obj)
    await session.commit()
    await session.refresh(obj)

    assert obj.created_at is not None


async def test_jsontype_variant_round_trip(session: AsyncSession) -> None:
    """Storing nested list-of-dicts works on SQLite via the JSONType variant."""
    payload = [
        {"input": [1, 2, 3], "expected": [3, 2, 1], "meta": {"weight": 1.0}},
        {"input": [], "expected": [], "meta": {"weight": 0.5}},
    ]
    obj = _make_session_obj(test_results=payload)
    session.add(obj)
    await session.commit()

    fetched = (await session.execute(select(SolverSession))).scalar_one()
    assert fetched.test_results == payload
