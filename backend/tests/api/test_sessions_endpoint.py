"""TestClient + real PG integration tests for the GET endpoints.

Direct repository seeding (no /solve roundtrip) so each test isolates a
single concern. The JSONB-pydantic round trip test in particular guards
against the subtle pipeline failure where DB reads come back as plain
dicts but the API model claims richer Pydantic types.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.solver_repository import SolverRepository

pytestmark = pytest.mark.integration


def _seed_kwargs(**overrides) -> dict:
    base = dict(
        problem_id="prob_api",
        problem_text="Compute something.",
        entry_function="f",
        test_cases=[
            {"input": "1", "expected": "1", "description": "trivial"},
            {"input": "2", "expected": "4", "description": "square"},
        ],
        analysis="Restate it.",
        plan_steps=[
            {"step_number": 1, "action": "do thing", "rationale": "because"},
            {"step_number": 2, "action": "return", "rationale": "result"},
        ],
        code="def f(n):\n    return n * n\n",
        explanation="square it",
        verified=True,
        test_results=[
            {
                "test_index": 0,
                "input": "1",
                "expected": "1",
                "actual": "1",
                "passed": True,
                "error": None,
                "duration_ms": 1,
            }
        ],
        confidence=0.92,
        retry_used=False,
        total_latency_ms=128,
    )
    base.update(overrides)
    return base


# ---------- GET /sessions/{id} ----------


async def test_get_session_returns_full_row(
    client: TestClient, pg_session: AsyncSession
) -> None:
    repo = SolverRepository()
    row = await repo.create(pg_session, **_seed_kwargs())
    await pg_session.commit()

    response = client.get(f"/api/v1/sessions/{row.id}")

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == str(row.id)
    assert body["problem_id"] == "prob_api"
    assert body["retry_used"] is False
    assert body["total_latency_ms"] == 128
    assert body["confidence"] == pytest.approx(0.92)
    assert "created_at" in body


async def test_get_session_returns_404_when_missing(client: TestClient) -> None:
    response = client.get(f"/api/v1/sessions/{uuid.uuid4()}")

    assert response.status_code == 404
    assert response.json()["detail"] == "Session not found"


async def test_get_session_returns_422_for_non_uuid_path(client: TestClient) -> None:
    response = client.get("/api/v1/sessions/not-a-uuid")
    assert response.status_code == 422


async def test_get_session_validates_jsonb_into_pydantic_schemas(
    client: TestClient, pg_session: AsyncSession
) -> None:
    """End-to-end proof of the from_attributes pipeline against real PG.

    The JSONB columns come out of asyncpg as plain dicts. SolverSessionOut
    declares them as nested Pydantic schemas (TestCase / PlanStep /
    TestExecutionResult). This test asserts the response payload has the
    full nested shape — not loose `dict` blobs — so OpenAPI typing is
    actually backed by data.
    """
    repo = SolverRepository()
    row = await repo.create(pg_session, **_seed_kwargs())
    await pg_session.commit()

    response = client.get(f"/api/v1/sessions/{row.id}")
    assert response.status_code == 200
    body = response.json()

    # test_cases → list[TestCase]: every item has {input, expected, description}
    assert isinstance(body["test_cases"], list) and len(body["test_cases"]) == 2
    for tc in body["test_cases"]:
        assert set(tc.keys()) == {"input", "expected", "description"}

    # plan_steps → list[PlanStep]: every item has {step_number, action, rationale}
    assert isinstance(body["plan_steps"], list) and len(body["plan_steps"]) == 2
    for ps in body["plan_steps"]:
        assert set(ps.keys()) == {"step_number", "action", "rationale"}
        assert isinstance(ps["step_number"], int)

    # test_results → list[TestExecutionResult]: full sandbox result schema
    assert isinstance(body["test_results"], list) and len(body["test_results"]) == 1
    tr = body["test_results"][0]
    assert {
        "test_index",
        "input",
        "expected",
        "actual",
        "passed",
        "error",
        "duration_ms",
    } <= set(tr.keys())


# ---------- GET /sessions ----------


async def test_list_sessions_filters_by_problem_id(
    client: TestClient, pg_session: AsyncSession
) -> None:
    repo = SolverRepository()
    await repo.create(pg_session, **_seed_kwargs(problem_id="alpha"))
    await repo.create(pg_session, **_seed_kwargs(problem_id="beta"))
    await repo.create(pg_session, **_seed_kwargs(problem_id="alpha"))
    await pg_session.commit()

    response = client.get("/api/v1/sessions", params={"problem_id": "alpha"})

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 2
    assert len(body["items"]) == 2
    assert all(item["problem_id"] == "alpha" for item in body["items"])


async def test_list_sessions_paginates_with_limit_and_offset(
    client: TestClient, pg_session: AsyncSession
) -> None:
    repo = SolverRepository()
    for _ in range(5):
        await repo.create(pg_session, **_seed_kwargs(problem_id="paginated"))
        await pg_session.commit()

    page1 = client.get(
        "/api/v1/sessions", params={"problem_id": "paginated", "limit": 2, "offset": 0}
    ).json()
    page2 = client.get(
        "/api/v1/sessions", params={"problem_id": "paginated", "limit": 2, "offset": 2}
    ).json()
    page3 = client.get(
        "/api/v1/sessions", params={"problem_id": "paginated", "limit": 2, "offset": 4}
    ).json()

    assert page1["total"] == 5
    assert page2["total"] == 5
    assert page3["total"] == 5
    assert len(page1["items"]) == 2
    assert len(page2["items"]) == 2
    assert len(page3["items"]) == 1
    assert page1["limit"] == 2 and page1["offset"] == 0
    assert page3["offset"] == 4

    # All ids unique across pages
    seen = {item["id"] for item in page1["items"] + page2["items"] + page3["items"]}
    assert len(seen) == 5


async def test_list_sessions_returns_empty_for_unknown_problem_id(
    client: TestClient,
) -> None:
    response = client.get("/api/v1/sessions", params={"problem_id": "ghost"})

    assert response.status_code == 200
    body = response.json()
    assert body["items"] == []
    assert body["total"] == 0


async def test_list_sessions_requires_problem_id(client: TestClient) -> None:
    response = client.get("/api/v1/sessions")
    assert response.status_code == 422


async def test_list_sessions_rejects_out_of_range_pagination(client: TestClient) -> None:
    too_big = client.get("/api/v1/sessions", params={"problem_id": "x", "limit": 999})
    too_small = client.get("/api/v1/sessions", params={"problem_id": "x", "offset": -1})
    assert too_big.status_code == 422
    assert too_small.status_code == 422
