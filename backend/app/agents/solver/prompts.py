from __future__ import annotations

from typing import Any

from app.agents.solver.schemas import PlanStep, TestCase

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
    plan_steps: list[PlanStep],
    test_cases: list[TestCase],
) -> list[dict[str, Any]]:
    plan_str = "\n".join(f"  {s.step_number}. {s.action} — {s.rationale}" for s in plan_steps)
    user = (
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
