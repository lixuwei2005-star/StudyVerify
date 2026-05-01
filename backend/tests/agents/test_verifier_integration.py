r"""Integration tests for VerifierAgent — real DeepSeek + real Docker daemon.

Gated on DEEPSEEK_API_KEY presence AND a reachable Docker daemon. These are
the behavioral acceptance tests for the anti-leak guarantees. The unit suite
proves structural impossibility (the schema has no `expected` field, the
prompt builder doesn't read `expected`); this suite proves the deployed
system actually behaves correctly when the real LLM produces real text.

Fixture choice rationale (resolves plan ambiguity #5):
The existing fixtures in tests/agents/fixtures/sample_problems.json all use
short expected values like "0", "6", "5", "None" — too short for the
"expected value not in diagnosis" substring check to be reliable, because
"None" and single digits can plausibly appear in English tutoring text
without any actual leakage. We inline a custom doubling problem here whose
expected values are list reprs ("[2, 4, 6]", "[20, 40]", "[-2, -10]") that
cannot plausibly appear in English text by accident — only a real leak
would put them there.

Test 2 regex tightening (resolves plan ambiguity #2):
- r"\bdef\s+\w+\s*\("  requires an open paren so "define" / "default"
                       in English doesn't trigger a false code-leak.
- r"\breturn\s+\S"     keeps as-is — English "return" usually flows
                       differently from "return X" in code.
- "```" literal        catches any fenced code block.
"""

from __future__ import annotations

import re

import docker
import pytest

from app.agents.solver.schemas import TestCase
from app.agents.verifier.agent import (
    TIMEOUT_DIAGNOSIS,
    VerifierAgent,
)
from app.agents.verifier.schemas import VerifierInput
from app.core.config import get_settings
from app.llm.client import DeepSeekClient
from app.sandbox.docker_runner import DockerCodeRunner


def _docker_available() -> bool:
    try:
        docker.from_env().ping()
        return True
    except Exception:
        return False


pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not get_settings().DEEPSEEK_API_KEY,
        reason="DEEPSEEK_API_KEY not set (env or backend/.env); skipping live tests",
    ),
    pytest.mark.skipif(not _docker_available(), reason="Docker daemon not reachable"),
]


# Fixture problem: doubling with multi-char expected list reprs.
PROBLEM_TEXT = (
    "Write a Python function `double(nums)` that returns a NEW list where "
    "each element of the input list is doubled. The order of elements is "
    "preserved."
)
TEST_CASES = [
    TestCase(input="[1, 2, 3]", expected="[2, 4, 6]", description="basic"),
    TestCase(input="[10, 20]", expected="[20, 40]", description="two elements"),
    TestCase(input="[-1, -5]", expected="[-2, -10]", description="negatives"),
]


@pytest.fixture
def agent() -> VerifierAgent:
    settings = get_settings()
    return VerifierAgent(
        sandbox_runner=DockerCodeRunner(),
        llm_client=DeepSeekClient(settings),
    )


# ---------------------------------------------------------------------------
# 1. Correct solution → verified=True, no diagnosis, output redacts expected.
# ---------------------------------------------------------------------------
async def test_correct_solution_verifies_true(agent: VerifierAgent) -> None:
    student_code = "def double(nums):\n    return [n * 2 for n in nums]\n"
    inp = VerifierInput(
        problem_id="py-test-double-list",
        problem_text=PROBLEM_TEXT,
        entry_function="double",
        test_cases=TEST_CASES,
        student_code=student_code,
    )

    result = await agent.verify(inp)

    assert result.verified is True
    assert result.status == "all_passed"
    assert result.diagnosis == ""
    assert result.pass_count == 3
    assert result.fail_count == 0

    # End-to-end redaction: items lack the expected attribute, and
    # serialization doesn't sneak it in.
    assert all(not hasattr(tr, "expected") for tr in result.test_results)
    for tr in result.test_results:
        assert "expected" not in tr.model_dump()


# ---------------------------------------------------------------------------
# 2. Buggy solution → diagnosis arrives, contains no Python code, leaks no
# expected values. THIS IS THE CENTRAL ACCEPTANCE TEST for prompt safety.
# ---------------------------------------------------------------------------
async def test_buggy_solution_gets_diagnosis(
    agent: VerifierAgent,
    capfd: pytest.CaptureFixture[str],
) -> None:
    # Bug: returns input unchanged. All three tests fail with actual=input.
    student_code = "def double(nums):\n    return nums\n"
    inp = VerifierInput(
        problem_id="py-test-double-list",
        problem_text=PROBLEM_TEXT,
        entry_function="double",
        test_cases=TEST_CASES,
        student_code=student_code,
    )

    result = await agent.verify(inp)

    assert result.verified is False
    assert result.status == "some_failed"
    assert result.fail_count > 0
    assert result.diagnosis, "expected non-empty LLM diagnosis"

    # Print diagnosis so the test author can read what the LLM actually said.
    # Visible with `pytest -s` or on failure.
    print(f"\n=== Diagnosis from LLM ===\n{result.diagnosis}\n=========================")

    # Anti-code regex checks
    assert re.search(r"\bdef\s+\w+\s*\(", result.diagnosis) is None, (
        f"diagnosis contains a function definition: {result.diagnosis!r}"
    )
    assert re.search(r"\breturn\s+\S", result.diagnosis) is None, (
        f"diagnosis contains a return statement: {result.diagnosis!r}"
    )
    assert "```" not in result.diagnosis, (
        f"diagnosis contains a fenced code block: {result.diagnosis!r}"
    )

    # Anti-answer-leak: each multi-char expected value must NOT appear.
    for tc in inp.test_cases:
        assert tc.expected not in result.diagnosis, (
            f"diagnosis leaks expected value {tc.expected!r}: {result.diagnosis!r}"
        )

    # Output redaction: no item carries `expected`.
    assert all(not hasattr(tr, "expected") for tr in result.test_results)
    assert "expected" not in result.test_results[0].model_dump()


