"""TestClient + real PG integration tests for the hint endpoints.

HintAgent and VerifierAgent are mocked; DB is real Postgres in a per-test
schema. Validates the full route → service → repository → DB chain plus
error paths and concurrency mapping.

Marker: integration. Matches the convention of test_verify_endpoint.py /
test_solve_endpoint.py / test_sessions_endpoint.py — all PG-backed API
tests are integration-tier.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.hint.agent import HintAgent, get_hint_agent
from app.agents.hint.schemas import HintOutput
from app.agents.verifier.agent import VerifierAgent, get_verifier_agent
from app.agents.verifier.schemas import RedactedTestResult, VerifierOutput
from app.db.models import HintSession, SolverSession, VerifierSession
from app.repositories.solver_repository import SolverRepository
from app.repositories.verifier_repository import VerifierRepository

pytestmark = pytest.mark.integration


# ---------- helpers ----------


def _solver_kwargs(**overrides) -> dict:
    base = dict(
        problem_id="py-001-sum-list",
        problem_text="Return the sum of a list of integers.",
        entry_function="sum_list",
        test_cases=[{"input": "[1,2,3]", "expected": "6", "description": "basic"}],
        analysis="-",
        plan_steps=[{"step_number": 1, "action": "a", "rationale": "r"}],
        code="def sum_list(nums): return sum(nums)",
        explanation="-",
        verified=True,
        test_results=[],
        confidence=Decimal("0.9"),
        retry_used=False,
        total_latency_ms=10,
    )
    base.update(overrides)
    return base


async def _seed_solver(pg_session: AsyncSession) -> SolverSession:
    repo = SolverRepository()
    solver = await repo.create(pg_session, **_solver_kwargs())
    await pg_session.commit()
    return solver


async def _seed_verifier_failed(
    pg_session: AsyncSession, solver_id: uuid.UUID
) -> VerifierSession:
    repo = VerifierRepository()
    row = await repo.create(
        pg_session,
        solver_session_id=solver_id,
        student_code="def sum_list(nums): return 0",
        verified=False,
        status="some_failed",
        pass_count=0,
        fail_count=1,
        test_results=[
            {
                "input": "[1,2,3]",
                "actual": "0",
                "passed": False,
                "duration_ms": 1,
                "error": None,
            }
        ],
        diagnosis="Your function always returns 0 regardless of input.",
        sandbox_error=None,
        total_latency_ms=42,
    )
    await pg_session.commit()
    return row


async def _seed_verifier_passed(
    pg_session: AsyncSession, solver_id: uuid.UUID
) -> VerifierSession:
    repo = VerifierRepository()
    row = await repo.create(
        pg_session,
        solver_session_id=solver_id,
        student_code="def sum_list(nums): return sum(nums)",
        verified=True,
        status="all_passed",
        pass_count=1,
        fail_count=0,
        test_results=[
            {
                "input": "[1,2,3]",
                "actual": "6",
                "passed": True,
                "duration_ms": 1,
                "error": None,
            }
        ],
        diagnosis="",
        sandbox_error=None,
        total_latency_ms=42,
    )
    await pg_session.commit()
    return row


class _FakeHintAgent:
    def __init__(self, *, hints: list[str] | None = None):
        self._hints = list(hints) if hints else ["Generated hint."]
        self._calls = 0

    async def generate(self, _input):
        text = self._hints[self._calls] if self._calls < len(self._hints) else self._hints[-1]
        self._calls += 1
        return HintOutput(hint_text=text)


def _override_hint_agent(app: FastAPI, fake: _FakeHintAgent) -> None:
    app.dependency_overrides[get_hint_agent] = lambda: fake


# ---------- POST /hint ----------


async def test_post_hint_with_valid_failed_verifier_returns_200(
    app_with_overrides: FastAPI,
    client: TestClient,
    pg_session: AsyncSession,
) -> None:
    solver = await _seed_solver(pg_session)
    verifier = await _seed_verifier_failed(pg_session, solver.id)

    _override_hint_agent(
        app_with_overrides, _FakeHintAgent(hints=["Think about edge cases first."])
    )

    response = client.post(
        "/api/v1/hint",
        json={"verifier_session_id": str(verifier.id)},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["hint_index"] == 1
    assert body["hint_text"] == "Think about edge cases first."
    assert "session_id" in body


async def test_post_hint_with_nonexistent_verifier_returns_404(
    app_with_overrides: FastAPI,
    client: TestClient,
) -> None:
    _override_hint_agent(app_with_overrides, _FakeHintAgent())

    response = client.post(
        "/api/v1/hint",
        json={"verifier_session_id": str(uuid.uuid4())},
    )

    assert response.status_code == 404


async def test_post_hint_with_passed_verifier_returns_409(
    app_with_overrides: FastAPI,
    client: TestClient,
    pg_session: AsyncSession,
) -> None:
    solver = await _seed_solver(pg_session)
    verifier = await _seed_verifier_passed(pg_session, solver.id)

    _override_hint_agent(app_with_overrides, _FakeHintAgent())

    response = client.post(
        "/api/v1/hint",
        json={"verifier_session_id": str(verifier.id)},
    )

    assert response.status_code == 409
    assert "already passed" in response.json()["detail"].lower()


async def test_post_hint_twice_increments_index_and_records_prior_count(
    app_with_overrides: FastAPI,
    client: TestClient,
    pg_session: AsyncSession,
) -> None:
    """Second hint has hint_index=2. The diagnosis-seeding only fires when
    DB prior_hints is empty — on hint #2, hint #1 already exists in the DB,
    so the LLM sees only [hint #1] (no diagnosis re-seed) and prior_hints_count=1.
    """
    solver = await _seed_solver(pg_session)
    verifier = await _seed_verifier_failed(pg_session, solver.id)

    _override_hint_agent(
        app_with_overrides,
        _FakeHintAgent(hints=["Hint one.", "Hint two."]),
    )

    r1 = client.post("/api/v1/hint", json={"verifier_session_id": str(verifier.id)})
    assert r1.status_code == 200, r1.text
    assert r1.json()["hint_index"] == 1

    r2 = client.post("/api/v1/hint", json={"verifier_session_id": str(verifier.id)})
    assert r2.status_code == 200, r2.text
    assert r2.json()["hint_index"] == 2

    # Inspect the persisted second row directly to verify prior_hints_count
    second_id = uuid.UUID(r2.json()["session_id"])
    detail = client.get(f"/api/v1/hint-sessions/{second_id}")
    assert detail.status_code == 200
    body = detail.json()
    assert body["hint_index"] == 2
    # LLM saw only [hint #1]: no diagnosis seed because DB prior_hints
    # was non-empty when hint #2 was generated.
    assert body["prior_hints_count"] == 1


async def test_get_hint_session_found_and_missing(
    app_with_overrides: FastAPI,
    client: TestClient,
    pg_session: AsyncSession,
) -> None:
    solver = await _seed_solver(pg_session)
    verifier = await _seed_verifier_failed(pg_session, solver.id)
    _override_hint_agent(app_with_overrides, _FakeHintAgent(hints=["A hint."]))

    post = client.post(
        "/api/v1/hint", json={"verifier_session_id": str(verifier.id)}
    )
    assert post.status_code == 200
    session_id = post.json()["session_id"]

    found = client.get(f"/api/v1/hint-sessions/{session_id}")
    assert found.status_code == 200
    assert found.json()["id"] == session_id

    missing = client.get(f"/api/v1/hint-sessions/{uuid.uuid4()}")
    assert missing.status_code == 404


async def test_get_verifier_session_hints_returns_ordered_list(
    app_with_overrides: FastAPI,
    client: TestClient,
    pg_session: AsyncSession,
) -> None:
    solver = await _seed_solver(pg_session)
    verifier = await _seed_verifier_failed(pg_session, solver.id)

    _override_hint_agent(
        app_with_overrides,
        _FakeHintAgent(hints=["Hint one.", "Hint two.", "Hint three."]),
    )

    for _ in range(3):
        r = client.post(
            "/api/v1/hint", json={"verifier_session_id": str(verifier.id)}
        )
        assert r.status_code == 200, r.text

    listing = client.get(f"/api/v1/verifier-sessions/{verifier.id}/hints")
    assert listing.status_code == 200
    body = listing.json()
    assert body["total"] == 3
    assert [h["hint_index"] for h in body["items"]] == [1, 2, 3]
    assert [h["hint_text"] for h in body["items"]] == [
        "Hint one.",
        "Hint two.",
        "Hint three.",
    ]


async def test_post_hint_at_limit_returns_429(
    app_with_overrides: FastAPI,
    client: TestClient,
    pg_session: AsyncSession,
) -> None:
    """5 prior hint rows exist → service rejects the 6th attempt with 429."""
    solver = await _seed_solver(pg_session)
    verifier = await _seed_verifier_failed(pg_session, solver.id)

    # Seed 5 hint rows directly via ORM
    for i in range(1, 6):
        pg_session.add(
            HintSession(
                verifier_session_id=verifier.id,
                hint_index=i,
                hint_text=f"Existing hint {i}",
                prior_hints_count=i,
                total_latency_ms=10,
            )
        )
    await pg_session.commit()

    _override_hint_agent(app_with_overrides, _FakeHintAgent(hints=["Should not reach"]))

    response = client.post(
        "/api/v1/hint", json={"verifier_session_id": str(verifier.id)}
    )

    assert response.status_code == 429
    assert "5 hints" in response.json()["detail"] or "Maximum" in response.json()["detail"]


async def test_post_hint_concurrent_409(
    app_with_overrides: FastAPI,
    client: TestClient,
    pg_session: AsyncSession,
) -> None:
    """Force HintConcurrencyError by stubbing the service to raise after the
    agent has run. Validates the 409 mapping for the concurrency exception
    path (the unit-test layer covers the real IntegrityError retry logic).
    """
    from app.dependencies import get_hint_service
    from app.services.hint_service import HintConcurrencyError

    solver = await _seed_solver(pg_session)
    verifier = await _seed_verifier_failed(pg_session, solver.id)

    class _ConcurrentService:
        async def generate_and_persist(self, _session, _verifier_id):
            raise HintConcurrencyError("Concurrent hint requests; please retry")

    app_with_overrides.dependency_overrides[get_hint_service] = lambda: _ConcurrentService()

    response = client.post(
        "/api/v1/hint", json={"verifier_session_id": str(verifier.id)}
    )

    assert response.status_code == 409
    assert "concurrent" in response.json()["detail"].lower()


async def test_post_hint_ignores_client_supplied_prior_hints(
    app_with_overrides: FastAPI,
    client: TestClient,
    pg_session: AsyncSession,
) -> None:
    """HintRequest schema only declares verifier_session_id. Pydantic default
    ignores extra fields, so a client-supplied prior_hints list is silently
    dropped — the service composes prior_hints from the DB itself.
    """
    solver = await _seed_solver(pg_session)
    verifier = await _seed_verifier_failed(pg_session, solver.id)

    _override_hint_agent(app_with_overrides, _FakeHintAgent(hints=["A hint."]))

    response = client.post(
        "/api/v1/hint",
        json={
            "verifier_session_id": str(verifier.id),
            "prior_hints": ["FAKE CLIENT HINT 1", "FAKE CLIENT HINT 2"],
        },
    )

    assert response.status_code == 200, response.text
    # The persisted prior_hints_count reflects the seeded diagnosis (1), not
    # the 2 fake client hints. If client tampering were possible we'd see 2.
    session_id = uuid.UUID(response.json()["session_id"])
    detail = client.get(f"/api/v1/hint-sessions/{session_id}")
    assert detail.status_code == 200
    assert detail.json()["prior_hints_count"] == 1


async def test_post_hint_does_not_leak_expected_into_hint_text(
    app_with_overrides: FastAPI,
    client: TestClient,
    pg_session: AsyncSession,
) -> None:
    """Anti-leak parity with Step 4.2: the persisted hint_text must not
    contain expected values from the parent solver_session's test_cases."""
    solver = await _seed_solver(pg_session)
    verifier = await _seed_verifier_failed(pg_session, solver.id)

    _override_hint_agent(
        app_with_overrides,
        _FakeHintAgent(hints=["Think about what your function does for empty inputs."]),
    )

    response = client.post(
        "/api/v1/hint", json={"verifier_session_id": str(verifier.id)}
    )
    assert response.status_code == 200

    # The expected value from the seeded solver test_cases is "6"
    body = response.json()
    assert "expected" not in body
    # Sanity: the fake hint text doesn't contain the solver's expected value.
    # (Real anti-leak depends on the prompt — covered by agent unit tests.)
    assert body["hint_text"] == "Think about what your function does for empty inputs."
