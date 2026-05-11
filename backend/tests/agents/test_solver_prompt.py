from app.agents.solver import prompts
from app.agents.solver.schemas import PlanStep, TestCase
from app.sandbox.schemas import TestExecutionResult


def _plan_steps() -> list[PlanStep]:
    return [PlanStep(step_number=1, action="Define the function", rationale="signature")]


def _test_cases() -> list[TestCase]:
    return [TestCase(input="5", expected="5", description="basic")]


def _user_content(messages: list[dict]) -> str:
    return messages[1]["content"]


def test_code_prompt_includes_entry_function_constraint() -> None:
    content = _user_content(
        prompts.build_code_messages(
            "Write a Fibonacci function.",
            "fibonacci",
            _plan_steps(),
            _test_cases(),
        )
    )

    assert content.startswith("## CRITICAL CONSTRAINT")
    assert "MUST be named EXACTLY: `fibonacci`" in content
    assert "def fibonacci(...):" in content
    assert "WRONG: def fib_n(n)" in content
    assert "WRONG: def fibonacciNumber(n)" in content


def test_code_prompt_preserves_camelcase_entry_function() -> None:
    content = _user_content(
        prompts.build_code_messages(
            "Add two numeric strings.",
            "addStrings",
            _plan_steps(),
            _test_cases(),
        )
    )

    assert "MUST be named EXACTLY: `addStrings`" in content
    assert "def addStrings(...):" in content
    assert "Do NOT rename, abbreviate, or change the case" in content


def test_retry_prompt_repeats_entry_function_constraint() -> None:
    failed = [
        TestExecutionResult(
            test_index=0,
            input="5",
            expected="5",
            actual=None,
            passed=False,
            error="FATAL: function fibonacci not defined or not callable",
            duration_ms=1,
        )
    ]

    content = _user_content(
        prompts.build_code_retry_messages(
            "Write a Fibonacci function.",
            "fibonacci",
            _plan_steps(),
            _test_cases(),
            "def fib_n(n):\n    return n\n",
            failed,
            sandbox_error="FATAL: function fibonacci not defined or not callable",
        )
    )

    assert content.startswith("## CRITICAL CONSTRAINT")
    assert "MUST be named EXACTLY: `fibonacci`" in content
    assert "Previous code:" in content
    assert "Sandbox-level error: FATAL: function fibonacci not defined or not callable" in content
