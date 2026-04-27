from __future__ import annotations

import json
from unittest.mock import AsyncMock

import pytest

from app.agents.solver.agent import SolverAgent, SolverError
from app.agents.solver.schemas import PlanStep, SolverInput, TestCase
from app.llm.client import DeepSeekClient
from app.llm.exceptions import LLMError, LLMTimeoutError
from app.sandbox.runner import PythonSubprocessRunner
from app.sandbox.schemas import SandboxRunResult, TestExecutionResult


def _input() -> SolverInput:
    return SolverInput(
        problem_id="py-001-sum-list",
        problem_text="Write sum_list(nums) returning the sum, or 0 if empty.",
        test_cases=[
            TestCase(input="[1,2,3]", expected="6", description="basic"),
            TestCase(input="[]", expected="0", description="empty"),
        ],
    )


def _good_responses() -> list[str]:
    analysis = (
        "We need a function sum_list that takes a list of integers and returns "
        "their sum. The empty-list case must return 0."
    )
    plan = json.dumps(
        {
            "steps": [
                {"step_number": 1, "action": "Define sum_list(nums)", "rationale": "signature"},
                {"step_number": 2, "action": "Initialize total = 0", "rationale": "accumulator"},
                {"step_number": 3, "action": "Iterate and add", "rationale": "core logic"},
                {"step_number": 4, "action": "Return total", "rationale": "result"},
            ]
        }
    )
    code_src = (
        "def sum_list(nums):\n"
        "    total = 0\n"
        "    for n in nums:\n"
        "        total += n\n"
        "    return total\n"
    )
    code = json.dumps({"code": code_src, "explanation": "Linear scan into total."})
    return [analysis, plan, code]


def _all_passed_result(n: int = 2) -> SandboxRunResult:
    results = [
        TestExecutionResult(
            test_index=i,
            input=f"input{i}",
            expected="x",
            actual="x",
            passed=True,
            error=None,
            duration_ms=1,
        )
        for i in range(n)
    ]
    return SandboxRunResult(status="all_passed", test_results=results, pass_count=n, fail_count=0)


