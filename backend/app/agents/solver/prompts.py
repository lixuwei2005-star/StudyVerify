from __future__ import annotations

from typing import Any

from app.agents.solver.schemas import PlanStep, TestCase
from app.sandbox.schemas import TestExecutionResult

SYSTEM_MESSAGE = (
    "You are an expert Python instructor solving beginner-level problems. "
    "Be precise, prefer clarity over cleverness."
)


def _format_test_cases(test_cases: list[TestCase]) -> str:
    if not test_cases:
        return "(no test cases provided)"
    lines = []
    for i, tc in enumerate(test_cases, start=1):
        lines.append(f"  {i}. input={tc.input!r}  expected={tc.expected!r}  ({tc.description})")
    return "\n".join(lines)


def _entry_function_constraint(entry_function: str) -> str:
    return (
        "## CRITICAL CONSTRAINT\n\n"
        f"The function you generate MUST be named EXACTLY: `{entry_function}`\n\n"
        "Do NOT rename, abbreviate, or change the case of this function name. "
        "The function signature must start with:\n\n"
        f"    def {entry_function}(...):\n\n"
        "Examples of CORRECT vs WRONG:\n"
        "- entry_function='fibonacci' -> CORRECT: def fibonacci(n)\n"
        "- entry_function='fibonacci' -> WRONG: def fib_n(n)\n"
        "- entry_function='fibonacci' -> WRONG: def fibonacciNumber(n)\n"
        "- entry_function='find_max' -> CORRECT: def find_max(nums)\n"
        "- entry_function='find_max' -> WRONG: def find_largest(nums)\n"
        "- entry_function='find_max' -> WRONG: def findMax(nums)\n\n"
        "Do not import or define any other top-level function with the same body "
        "- only one function with the entry_function name."
    )


def build_analyze_messages(problem_text: str, test_cases: list[TestCase]) -> list[dict[str, Any]]:
    user = (
        "Problem:\n"
        f"{problem_text}\n\n"
        "Test cases:\n"
        f"{_format_test_cases(test_cases)}\n\n"
        "Restate what is being asked in your own words. List the inputs, the expected "
        "output, and any edge cases you notice (empty input, unusual types, boundary "
        "values). Plain prose, no code, 200 words or fewer."
    )
    return [
        {"role": "system", "content": SYSTEM_MESSAGE},
        {"role": "user", "content": user},
    ]


def build_plan_messages(problem_text: str, analysis: str) -> list[dict[str, Any]]:
    user = (
        "Problem:\n"
        f"{problem_text}\n\n"
        "Your earlier analysis:\n"
        f"{analysis}\n\n"
        "Produce an ordered, atomic implementation plan a beginner could follow. "
        "Aim for 3 to 7 steps.\n\n"
        "Return ONLY a JSON object of the form:\n"
        '{"steps": [{"step_number": 1, "action": "...", "rationale": "..."}, ...]}\n'
        "No prose outside the JSON."
    )
    return [
        {"role": "system", "content": SYSTEM_MESSAGE},
        {"role": "user", "content": user},
    ]


def build_code_messages(
    problem_text: str,
    entry_function: str,
    plan_steps: list[PlanStep],
    test_cases: list[TestCase],
) -> list[dict[str, Any]]:
    plan_str = "\n".join(f"  {s.step_number}. {s.action} — {s.rationale}" for s in plan_steps)
    user = (
        f"{_entry_function_constraint(entry_function)}\n\n"
        "Problem:\n"
        f"{problem_text}\n\n"
        "Plan:\n"
        f"{plan_str}\n\n"
        "Test cases:\n"
        f"{_format_test_cases(test_cases)}\n\n"
        "Implement the function in Python 3.11. Include the full `def` signature. "
        "The code must run as-is when pasted into a fresh module.\n\n"
        "Return ONLY a JSON object of the form:\n"
        '{"code": "<full python source>", "explanation": "<<=150 words plain language>"}\n'
        "No prose outside the JSON."
    )
    return [
        {"role": "system", "content": SYSTEM_MESSAGE},
        {"role": "user", "content": user},
    ]


def _format_failures(test_results: list[TestExecutionResult]) -> str:
    if not test_results:
        return "  (no per-test results — sandbox could not execute the code)"
    lines = []
    for r in test_results:
        if r.passed:
            continue
        if r.error:
            outcome = f"raised {r.error}"
        else:
            outcome = f"got {r.actual!r}, expected {r.expected!r}"
        lines.append(f"  - test {r.test_index} (input={r.input}): {outcome}")
    return "\n".join(lines) if lines else "  (no individual failures recorded)"


def build_code_retry_messages(
    problem_text: str,
    entry_function: str,
    plan_steps: list[PlanStep],
    test_cases: list[TestCase],
    previous_code: str,
    test_results: list[TestExecutionResult],
    sandbox_error: str | None = None,
) -> list[dict[str, Any]]:
    plan_str = "\n".join(f"  {s.step_number}. {s.action} — {s.rationale}" for s in plan_steps)
    failure_block = _format_failures(test_results)
    sandbox_note = f"\n\nSandbox-level error: {sandbox_error}" if sandbox_error else ""
    user = (
        f"{_entry_function_constraint(entry_function)}\n\n"
        "Problem:\n"
        f"{problem_text}\n\n"
        "Plan:\n"
        f"{plan_str}\n\n"
        "Test cases:\n"
        f"{_format_test_cases(test_cases)}\n\n"
        "Your previous attempt failed sandbox verification.\n\n"
        "Previous code:\n"
        "```python\n"
        f"{previous_code}\n"
        "```\n\n"
        "Test results:\n"
        f"{failure_block}"
        f"{sandbox_note}\n\n"
        "Generate a corrected version that addresses the specific failures above. "
        "Return ONLY a JSON object of the form:\n"
        '{"code": "<full python source>", "explanation": "<<=150 words plain language>"}\n'
        "No prose outside the JSON."
    )
    return [
        {"role": "system", "content": SYSTEM_MESSAGE},
        {"role": "user", "content": user},
    ]
