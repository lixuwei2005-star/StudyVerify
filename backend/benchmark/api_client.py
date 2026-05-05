"""Async client for the three production endpoints used by the benchmark.

Wraps httpx with a uniform CallResult dict so callers can treat success and
failure paths identically. The gateway already handles retry inside the
backend; this client adds none of its own.
"""

from __future__ import annotations

import time
from typing import Any, TypedDict

import httpx

API_BASE = "https://api.005917.xyz"


class CallResult(TypedDict):
    success: bool
    latency_ms: int
    data: dict[str, Any] | None
    error: str | None


def _now_ms(start: float) -> int:
    return int((time.perf_counter() - start) * 1000)


class StudyVerifyAPI:
    def __init__(self, base_url: str = API_BASE, timeout: float = 90.0) -> None:
        self._client = httpx.AsyncClient(base_url=base_url, timeout=timeout)

    async def solve(self, problem: dict[str, Any]) -> CallResult:
        body = {
            "problem_id": problem["id"],
            "problem_text": problem["problem_text"],
            "entry_function": problem["entry_function"],
            "test_cases": problem["test_cases"],
        }
        return await self._post("/api/v1/solve", body)

    async def verify(self, solver_session_id: str, student_code: str) -> CallResult:
        body = {"solver_session_id": solver_session_id, "student_code": student_code}
        return await self._post("/api/v1/verify", body)

    async def hint(self, verifier_session_id: str) -> CallResult:
        body = {"verifier_session_id": verifier_session_id}
        return await self._post("/api/v1/hint", body)

    async def _post(self, path: str, body: dict[str, Any]) -> CallResult:
        start = time.perf_counter()
        try:
            res = await self._client.post(path, json=body)
            ms = _now_ms(start)
            if res.status_code == 200:
                return {"success": True, "latency_ms": ms, "data": res.json(), "error": None}
            return {
                "success": False,
                "latency_ms": ms,
                "data": None,
                "error": f"HTTP {res.status_code}: {res.text[:200]}",
            }
        except Exception as e:
            return {
                "success": False,
                "latency_ms": _now_ms(start),
                "data": None,
                "error": f"{type(e).__name__}: {e}",
            }

    async def close(self) -> None:
        await self._client.aclose()