def _some_failed_result(n: int = 2) -> SandboxRunResult:
    results = [
        TestExecutionResult(
            test_index=0,
            input="[1,2,3]",
            expected="6",
            actual="0",
            passed=False,
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
    ]
    return SandboxRunResult(
        status="some_failed", test_results=results[:n], pass_count=1, fail_count=1
    )


def _timeout_result() -> SandboxRunResult:
    return SandboxRunResult(
        status="timeout",
        test_results=[],
        pass_count=0,
        fail_count=0,
        error="subprocess exceeded 5s timeout",
    )


def _fake_runner(results: list[SandboxRunResult]) -> tuple[PythonSubprocessRunner, AsyncMock]:
    runner = AsyncMock(spec=PythonSubprocessRunner)
    runner.run = AsyncMock(side_effect=results)
    return runner, runner.run


def _agent(
    llm_responses: list[str | Exception],
    sandbox_results: list[SandboxRunResult] | None = None,
) -> tuple[SolverAgent, AsyncMock, AsyncMock]:
    client = AsyncMock(spec=DeepSeekClient)
    client.chat = AsyncMock(side_effect=llm_responses)
    runner, run_mock = _fake_runner(sandbox_results or [])
    return SolverAgent(client=client, runner=runner), client.chat, run_mock


# ---------- happy / error paths from Step 2.2 (updated for sandbox) ----------


async def test_solve_happy_path_verified_first_try():
    agent, chat, sandbox_run = _agent(_good_responses(), [_all_passed_result()])

    out = await agent.solve(_input())

    assert chat.await_count == 3  # analyze, plan, code (no retry)
    assert sandbox_run.await_count == 1
    assert out.problem_id == "py-001-sum-list"
    assert out.verified is True
    assert len(out.test_results) == 2
    assert all(r.passed for r in out.test_results)
    assert out.confidence == pytest.approx(1.0)

    # Stage 1: analyze — no json_mode.
    assert chat.await_args_list[0].kwargs.get("json_mode", False) is False
    # Stages 2 & 3: json_mode required.
    assert chat.await_args_list[1].kwargs["json_mode"] is True
    assert chat.await_args_list[2].kwargs["json_mode"] is True


async def test_solve_propagates_llm_error_as_solver_error_with_step_context():
    agent, _, _ = _agent([LLMError("upstream 500")])

    with pytest.raises(SolverError) as ei:
        await agent.solve(_input())

    assert ei.value.step == "analyze"
    assert ei.value.problem_id == "py-001-sum-list"


async def test_solve_propagates_timeout_in_plan_step():
    analysis, _plan, _code = _good_responses()
    agent, _, _ = _agent([analysis, LLMTimeoutError("slow")])

    with pytest.raises(SolverError) as ei:
        await agent.solve(_input())

    assert ei.value.step == "plan"


async def test_solve_raises_on_malformed_plan_json():
    analysis, _, code = _good_responses()
    agent, _, _ = _agent([analysis, "not-json-at-all", code])

    with pytest.raises(SolverError) as ei:
        await agent.solve(_input())

    assert ei.value.step == "plan"
    assert "invalid JSON" in str(ei.value)


async def test_solve_raises_when_plan_missing_steps_key():
    analysis, _, code = _good_responses()
    agent, _, _ = _agent([analysis, json.dumps({"items": []}), code])

    with pytest.raises(SolverError) as ei:
        await agent.solve(_input())

    assert ei.value.step == "plan"


async def test_solve_raises_on_malformed_code_json():
    analysis, plan, _ = _good_responses()
    agent, _, _ = _agent([analysis, plan, json.dumps({"code": "x"})])

    with pytest.raises(SolverError) as ei:
        await agent.solve(_input())

    assert ei.value.step == "code"


# ---------- new: sandbox retry / verification paths ----------


async def test_solve_retries_once_when_first_attempt_fails_sandbox():
    analysis, plan, code = _good_responses()
    # Second code response (retry) is also valid JSON — same body works.
    retry_code = json.dumps(
        {
            "code": ("def sum_list(nums):\n    return sum(nums)\n"),
            "explanation": "use builtin",
        }
    )
    agent, chat, sandbox_run = _agent(
        llm_responses=[analysis, plan, code, retry_code],
        sandbox_results=[_some_failed_result(), _all_passed_result()],
    )

    out = await agent.solve(_input())

    assert chat.await_count == 4  # extra code retry call
    assert sandbox_run.await_count == 2
    assert out.verified is True
    assert out.confidence <= 0.85
    # Code should reflect the retry's output, not the first attempt
    assert "return sum(nums)" in out.code


async def test_solve_returns_unverified_when_both_attempts_fail():
    analysis, plan, code = _good_responses()
    retry_code = json.dumps({"code": "def sum_list(nums): return -1", "explanation": "wrong"})
    agent, chat, sandbox_run = _agent(
        llm_responses=[analysis, plan, code, retry_code],
        sandbox_results=[_some_failed_result(), _some_failed_result()],
    )

    out = await agent.solve(_input())

    assert chat.await_count == 4
    assert sandbox_run.await_count == 2
    assert out.verified is False
    assert out.confidence <= 0.4
    assert len(out.test_results) > 0  # final failure details attached


async def test_solve_does_not_retry_on_timeout():
    analysis, plan, code = _good_responses()
    agent, chat, sandbox_run = _agent(
        llm_responses=[analysis, plan, code],
        sandbox_results=[_timeout_result()],
    )

    out = await agent.solve(_input())

    assert chat.await_count == 3  # no retry
    assert sandbox_run.await_count == 1
    assert out.verified is False
    assert out.confidence <= 0.4
    assert out.test_results == []


async def test_solve_raises_when_generated_code_has_no_def():
    analysis, plan, _ = _good_responses()
    bad_code = json.dumps({"code": "x = 1  # no function!", "explanation": "broken"})
    # Sandbox results not consumed because we should fail before running.
    agent, _, sandbox_run = _agent([analysis, plan, bad_code], sandbox_results=[])

    with pytest.raises(SolverError) as ei:
        await agent.solve(_input())

    assert ei.value.step == "sandbox"
    assert sandbox_run.await_count == 0


# ---------- entry-function extraction ----------


@pytest.mark.parametrize(
    "code,expected",
    [
        ("def foo(x):\n    return x", "foo"),
        ("async def fetch(url):\n    pass", "fetch"),
        ("@cache\ndef bar(n):\n    return n", "bar"),
        # Method inside a class is indented → skipped; top-level wins.
        ("def top(x):\n    pass\n\nclass C:\n    def method(self): pass", "top"),
    ],
)
def test_extract_entry_function_picks_first_top_level(code: str, expected: str):
    assert SolverAgent._extract_entry_function(code, "pid") == expected


def test_extract_entry_function_raises_when_no_def():
    with pytest.raises(SolverError) as ei:
        SolverAgent._extract_entry_function("x = 1", "pid")
    assert ei.value.step == "sandbox"


# ---------- confidence table (now keyword-only verified/retry_used) ----------


@pytest.mark.parametrize(
    "analysis,plan_steps,code,verified,retry_used,expected",
    [
        # verified, no retry — full score
        (
            "x" * 100,
            [PlanStep(step_number=i, action="a", rationale="r") for i in (1, 2, 3)],
            "def f(): pass",
            True,
            False,
            1.0,
        ),
        # verified after retry — capped at 0.85
        (
            "x" * 100,
            [PlanStep(step_number=i, action="a", rationale="r") for i in (1, 2, 3)],
            "def f(): pass",
            True,
            True,
            0.85,
        ),
        # not verified — capped at 0.4 regardless of base score
        (
            "x" * 100,
            [PlanStep(step_number=i, action="a", rationale="r") for i in (1, 2, 3)],
            "def f(): pass",
            False,
            False,
            0.4,
        ),
        # base score below cap is preserved
        (
            "short",
            [],
            "no_function_here",
            False,
            False,
            0.3,
        ),
    ],
)
def test_compute_confidence_table(analysis, plan_steps, code, verified, retry_used, expected):
    got = SolverAgent._compute_confidence(
        analysis, plan_steps, code, verified=verified, retry_used=retry_used
    )
    assert got == pytest.approx(expected)
