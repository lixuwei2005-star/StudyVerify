"""TestClient + real PG integration tests for POST /api/v1/solve.

The agent is mocked (no real DeepSeek calls); the DB is real Postgres
inside a per-test schema. This validates the full route → service →
repository → DB chain plus the rollback path when the agent raises.

Marker: integration. No -m "not integration" tier exists for this file —
the whole point is the real-DB persistence assertion, and a SQLite-only
flavor would not exercise asyncpg/JSONB.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.solver import SolverError
from app.agents.solver.agent import get_solver_agent
from app.agents.solver.schemas import PlanStep, SolverInput, SolverOutput
from app.db.models import SolverSession
from app.llm.exceptions import LLMTimeoutError
from app.sandbox.schemas import TestExecutionResult

pytestmark = pytest.mark.integration


SAMPLE_INPUT = {
    "problem_id": "py-001-sum-list",
    "problem_text": "Write sum_list(nums) returning the sum, or 0 if empty.",
    "test_cases": [
        {"input": "[1,2,3]", "expected": "6", "description": "basic"},
        {"input": "[]", "expected": "0", "description": "empty"},
    ],
}


def _canned_output(retry_used: bool = False) -> SolverOutput:
    return SolverOutput(
        problem_id="py-001-sum-list",
        entry_function="sum_list",
        analysis="Sum the elements; return 0 for an empty list.",
        plan_steps=[
            PlanStep(step_number=1, action="define sum_list(nums)", rationale="signature"),
            PlanStep(step_number=2, action="return sum(nums)", rationale="builtin"),
        ],
        code="def sum_list(nums):\n    return sum(nums)\n",
        explanation="Use the builtin sum.",
        confidence=0.9,
        verified=True,
        test_results=[
            TestExecutionResult(
                test_index=0,
                input="[1,2,3]",
                expected="6",
                actual="6",
                passed=True,
                error=None,
                duration_ms=1,
            ),
            TestExecutionResult(
                test_index=1,
                input="[]",
                expected="0",
                actual="0",
                passed=True,
                error=None,
                duration_ms=1,
            ),
        ],
        retry_used=retry_used,
    )


class _FakeAgent:
    """Stands in for SolverAgent. Either yields a canned SolverOutput or
    raises a pre-supplied exception, depending on what the test needs."""

    def __init__(self, *, output: SolverOutput | None = None, exc: Exception | None = None):
        self._output = output
        self._exc = exc

    async def solve(self, _: SolverInput) -> SolverOutput:
        if self._exc is not None:
            raise self._exc
        assert self._output is not None
        return self._output


def _override_agent(app: FastAPI, fake: _FakeAgent) -> None:
    app.dependency_overrides[get_solver_agent] = lambda: fake


# ---------- happy path ----------


async def test_solve_persists_row_and_returns_session_id(
    app_with_overrides: FastAPI,
    client: TestClient,
    pg_session: AsyncSession,
) -> None:
    _override_agent(app_with_overrides, _FakeAgent(output=_canned_output()))

    response = client.post("/api/v1/solve", json=SAMPLE_INPUT)

    assert response.status_code == 200, response.text
    body = response.json()
    assert "session_id" in body
    assert "output" in body
    assert body["output"]["problem_id"] == "py-001-sum-list"
    assert body["output"]["retry_used"] is False
    assert body["output"]["verified"] is True

    rows = (await pg_session.execute(select(SolverSession))).scalars().all()
    assert len(rows) == 1
    row = rows[0]
    assert str(row.id) == body["session_id"]
    assert row.problem_id == "py-001-sum-list"
    assert row.retry_used is False
    assert row.total_latency_ms >= 0


async def test_solve_persists_retry_used_true_when_agent_reports_retry(
    app_with_overrides: FastAPI,
    client: TestClient,
    pg_session: AsyncSession,
) -> None:
    _override_agent(app_with_overrides, _FakeAgent(output=_canned_output(retry_used=True)))

    response = client.post("/api/v1/solve", json=SAMPLE_INPUT)

    assert response.status_code == 200
    assert response.json()["output"]["retry_used"] is True

    row = (await pg_session.execute(select(SolverSession))).scalar_one()
    assert row.retry_used is True


# ---------- error mappings ----------


async def test_solve_maps_solver_error_to_502(
    app_with_overrides: FastAPI,
    client: TestClient,
) -> None:
    _override_agent(
        app_with_overrides,
        _FakeAgent(exc=SolverError("plan", "py-001-sum-list", "boom")),
    )

    response = client.post("/api/v1/solve", json=SAMPLE_INPUT)

    assert response.status_code == 502
    assert "boom" in response.json()["detail"]


async def test_solve_maps_llm_timeout_to_504(
    app_with_overrides: FastAPI,
    client: TestClient,
) -> None:
    _override_agent(app_with_overrides, _FakeAgent(exc=LLMTimeoutError("upstream slow")))

    response = client.post("/api/v1/solve", json=SAMPLE_INPUT)

    assert response.status_code == 504
    assert response.json()["detail"] == "LLM provider timed out"


# ---------- end-to-end rollback ----------


async def test_solve_does_not_persist_row_when_agent_raises(
    app_with_overrides: FastAPI,
    client: TestClient,
    pg_session: AsyncSession,
) -> None:
    """Full-chain rollback: route → service exception → get_db_session
    rollback handler → no row in solver_sessions."""
    _override_agent(
        app_with_overrides,
        _FakeAgent(exc=SolverError("analyze", "py-001-sum-list", "kaboom")),
    )

    response = client.post("/api/v1/solve", json=SAMPLE_INPUT)
    assert response.status_code == 502

    rows = (await pg_session.execute(select(SolverSession))).scalars().all()
    assert rows == []
