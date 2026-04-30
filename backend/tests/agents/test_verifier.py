"""Unit tests for VerifierAgent — no Docker daemon, no real LLM.

These tests mock both the DockerCodeRunner and DeepSeekClient. They verify
orchestration logic and three structural anti-leak guards:

    test_prompt_omits_expected:        no `expected` value reaches the LLM
    test_prompt_omits_descriptions:    no `description` value reaches the LLM
    test_redacted_output_excludes_expected: VerifierOutput schema has no expected

Behavioral leak guards (does the actual LLM produce code-free, answer-free
text) live in test_verifier_integration.py, not here.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from app.agents.solver.schemas import TestCase
from app.agents.verifier.agent import (
    LLM_FALLBACK_DIAGNOSIS,
    TIMEOUT_DIAGNOSIS,
    VerifierAgent,
    VerifierError,
)
from app.agents.verifier.schemas import (
    RedactedTestResult,
    VerifierInput,
    VerifierOutput,
)
from app.llm.client import DeepSeekClient
from app.llm.exceptions import LLMError
from app.sandbox.docker_runner import DockerCodeRunner
from app.sandbox.schemas import (
    SandboxRunResult,
    SandboxStatus,
    TestExecutionResult,
)

# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


def _agent(
    sandbox_results: list[SandboxRunResult] | Exception | None = None,
    llm_responses: list[str | Exception] | None = None,
) -> tuple[VerifierAgent, AsyncMock, AsyncMock]:
    """Build a VerifierAgent with mocked dependencies.

    Returns (agent, sandbox.run mock, llm.chat mock).
    """
    sandbox = AsyncMock(spec=DockerCodeRunner)
    if isinstance(sandbox_results, Exception):
        sandbox.run = AsyncMock(side_effect=sandbox_results)
    else:
        sandbox.run = AsyncMock(side_effect=sandbox_results or [])

    llm = AsyncMock(spec=DeepSeekClient)
    llm.chat = AsyncMock(side_effect=llm_responses or [])

    return (
        VerifierAgent(sandbox_runner=sandbox, llm_client=llm),
        sandbox.run,
        llm.chat,
    )


def _input(
    *,
    test_cases: list[TestCase] | None = None,
    student_code: str = "def f(x): return x",
    entry_function: str = "f",
) -> VerifierInput:
    return VerifierInput(
        problem_id="py-001",
        problem_text="Implement f(x).",
        entry_function=entry_function,
        test_cases=test_cases or [TestCase(input="1", expected="1", description="basic")],
        student_code=student_code,
    )


def _result(
    *,
    status: SandboxStatus,
    test_results: list[TestExecutionResult] | None = None,
    pass_count: int = 0,
    fail_count: int = 0,
    error: str | None = None,
) -> SandboxRunResult:
    return SandboxRunResult(
        status=status,
        test_results=test_results or [],
        pass_count=pass_count,
        fail_count=fail_count,
        error=error,
    )


def _passing(index: int = 0, input: str = "1", actual: str = "1") -> TestExecutionResult:
    return TestExecutionResult(
        test_index=index,
        input=input,
        expected="REDACTED_BY_SANDBOX",
        actual=actual,
        passed=True,
        error=None,
        duration_ms=1,
    )


def _failing(
    index: int = 0,
    input: str = "1",
    actual: str | None = "2",
    error: str | None = None,
) -> TestExecutionResult:
    return TestExecutionResult(
        test_index=index,
        input=input,
        expected="REDACTED_BY_SANDBOX",
        actual=actual,
        passed=False,
        error=error,
        duration_ms=1,
    )


def _captured_prompt(chat_mock: AsyncMock) -> str:
    """Return system + user prompt content concatenated."""
    messages = chat_mock.call_args.kwargs["messages"]
    return messages[0]["content"] + "\n" + messages[1]["content"]


# ---------------------------------------------------------------------------
# 1. all_passed → verified=True, no LLM call.
# ---------------------------------------------------------------------------
async def test_all_pass_returns_verified_true_no_diagnosis() -> None:
    sandbox_result = _result(
        status="all_passed",
        test_results=[_passing(0), _passing(1, input="2", actual="2")],
        pass_count=2,
    )
    agent, _, chat = _agent(sandbox_results=[sandbox_result])

    out = await agent.verify(_input())

    assert out.verified is True
    assert out.diagnosis == ""
    assert out.status == "all_passed"
    assert out.pass_count == 2
    chat.assert_not_called()


# ---------------------------------------------------------------------------
# 2. some_failed → call LLM exactly once for diagnosis.
# ---------------------------------------------------------------------------
async def test_some_fail_calls_llm_for_diagnosis() -> None:
    sandbox_result = _result(
        status="some_failed",
        test_results=[_passing(0), _failing(1, input="2", actual="3")],
        pass_count=1,
        fail_count=1,
    )
    agent, _, chat = _agent(
        sandbox_results=[sandbox_result],
        llm_responses=["Your function ignores the edge case."],
    )

    out = await agent.verify(_input())

    assert out.verified is False
    assert out.status == "some_failed"
    assert out.diagnosis == "Your function ignores the edge case."
    chat.assert_awaited_once()


# ---------------------------------------------------------------------------
# 3. Sandbox infra failure → VerifierError, original chained.
# ---------------------------------------------------------------------------
async def test_sandbox_infra_error_raises_verifier_error() -> None:
    original = RuntimeError("docker daemon down")
    agent, _, _ = _agent(sandbox_results=original)

    with pytest.raises(VerifierError) as exc_info:
        await agent.verify(_input())

    assert exc_info.value.__cause__ is original
    assert "RuntimeError" in str(exc_info.value)


# ---------------------------------------------------------------------------
# 4. LLM error degrades gracefully — fallback diagnosis, no exception.
# ---------------------------------------------------------------------------
async def test_llm_error_degrades_gracefully() -> None:
    sandbox_result = _result(
        status="some_failed",
        test_results=[_failing()],
        fail_count=1,
    )
    agent, _, chat = _agent(
        sandbox_results=[sandbox_result],
        llm_responses=[LLMError("upstream 500")],
    )

    out = await agent.verify(_input())

    assert isinstance(out, VerifierOutput)
    assert out.verified is False
    assert out.diagnosis == LLM_FALLBACK_DIAGNOSIS
    assert out.fail_count == 1
    chat.assert_awaited_once()


# ---------------------------------------------------------------------------
# 5. status="error" (e.g., student SyntaxError) → no LLM call, sandbox_error set.
# ---------------------------------------------------------------------------
async def test_sandbox_returns_status_error() -> None:
    sandbox_result = _result(
        status="error",
        error="FATAL: user code failed to load: SyntaxError: invalid syntax",
    )
    agent, _, chat = _agent(sandbox_results=[sandbox_result])

    out = await agent.verify(_input())

    assert out.verified is False
    assert out.status == "error"
    assert out.diagnosis == ""
    assert "SyntaxError" in (out.sandbox_error or "")
    chat.assert_not_called()


# ---------------------------------------------------------------------------
# 6. Only failed tests appear in the prompt.
# ---------------------------------------------------------------------------
async def test_only_failed_tests_in_prompt() -> None:
    sandbox_result = _result(
        status="some_failed",
        test_results=[
            _passing(0, input="PASS_INPUT_AAA", actual="ok"),
            _failing(1, input="FAIL_INPUT_BBB", actual="bad"),
            _passing(2, input="PASS_INPUT_CCC", actual="ok"),
        ],
        pass_count=2,
        fail_count=1,
    )
    agent, _, chat = _agent(
        sandbox_results=[sandbox_result],
        llm_responses=["hint"],
    )
    await agent.verify(_input())

    prompt = _captured_prompt(chat)
    assert "FAIL_INPUT_BBB" in prompt
    assert "PASS_INPUT_AAA" not in prompt
    assert "PASS_INPUT_CCC" not in prompt


# ---------------------------------------------------------------------------
# 7. At most 3 failed tests reach the prompt; order preserved.
# ---------------------------------------------------------------------------
async def test_failed_tests_capped_at_three() -> None:
    sandbox_result = _result(
        status="some_failed",
        test_results=[_failing(i, input=f"FAIL_INPUT_{i + 1}", actual="x") for i in range(5)],
        fail_count=5,
    )
    agent, _, chat = _agent(
        sandbox_results=[sandbox_result],
        llm_responses=["hint"],
    )
    await agent.verify(_input())

    prompt = _captured_prompt(chat)
    assert "FAIL_INPUT_1" in prompt
    assert "FAIL_INPUT_2" in prompt
    assert "FAIL_INPUT_3" in prompt
    assert "FAIL_INPUT_4" not in prompt
    assert "FAIL_INPUT_5" not in prompt
    # Order preserved: 1 before 2 before 3
    assert (
        prompt.index("FAIL_INPUT_1") < prompt.index("FAIL_INPUT_2") < prompt.index("FAIL_INPUT_3")
    )


# ---------------------------------------------------------------------------
# 8. SandboxRunRequest receives [tc.model_dump() for tc in input.test_cases].
# ---------------------------------------------------------------------------
async def test_typed_test_cases_dumped_for_sandbox() -> None:
    sandbox_result = _result(status="all_passed", test_results=[_passing()], pass_count=1)
    agent, run_mock, _ = _agent(sandbox_results=[sandbox_result])

    inp = _input(
        test_cases=[
            TestCase(input="1", expected="A", description="d1"),
            TestCase(input="2", expected="B", description="d2"),
        ]
    )
    await agent.verify(inp)

    sandbox_request = run_mock.call_args.args[0]
    assert sandbox_request.test_cases == [tc.model_dump() for tc in inp.test_cases]
    # Specifically dicts, not TestCase instances:
    assert all(isinstance(tc, dict) for tc in sandbox_request.test_cases)


# ---------------------------------------------------------------------------
# 9. timeout → deterministic message, no LLM call.
# ---------------------------------------------------------------------------
async def test_timeout_status_skips_llm_call() -> None:
    sandbox_result = _result(
        status="timeout",
        error="subprocess exceeded 5s timeout",
    )
    agent, _, chat = _agent(sandbox_results=[sandbox_result])

    out = await agent.verify(_input())

    assert out.verified is False
    assert out.status == "timeout"
    assert out.diagnosis == TIMEOUT_DIAGNOSIS
    chat.assert_not_called()


# ---------------------------------------------------------------------------
# 10. Defensive: status=some_failed with empty test_results → no LLM, no diagnosis.
# ---------------------------------------------------------------------------
async def test_some_failed_with_empty_results_skips_llm_call() -> None:
    sandbox_result = _result(status="some_failed", test_results=[])
    agent, _, chat = _agent(sandbox_results=[sandbox_result])

    out = await agent.verify(_input())

    assert out.diagnosis == ""
    chat.assert_not_called()


# ---------------------------------------------------------------------------
# 11. Failed test with actual=None and error string formats prompt safely.
# ---------------------------------------------------------------------------
async def test_failed_test_with_error_and_none_actual() -> None:
    sandbox_result = _result(
        status="some_failed",
        test_results=[
            _failing(
                0, input="DIVZERO_INPUT", actual=None, error="ZeroDivisionError: division by zero"
            )
        ],
        fail_count=1,
    )
    agent, _, chat = _agent(
        sandbox_results=[sandbox_result],
        llm_responses=["hint"],
    )

    out = await agent.verify(_input())

    assert out.verified is False
    assert out.diagnosis == "hint"
    chat.assert_awaited_once()
    prompt = _captured_prompt(chat)
    assert "DIVZERO_INPUT" in prompt
    assert "ZeroDivisionError" in prompt


# ---------------------------------------------------------------------------
# 12. CRITICAL ANTI-LEAK: `expected` values never reach the LLM prompt.
# ---------------------------------------------------------------------------
async def test_prompt_omits_expected() -> None:
    sandbox_result = _result(
        status="some_failed",
        test_results=[_failing(0, input="1", actual="2")],
        fail_count=1,
    )
    agent, _, chat = _agent(
        sandbox_results=[sandbox_result],
        llm_responses=["hint"],
    )

    inp = _input(
        test_cases=[
            TestCase(input="1", expected="EXPECTED_SECRET_42", description="basic"),
            TestCase(input="2", expected="EXPECTED_SECRET_99", description="edge"),
        ]
    )
    await agent.verify(inp)

    combined = _captured_prompt(chat)
    assert "EXPECTED_SECRET_42" not in combined
    assert "EXPECTED_SECRET_99" not in combined


# ---------------------------------------------------------------------------
# 13. CRITICAL ANTI-LEAK: `description` text never reaches the LLM prompt.
# ---------------------------------------------------------------------------
async def test_prompt_omits_descriptions() -> None:
    sandbox_result = _result(
        status="some_failed",
        test_results=[_failing(0, input="1", actual="2")],
        fail_count=1,
    )
    agent, _, chat = _agent(
        sandbox_results=[sandbox_result],
        llm_responses=["hint"],
    )

    inp = _input(
        test_cases=[
            TestCase(
                input="1",
                expected="ok",
                description="DESC_LEAKS_ANSWER_777: empty list returns -1",
            )
        ]
    )
    await agent.verify(inp)

    combined = _captured_prompt(chat)
    assert "DESC_LEAKS_ANSWER_777" not in combined


# ---------------------------------------------------------------------------
# 14. CRITICAL ANTI-LEAK: VerifierOutput.test_results items have no `expected`.
# Schema-level guard: even a future regression that adds expected back would
# trip this test.
# ---------------------------------------------------------------------------
async def test_redacted_output_excludes_expected() -> None:
    # Schema-level: the field literally does not exist on RedactedTestResult.
    assert "expected" not in RedactedTestResult.model_fields

    # Runtime: items in VerifierOutput.test_results have no expected attribute.
    sandbox_result = _result(
        status="some_failed",
        test_results=[
            _passing(0, input="1", actual="ok"),
            _failing(1, input="2", actual="bad"),
        ],
        pass_count=1,
        fail_count=1,
    )
    agent, _, _ = _agent(
        sandbox_results=[sandbox_result],
        llm_responses=["hint"],
    )

    out = await agent.verify(_input())
    assert len(out.test_results) == 2
    for tr in out.test_results:
        assert isinstance(tr, RedactedTestResult)
        assert not hasattr(tr, "expected")
        # Also verify the dump doesn't contain it:
        assert "expected" not in tr.model_dump()


# ---------------------------------------------------------------------------
# 15. SDK contract: chat() is the entry point; complete() is not used.
# ---------------------------------------------------------------------------
async def test_uses_chat_method_not_complete() -> None:
    sandbox_result = _result(
        status="some_failed",
        test_results=[_failing()],
        fail_count=1,
    )
    agent, _, chat = _agent(
        sandbox_results=[sandbox_result],
        llm_responses=["hint"],
    )
    await agent.verify(_input())

    chat.assert_awaited_once()
    # AsyncMock(spec=DeepSeekClient) restricts attribute access to real
    # attributes of DeepSeekClient. If `complete` is not defined on the
    # client, hasattr returns False and the assertion holds trivially.
    # If a future `complete` method is added, assert it was never called.
    if hasattr(agent.llm, "complete"):
        agent.llm.complete.assert_not_called()
