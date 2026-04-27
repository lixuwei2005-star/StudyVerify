from __future__ import annotations

import json
import logging
from functools import lru_cache

from pydantic import TypeAdapter, ValidationError

from app.agents.solver import prompts
from app.agents.solver.schemas import PlanStep, SolverInput, SolverOutput
from app.llm.client import DeepSeekClient, get_llm_client
from app.llm.exceptions import LLMError

logger = logging.getLogger("app.agents.solver")

_PLAN_STEPS_ADAPTER = TypeAdapter(list[PlanStep])
_SNIPPET_LEN = 200


class SolverError(Exception):
    """Raised when the solver pipeline fails for any non-recoverable reason."""

    def __init__(self, step: str, problem_id: str, message: str) -> None:
        super().__init__(f"[{step}] problem_id={problem_id}: {message}")
        self.step = step
        self.problem_id = problem_id


class SolverAgent:
    """3-stage Solver: analyze → plan → code. No sandbox in this step."""

    def __init__(self, client: DeepSeekClient) -> None:
        self._client = client

    async def solve(self, request: SolverInput) -> SolverOutput:
        pid = request.problem_id
        logger.info("solver.start problem_id=%s", pid)

        analysis = await self._analyze(request)
        plan_steps = await self._plan(request, analysis)
        code, explanation = await self._code(request, plan_steps)

        confidence = self._compute_confidence(analysis, plan_steps, code)
        output = SolverOutput(
            problem_id=pid,
            analysis=analysis,
            plan_steps=plan_steps,
            code=code,
            explanation=explanation,
            confidence=confidence,
        )
        logger.info("solver.done problem_id=%s confidence=%.2f", pid, confidence)
        return output

    async def _analyze(self, request: SolverInput) -> str:
        messages = prompts.build_analyze_messages(request.problem_text, request.test_cases)
        try:
            return (await self._client.chat(messages, temperature=0.3)).strip()
        except LLMError as exc:
            raise SolverError("analyze", request.problem_id, str(exc)) from exc

    async def _plan(self, request: SolverInput, analysis: str) -> list[PlanStep]:
        messages = prompts.build_plan_messages(request.problem_text, analysis)
        try:
            raw = await self._client.chat(messages, temperature=0.2, json_mode=True)
        except LLMError as exc:
            raise SolverError("plan", request.problem_id, str(exc)) from exc
        return self._parse_plan(raw, request.problem_id)

    async def _code(self, request: SolverInput, plan_steps: list[PlanStep]) -> tuple[str, str]:
        messages = prompts.build_code_messages(request.problem_text, plan_steps, request.test_cases)
        try:
            raw = await self._client.chat(messages, temperature=0.1, json_mode=True)
        except LLMError as exc:
            raise SolverError("code", request.problem_id, str(exc)) from exc
        return self._parse_code(raw, request.problem_id)

    @staticmethod
    def _parse_plan(raw: str, problem_id: str) -> list[PlanStep]:
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise SolverError(
                "plan", problem_id, f"invalid JSON: {exc}; got: {raw[:_SNIPPET_LEN]!r}"
            ) from exc
        steps_raw = payload.get("steps") if isinstance(payload, dict) else None
        if not isinstance(steps_raw, list):
            shape = list(payload) if isinstance(payload, dict) else type(payload).__name__
            raise SolverError("plan", problem_id, f"missing 'steps' list; got {shape}")
        try:
            return _PLAN_STEPS_ADAPTER.validate_python(steps_raw)
        except ValidationError as exc:
            raise SolverError("plan", problem_id, f"plan_steps invalid: {exc}") from exc

    @staticmethod
    def _parse_code(raw: str, problem_id: str) -> tuple[str, str]:
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise SolverError(
                "code", problem_id, f"invalid JSON: {exc}; got: {raw[:_SNIPPET_LEN]!r}"
            ) from exc
        if not isinstance(payload, dict):
            raise SolverError("code", problem_id, "expected JSON object")
        code = payload.get("code")
        explanation = payload.get("explanation")
        if not isinstance(code, str) or not isinstance(explanation, str):
            raise SolverError(
                "code",
                problem_id,
                f"missing 'code' or 'explanation' string; got keys={list(payload)}",
            )
        return code, explanation

    @staticmethod
    def _compute_confidence(analysis: str, plan_steps: list[PlanStep], code: str) -> float:
        score = 1.0
        if len(analysis) < 50:
            score -= 0.2
        if len(plan_steps) <= 1:
            score -= 0.2
        if "def " not in code:
            score -= 0.3
        return max(0.0, score)


@lru_cache
def get_solver_agent() -> SolverAgent:
    return SolverAgent(get_llm_client())
