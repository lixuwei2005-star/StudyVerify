# ruff: noqa: E501 -- prompt text intentionally exceeds line length for readability
"""Diagnostic prompt for the Verifier Agent.

Two anti-leak rules govern this module:

1. Never include `expected` values in either prompt. The system prompt and
   the user prompt together form the LLM's input window; if `expected` is
   not in that window, the LLM cannot leak it. Schema-level redaction is
   not enough — the LLM never gets to see the answer key in the first place.

2. Never include `test_case.description`. Descriptions are written for
   problem authors and may state the expected behavior literally
   (e.g., "empty list returns None"), which would defeat the redaction.

Up to 3 representative failed tests are included, preserving original test
order. We rely on test authors ordering tests basic-to-edge so the first
failure is the most instructive. If tests are randomized or reverse-sorted,
diagnosis quality degrades — that's an authoring concern.
"""

from app.sandbox.schemas import TestExecutionResult

DIAGNOSIS_SYSTEM_PROMPT = """You are a coding tutor reviewing a student's submission. Some test cases failed. Your job is to give targeted, educational feedback.

CRITICAL RULES:
1. DO NOT write any code in your response. Not even a snippet. Not even pseudocode that closely resembles the fix.
2. DO NOT show the correct output for failing tests. Show only the input that failed.
3. DO NOT reveal what the student should literally write.
4. Describe WHAT is wrong (what the symptom is) and HINT at the root cause. Let the student think.
5. Keep responses to 1-3 sentences.
6. No greetings, no "great attempt".
7. If multiple tests fail, identify the common root cause if there is one; otherwise mention the most instructive failure.

Example of GOOD feedback:
"Your function's behavior on empty input differs from what the problem requires. Re-read the problem statement and consider what should happen when there are no elements."
(GOOD because it describes the symptom without revealing the required output.)

Example of BAD feedback (DO NOT do this):
"Change line 3 to `return -1 if not items else max(items)`. The issue is your default return value."
(BAD because it gives the literal code.)

Another BAD example:
"For input [], the expected output is -1, not 0."
(BAD because it reveals the expected output.)
"""

_MAX_FAILED_TESTS_IN_PROMPT = 3


def build_diagnosis_prompt(
    problem_text: str,
    student_code: str,
    failed_tests: list[TestExecutionResult],
) -> dict[str, str]:
    """Returns {'system': ..., 'user': ...} for chat completion.

    Includes only `input`, `actual`, and (if present) `error` from each
    failed test. `expected` is intentionally never read here.
    """
    failures_text = "\n\n".join(
        (
            f"FAILED TEST {i + 1}\n"
            f"  Input: {tr.input}\n"
            f"  Student's output: {tr.actual}\n"
            f"  {'Error: ' + tr.error if tr.error else ''}"
        ).rstrip()
        for i, tr in enumerate(failed_tests[:_MAX_FAILED_TESTS_IN_PROMPT])
    )

    user_message = f"""PROBLEM:
{problem_text}

STUDENT'S CODE:
```python
{student_code}
```

{failures_text}

Provide diagnostic feedback per the rules in the system message."""

    return {
        "system": DIAGNOSIS_SYSTEM_PROMPT,
        "user": user_message,
    }
