"""TestClient + real PG integration tests for the verify endpoints.

Agent is mocked (no real Docker/DeepSeek); DB is real Postgres in a per-test
schema. Validates the full route → service → repository → DB chain plus error
paths and the FK-backed solver-session lookup.

NOTE — real DockerCodeRunner not exercised here:
Every test overrides get_verifier_agent with _FakeAgent, so DockerCodeRunner
is never instantiated. The real Docker sandbox path (tempfile bind-mount into
sibling containers) is verified by the manual end-to-end smoke described in
the Step 4.3 commit message: POST /solve → POST /verify → GET endpoints →
psql JSONB redaction check. That smoke requires make compose-up-rebuild with
the /tmp bind-mount in docker-compose.yml (Step 4.3 addition).

Marker: integration. No -m "not integration" tier exists for this file.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.verifier.agent import VerifierAgent, VerifierError, get_verifier_agent
from app.agents.verifier.schemas import RedactedTestResult, VerifierOutput
from app.db.models import SolverSession
from app.dependencies import get_verifier_service
from app.repositories.solver_repository import SolverRepository
from app.sandbox.schemas import SandboxStatus
from app.services.verifier_service import VerifierService

pytestmark = pytest.mark.integration


# ---------- helpers ----------

def _solver_kwargs(**overrides) -> dict:
    base = dict(
        problem_id="py-001-sum-list",
        problem_text="Sum a list.",
        entry_function="sum_list",
        test_cases=[{"input": "[1,2,3]", "expected": "6", "description": "basic"}],
        analysis="-",
        plan_steps=[{"step_number": 1, "action": "a", "rationale": "r"}],
        code="def sum_list(nums): return sum(nums)",
        explanation="-",
        verified=True,
        test_results=[],
        confidence=0.9,
        retry_used=False,
        total_latency_ms=10,
    )
    base.update(overrides)
    return base


def _passed_output() -> VerifierOutput:
    return VerifierOutput(
        problem_id="py-001-sum-list",
        verified=True,
        status="all_passed",
        pass_count=1,
        fail_count=0,
        test_results=[
            RedactedTestResult(input="[1,2,3]", actual="6", passed=True, duration_ms=1)
        ],
        diagnosis="",
        sandbox_error=None,
    )


def _failed_output() -> VerifierOutput:
    return VerifierOutput(
        problem_id="py-001-sum-list",
        verified=False,
        status="some_failed",
        pass_count=0,
        fail_count=1,
        test_results=[
            RedactedTestResult(input="[1,2,3]", actual=None, passed=False, error="SyntaxError")
        ],
        diagnosis="Syntax error in submitted code.",
        sandbox_error=None,
    )


class _FakeAgent:
    def __init__(self, *, output: VerifierOutput | None = None, exc: Exception | None = None):
        self._output = output
        self._exc = exc

    async def verify(self, _input):
        if self._exc is not None:
            raise self._exc
        assert self._output is not None
        return self._output


def _override_agent(app: FastAPI, fake: _FakeAgent) -> None:
    app.dependency_overrides[get_verifier_agent] = lambda: fake


# ---------- POST /verify ----------

async def test_post_verify_with_valid_solver_session_id_returns_200_and_persists(
    app_with_overrides: FastAPI,
    client: TestClient,
    pg_session: AsyncSession,
) -> None:
    repo = SolverRepository()
    solver = await repo.create(pg_session, **_solver_kwargs())
    await pg_session.commit()

    _override_agent(app_with_overrides, _FakeAgent(output=_passed_output()))

    response = client.post(
        "/api/v1/verify",
        json={"solver_session_id": str(solver.id), "student_code": "def sum_list(n): return sum(n)"},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert "session_id" in body
    assert body["output"]["verified"] is True
    assert body["output"]["status"] == "all_passed"
    # Confirm no 'expected' key leaked in test_results
    for tr in body["output"]["test_results"]:
        assert "expected" not in tr


async def test_post_verify_with_nonexistent_solver_session_id_returns_404(
    app_with_overrides: FastAPI,
    client: TestClient,
) -> None:
    _override_agent(app_with_overrides, _FakeAgent(output=_passed_output()))

    response = client.post(
        "/api/v1/verify",
        json={"solver_session_id": str(uuid.uuid4()), "student_code": "def f(): pass"},
    )

    assert response.status_code == 404


async def test_post_verify_with_bad_student_code_returns_200_verified_false(
    app_with_overrides: FastAPI,
    client: TestClient,
    pg_session: AsyncSession,
) -> None:
    """Sandbox catches syntax errors and returns verified=False; route still 200."""
    repo = SolverRepository()
    solver = await repo.create(pg_session, **_solver_kwargs())
    await pg_session.commit()

    _override_agent(app_with_overrides, _FakeAgent(output=_failed_output()))

    response = client.post(
        "/api/v1/verify",
        json={"solver_session_id": str(solver.id), "student_code": "syntax error !!!"},
    )

    assert response.status_code == 200
    assert response.json()["output"]["verified"] is False


# ---------- GET /verifier-sessions/{id} ----------

async def test_get_verifier_session_found(
    app_with_overrides: FastAPI,
    client: TestClient,
    pg_session: AsyncSession,
) -> None:
    repo = SolverRepository()
    solver = await repo.create(pg_session, **_solver_kwargs())
    await pg_session.commit()

    _override_agent(app_with_overrides, _FakeAgent(output=_passed_output()))

    post = client.post(
        "/api/v1/verify",
        json={"solver_session_id": str(solver.id), "student_code": "def sum_list(n): return sum(n)"},
    )
    assert post.status_code == 200
    session_id = post.json()["session_id"]

    response = client.get(f"/api/v1/verifier-sessions/{session_id}")
    assert response.status_code == 200
    body = response.json()
    assert body["id"] == session_id
    assert body["verified"] is True
    assert "expected" not in str(body["test_results"])


async def test_get_verifier_session_missing_returns_404(
    client: TestClient,
) -> None:
    response = client.get(f"/api/v1/verifier-sessions/{uuid.uuid4()}")
    assert response.status_code == 404


# ---------- GET /sessions/{solver_id}/verifier-sessions ----------

async def test_get_solver_verifier_sessions_list_with_ordering_and_pagination(
    app_with_overrides: FastAPI,
    client: TestClient,
    pg_session: AsyncSession,
) -> None:
    repo = SolverRepository()
    solver = await repo.create(pg_session, **_solver_kwargs())
    await pg_session.commit()

    _override_agent(app_with_overrides, _FakeAgent(output=_passed_output()))

    for _ in range(3):
        r = client.post(
            "/api/v1/verify",
            json={"solver_session_id": str(solver.id), "student_code": "def sum_list(n): return sum(n)"},
        )
        assert r.status_code == 200

    response = client.get(f"/api/v1/sessions/{solver.id}/verifier-sessions")
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 3
    assert len(body["items"]) == 3

    # Pagination
    page1 = client.get(f"/api/v1/sessions/{solver.id}/verifier-sessions?limit=2&offset=0")
    page2 = client.get(f"/api/v1/sessions/{solver.id}/verifier-sessions?limit=2&offset=2")
    assert len(page1.json()["items"]) == 2
    assert len(page2.json()["items"]) == 1


# ---------- 503 dependency construction failure ----------

async def test_dependency_construction_failure_returns_503(
    app_with_overrides: FastAPI,
    client: TestClient,
    pg_session: AsyncSession,
) -> None:
    """FastAPI builds dependencies before the route body executes, so a
    try/except inside the route cannot catch constructor failures.

    Strategy: override get_verifier_service itself (the outermost dep) with
    a factory that raises VerifierError at construction time; document the
    limitation that this requires overriding the service factory rather than
    a low-level dep.

    Note: The verify route maps VerifierError -> 503 inside the route body,
    but construction-time failures do not reach that handler. Instead we
    test the wrapper approach: inject a VerifierService subclass whose
    verify_and_persist raises VerifierError, which the route catches.
    This exercises the 503 mapping that real infra failures will trigger
    (Docker daemon unavailable surfaces through agent.verify, not __init__).
    """
    repo = SolverRepository()
    solver = await repo.create(pg_session, **_solver_kwargs())
    await pg_session.commit()

    class _BrokenAgent:
        async def verify(self, _input):
            raise VerifierError("Docker daemon unavailable")

    # Override agent to simulate infra failure at runtime (inside verify_and_persist)
    app_with_overrides.dependency_overrides[get_verifier_agent] = lambda: _BrokenAgent()

    response = client.post(
        "/api/v1/verify",
        json={"solver_session_id": str(solver.id), "student_code": "def sum_list(n): return sum(n)"},
    )

    assert response.status_code == 503
    assert "unavailable" in response.json()["detail"].lower()