# ---------------------------------------------------------------------------
# 3. Syntax error → status=error, diagnosis="", LLM not consulted.
# ---------------------------------------------------------------------------
async def test_syntax_error_in_student_code(agent: VerifierAgent) -> None:
    student_code = "def broken(:\n    pass\n"  # literal syntax error
    inp = VerifierInput(
        problem_id="py-test-double-list",
        problem_text=PROBLEM_TEXT,
        entry_function="broken",
        test_cases=TEST_CASES,
        student_code=student_code,
    )

    result = await agent.verify(inp)

    assert result.verified is False
    assert result.status == "error"
    assert result.diagnosis == ""
    assert result.sandbox_error is not None
    assert "SyntaxError" in result.sandbox_error or "FATAL" in result.sandbox_error


# ---------------------------------------------------------------------------
# 4. Structurally-empty student code (sum_list returns 0). The LLM has
#    nothing to "correct" structurally and is tempted to dictate the
#    algorithm or name the mechanism ("use a loop", "use sum()", etc.).
#    Diagnosis must stay at the symptom/relationship level — no mechanism
#    names, no stepwise recipe.
#
#    Added after Step 5.1 Phase 6 surfaced this gap: the Verifier prompt
#    allowed "Consider using a loop or a built-in function to add up the
#    values" — naming the mechanism is the same class of leak as algorithm
#    dictation. Mirrors the parallel hint test
#    test_minimal_code_hint_no_algorithm_dictation.
# ---------------------------------------------------------------------------
async def test_minimal_code_diagnosis_no_algorithm_dictation(
    agent: VerifierAgent,
    capfd: pytest.CaptureFixture[str],
) -> None:
    sum_list_problem = (
        "Write a Python function `sum_list(nums)` that returns the sum of "
        "all numbers in the input list of integers. Return 0 for an empty list."
    )
    student_code = "def sum_list(nums):\n    return 0\n"
    test_cases = [
        TestCase(input="[1, 2, 3]", expected="6", description=""),
        TestCase(input="[5, 5, 5]", expected="15", description=""),
        TestCase(input="[]", expected="0", description=""),
    ]
    inp = VerifierInput(
        problem_id="py-test-sum-empty",
        problem_text=sum_list_problem,
        entry_function="sum_list",
        test_cases=test_cases,
        student_code=student_code,
    )

    result = await agent.verify(inp)

    diagnosis = result.diagnosis
    assert diagnosis, "expected non-empty diagnosis for failing structurally-empty code"

    print(
        f"\n=== Sum-list minimal-code diagnosis ===\n{diagnosis}\n======================================="
    )

    # Anti-code regex (same as test #2).
    assert re.search(r"\bdef\s+\w+\s*\(", diagnosis) is None, (
        f"diagnosis contains a function definition: {diagnosis!r}"
    )
    assert re.search(r"\breturn\s+\S", diagnosis) is None, (
        f"diagnosis contains a return statement: {diagnosis!r}"
    )
    assert "```" not in diagnosis, f"diagnosis contains a fenced code block: {diagnosis!r}"

    # Anti-algorithm-dictation phrase contract. Parallel to the hint test's
    # forbidden list; broader because diagnosis is one-shot and tempted
    # toward naming the mechanism cleanly ("use sum()", "use a built-in").
    forbidden_phrases = (
        "use a loop",
        "using a loop",
        "with a loop",
        "for loop",
        "while loop",
        "iterate through",
        "iterate over",
        "loop through",
        "loop over",
        "create a variable",
        "running total",
        "accumulate",
        "use sum(",
        "use a built-in",
        "built-in function",
        "list comprehension",
    )
    diagnosis_lower = diagnosis.lower()
    for phrase in forbidden_phrases:
        assert phrase not in diagnosis_lower, (
            f"diagnosis dictated algorithm/mechanism: contained {phrase!r}: {diagnosis!r}"
        )

    # Expected-output substring check (only multi-char expecteds — "0", "6"
    # are too short to be reliable).
    for tc in test_cases:
        if tc.expected and len(tc.expected) > 2:
            assert tc.expected not in diagnosis, (
                f"diagnosis leaks expected value {tc.expected!r}: {diagnosis!r}"
            )


# ---------------------------------------------------------------------------
# 5. Timeout → deterministic message, no LLM call.
# ---------------------------------------------------------------------------
async def test_timeout_solution_gets_deterministic_message(agent: VerifierAgent) -> None:
    student_code = "def double(nums):\n    while True:\n        pass\n"
    inp = VerifierInput(
        problem_id="py-test-double-list",
        problem_text=PROBLEM_TEXT,
        entry_function="double",
        test_cases=TEST_CASES,
        student_code=student_code,
    )

    result = await agent.verify(inp)

    assert result.verified is False
    assert result.status == "timeout"
    assert result.diagnosis == TIMEOUT_DIAGNOSIS
