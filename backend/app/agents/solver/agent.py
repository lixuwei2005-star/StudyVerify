from __future__ import annotations

import json
import logging
from functools import lru_cache

from pydantic import TypeAdapter, ValidationError

from app.agents.solver import prompts
from app.agents.solver.extraction import EntryFunctionExtractionError, extract_entry_function
from app.agents.solver.schemas import PlanStep, SolverInput, SolverOutput
from app.core.config import get_settings
from app.llm.client import DeepSeekClient, get_llm_client
from app.llm.exceptions import LLMError
from app.sandbox.runner import PythonSubprocessRunner, get_sandbox_runner
from app.sandbox.schemas import SandboxRunRequest, SandboxRunResult

logger = logging.getLogger("app.agents.solver")

_PLAN_STEPS_ADAPTER = TypeAdapter(list[PlanStep])
_SNIPPET_LEN = 200

_UNVERIFIED_CONFIDENCE_CAP = 0.4
_RETRIED_CONFIDENCE_CAP = 0.85


class SolverError(Exception):
    """Raised when the solver pipeline fails for any non-recoverable reason."""

    def __init__(self, step: str, problem_id: str, message: str) -> None:
        super().__init__(f"[{step}] problem_id={problem_id}: {message}")
        self.step = step
        self.problem_id = problem_id


class SolverAgent:
    """4-stage Solver: analyze → plan → code → sandbox-verify (retry-once)."""

    def __init__(
        self,
        client: DeepSeekClient,
        runner: PythonSubprocessRunner,
        sandbox_timeout_seconds: int = 5,
        sandbox_memory_mb: int = 128,
    ) -> None:
        self._client = client
        self._runner = runner
        self._sandbox_timeout_seconds = sandbox_timeout_seconds
        self._sandbox_memory_mb = sandbox_memory_mb

    async def solve(self, request: SolverInput) -> SolverOutput:
        pid = request.problem_id
        logger.info("solver.start problem_id=%s", pid)

        analysis = await self._analyze(request)
        plan_steps = await self._plan(request, analysis)
        code, explanation = await self._code(request, plan_steps)

        test_payload = [tc.model_dump() for tc in request.test_cases]
        entry_function = self._extract_entry_function(code, pid)
        sandbox_result = await self._run_sandbox(code, entry_function, test_payload)

        retry_used = False
        if self._should_retry(sandbox_result):
            logger.info(
                "solver.retry_code problem_id=%s prior_status=%s", pid, sandbox_result.status
            )
            retry_used = True
            code, explanation = await self._code_retry(request, plan_steps, code, sandbox_result)
            entry_function = self._extract_entry_function(code, pid)
            sandbox_result = await self._run_sandbox(code, entry_function, test_payload)

        verified = sandbox_result.status == "all_passed"
        confidence = self._compute_confidence(
            analysis, plan_steps, code, verified=verified, retry_used=retry_used
        )
        output = SolverOutput(
            problem_id=pid,
            entry_function=entry_function,
            analysis=analysis,
            plan_steps=plan_steps,
            code=code,
            explanation=explanation,
            confidence=confidence,
            verified=verified,
            test_results=sandbox_result.test_results,
            retry_used=retry_used,
        )
        logger.info(
            "solver.done problem_id=%s confidence=%.2f verified=%s status=%s retry_used=%s",
            pid,
            confidence,
            verified,
            sandbox_result.status,
            retry_used,
        )
        return output

    @staticmethod
    def _should_retry(result: SandboxRunResult) -> bool:
        # Retry on wrong-answer or hard sandbox errors; do NOT retry on timeout
        # (likely an infinite loop — regenerating won't help quickly).
        return result.status in ("some_failed", "error")

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

    async def _code_retry(
        self,
        request: SolverInput,
        plan_steps: list[PlanStep],
        previous_code: str,
        sandbox_result: SandboxRunResult,
    ) -> tuple[str, str]:
        messages = prompts.build_code_retry_messages(
            request.problem_text,
            plan_steps,
            request.test_cases,
            previous_code,
            sandbox_result.test_results,
            sandbox_error=sandbox_result.error,
        )
        try:
            raw = await self._client.chat(messages, temperature=0.1, json_mode=True)
        except LLMError as exc:
            raise SolverError("code_retry", request.problem_id, str(exc)) from exc
        return self._parse_code(raw, request.problem_id)

    async def _run_sandbox(
        self, code: str, entry_function: str, test_cases: list[dict]
    ) -> SandboxRunResult:
        sandbox_request = SandboxRunRequest(
            code=code,
            entry_function=entry_function,
            test_cases=test_cases,
            timeout_seconds=self._sandbox_timeout_seconds,
            memory_mb=self._sandbox_memory_mb,
        )
        return await self._runner.run(sandbox_request)

    @staticmethod
    def _extract_entry_function(code: str, problem_id: str) -> str:
        try:
            return extract_entry_function(code, problem_id)
        except EntryFunctionExtractionError:
            raise SolverError(
                "sandbox", problem_id, "no top-level function definition found in generated code"
            )

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
    def _compute_confidence(
        analysis: str,
        plan_steps: list[PlanStep],
        code: str,
        *,
        verified: bool,
        retry_used: bool,
    ) -> float:
        score = 1.0
        if len(analysis) < 50:
            score -= 0.2
        if len(plan_steps) <= 1:
            score -= 0.2
        if "def " not in code:
            score -= 0.3
        score = max(0.0, score)
        if not verified:
            return min(score, _UNVERIFIED_CONFIDENCE_CAP)
        if retry_used:
            return min(score, _RETRIED_CONFIDENCE_CAP)
        return score


@lru_cache
def get_solver_agent() -> SolverAgent:
    settings = get_settings()
    return SolverAgent(
        client=get_llm_client(),
        runner=get_sandbox_runner(),
        sandbox_timeout_seconds=settings.SANDBOX_TIMEOUT_SECONDS,
        sandbox_memory_mb=settings.SANDBOX_MEMORY_MB,
    )
