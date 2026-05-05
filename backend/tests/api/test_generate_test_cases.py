"""TestClient tests for POST /api/v1/generate-test-cases.

The service is dependency-overridden — no DB or LLM is touched. Validation
errors (422) come from FastAPI/Pydantic before the service is invoked, so
they need no override.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

from fastapi.testclient import TestClient

from app.agents.solver.schemas import TestCase
from app.dependencies import get_test_case_generator_service
from app.llm.exceptions import LLMTimeoutError
from app.main import app
from app.services.test_case_generator import TestCaseGeneratorError

SAMPLE_BODY = {
    "problem_text": "Implement sum_list(nums) returning the sum of an integer list, or 0 if empty.",
    "entry_function": "sum_list",
    "n": 3,
}


def _override_service(service_mock: AsyncMock) -> None:
    app.dependency_overrides[get_test_case_generator_service] = lambda: service_mock


def _clear_overrides() -> None:
    app.dependency_overrides.clear()


# ---------- 200 OK ----------


def test_returns_200_with_valid_request() -> None:
    fake_cases = [
        TestCase(input="[1,2,3]", expected="6", description="basic"),
        TestCase(input="[]", expected="0", description="empty"),
        TestCase(input="[42]", expected="42", description="single element"),
    ]
    service_mock = AsyncMock()
    service_mock.generate = AsyncMock(return_value=fake_cases)
    _override_service(service_mock)
    try:
        client = TestClient(app)
        response = client.post("/api/v1/generate-test-cases", json=SAMPLE_BODY)
    finally:
        _clear_overrides()

    assert response.status_code == 200, response.text
    body = response.json()
    assert len(body["test_cases"]) == 3
    assert body["test_cases"][0] == {"input": "[1,2,3]", "expected": "6", "description": "basic"}
    service_mock.generate.assert_awaited_once_with(
        problem_text=SAMPLE_BODY["problem_text"],
        entry_function="sum_list",
        n=3,
    )


# ---------- 422 validation errors (no service override needed) ----------


def test_returns_422_for_bad_function_name_pattern() -> None:
    client = TestClient(app)
    bad_body = {**SAMPLE_BODY, "entry_function": "BadName"}  # uppercase rejected
    response = client.post("/api/v1/generate-test-cases", json=bad_body)
    assert response.status_code == 422
    assert any(
        err["loc"][-1] == "entry_function" for err in response.json()["detail"]
    )


def test_returns_422_for_too_short_problem_text() -> None:
    client = TestClient(app)
    bad_body = {**SAMPLE_BODY, "problem_text": "short"}  # under min_length=10
    response = client.post("/api/v1/generate-test-cases", json=bad_body)
    assert response.status_code == 422
    assert any(
        err["loc"][-1] == "problem_text" for err in response.json()["detail"]
    )


# ---------- error mappings ----------


def test_returns_502_when_service_raises_generator_error() -> None:
    service_mock = AsyncMock()
    service_mock.generate = AsyncMock(
        side_effect=TestCaseGeneratorError("malformed JSON after retry")
    )
    _override_service(service_mock)
    try:
        client = TestClient(app)
        response = client.post("/api/v1/generate-test-cases", json=SAMPLE_BODY)
    finally:
        _clear_overrides()

    assert response.status_code == 502
    assert "malformed JSON after retry" in response.json()["detail"]


def test_returns_504_when_llm_times_out() -> None:
    service_mock = AsyncMock()
    service_mock.generate = AsyncMock(side_effect=LLMTimeoutError("upstream slow"))
    _override_service(service_mock)
    try:
        client = TestClient(app)
        response = client.post("/api/v1/generate-test-cases", json=SAMPLE_BODY)
    finally:
        _clear_overrides()

    assert response.status_code == 504
    assert response.json()["detail"] == "LLM provider timed out"
