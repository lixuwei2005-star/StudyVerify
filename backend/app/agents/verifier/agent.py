"""Stateless Verifier Agent.

Pure function from VerifierInput to VerifierOutput. No DB access, no FastAPI
knowledge, no per-request mutable state. Step 4.3 will wrap this agent with
a service that adds persistence + a route.

Constructor-injected dependencies (DockerCodeRunner + DeepSeekClient) make
the agent trivially mockable in unit tests. A single cached instance from
get_verifier_agent() serves concurrent requests because DockerCodeRunner
creates a fresh container per call.
"""

from __future__ import annotations

import logging
from functools import lru_cache

from app.agents.verifier.prompts import build_diagnosis_prompt
from app.agents.verifier.schemas import (
    RedactedTestResult,
    VerifierInput,
    VerifierOutput,
)
from app.llm.client import DeepSeekClient, get_llm_client
from app.llm.exceptions import LLMError
from app.sandbox.docker_runner import DockerCodeRunner
from app.sandbox.schemas import SandboxRunRequest, SandboxRunResult, TestExecutionResult

logger = logging.getLogger(__name__)

# Module-level constants instead of constructor params or magic numbers in
# verify(). Step 4.3 may want per-problem limits; tuning here is one-place.
DEFAULT_TIMEOUT_SECONDS = 5
DEFAULT_MEMORY_MB = 128

TIMEOUT_DIAGNOSIS = (
    "Your code did not complete within the time limit. Look for infinite "
    "loops or excessive computation."
)

LLM_FALLBACK_DIAGNOSIS = (
    "Tests failed; detailed feedback unavailable right now. Review the failing test inputs above."
)


class VerifierError(Exception):
    """Raised when verification cannot complete due to upstream sandbox infra
    failure, such as Docker being unavailable. Distinct from LLM errors,
    which degrade gracefully into a fallback diagnosis."""


class VerifierAgent:
    """Stateless verifier with constructor-injected dependencies."""

    def __init__(
        self,
        sandbox_runner: DockerCodeRunner,
        llm_client: DeepSeekClient,
    ) -> None:
        self.sandbox = sandbox_runner
        self.llm = llm_client

    async def verify(self, input: VerifierInput) -> VerifierOutput:
        """Run student code, redact answers, and diagnose wrong-answer failures."""
        try:
            sandbox_result = await self.sandbox.run(
                SandboxRunRequest(
                    code=input.student_code,
                    entry_function=input.entry_function,
                    test_cases=[tc.model_dump() for tc in input.test_cases],
                    timeout_seconds=DEFAULT_TIMEOUT_SECONDS,
                    memory_mb=DEFAULT_MEMORY_MB,
                )
            )
        except Exception as exc:
            logger.exception("Sandbox infra failure for problem=%s", input.problem_id)
            raise VerifierError(f"Sandbox unavailable: {type(exc).__name__}") from exc

        redacted_results = self._redact_results(sandbox_result)
        verified = sandbox_result.status == "all_passed"
        diagnosis = ""

        if sandbox_result.status == "all_passed":
            diagnosis = ""
        elif sandbox_result.status == "error":
            # Wrapper FATAL / syntax errors / load failures: no per-test
            # signal to diagnose, and the sandbox_error string already tells
            # the student what happened.
            diagnosis = ""
        elif sandbox_result.status == "timeout":
            # Deterministic — don't spend LLM tokens.
            diagnosis = TIMEOUT_DIAGNOSIS
        elif sandbox_result.status == "some_failed":
            failed_tests = [tr for tr in sandbox_result.test_results if not tr.passed]
            if failed_tests:
                try:
                    diagnosis = await self._generate_diagnosis(input, failed_tests)
                except LLMError as exc:
                    logger.warning(
                        "Diagnosis generation failed for problem=%s: %s",
                        input.problem_id,
                        exc,
                    )
                    diagnosis = LLM_FALLBACK_DIAGNOSIS

        return VerifierOutput(
            problem_id=input.problem_id,
            verified=verified,
            status=sandbox_result.status,
            pass_count=sandbox_result.pass_count,
            fail_count=sandbox_result.fail_count,
            test_results=redacted_results,
            diagnosis=diagnosis,
            sandbox_error=sandbox_result.error,
        )

    async def _generate_diagnosis(
        self,
        input: VerifierInput,
        failed_tests: list[TestExecutionResult],
    ) -> str:
        prompt = build_diagnosis_prompt(
            problem_text=input.problem_text,
            student_code=input.student_code,
            failed_tests=failed_tests,
        )
        response = await self.llm.chat(
            messages=[
                {"role": "system", "content": prompt["system"]},
                {"role": "user", "content": prompt["user"]},
            ],
            temperature=0.3,
            json_mode=False,
        )
        return response.strip()

    @staticmethod
    def _redact_results(result: SandboxRunResult) -> list[RedactedTestResult]:
        return [
            RedactedTestResult(
                input=tr.input,
                actual=tr.actual,
                passed=tr.passed,
                duration_ms=tr.duration_ms,
                error=tr.error,
            )
            for tr in result.test_results
        ]


@lru_cache
def get_verifier_agent() -> VerifierAgent:
    """Cached factory. Verifier is stateless; one instance serves all requests.

    First call constructs DockerCodeRunner() which calls docker.from_env().
    If the daemon is unavailable, this raises and lru_cache stores no result —
    the next call retries.
    """
    return VerifierAgent(
        sandbox_runner=DockerCodeRunner(),
        llm_client=get_llm_client(),
    )
