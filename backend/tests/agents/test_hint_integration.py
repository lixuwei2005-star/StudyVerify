r"""Integration tests for HintAgent — real DeepSeek calls.

Gated on DEEPSEEK_API_KEY presence. These are the behavioral acceptance
tests for the anti-leak guarantees on hints. The unit suite proves the
schema and prompt builder cannot reach `expected` values; this suite
proves the deployed system behaves correctly when the real LLM produces
real text.

Fixture choice mirrors test_verifier_integration.py: a doubling problem
whose expected values are list reprs ("[2, 4, 6]", "[20, 40]", "[-2, -10]")
that cannot plausibly appear in English tutoring text by accident — only
a real leak would put them there.

Anti-code regex (same as verifier integration test 2):
- r"\bdef\s+\w+\s*\("  open paren so "define" / "default" doesn't false-trigger
- r"\breturn\s+\S"     literal "return X" code shape, not English flow
- "```" literal        catches any fenced code block
"""

from __future__ import annotations

import re

import pytest

from app.agents.hint.agent import HintAgent
from app.agents.hint.schemas import HintInput, RetrievedContext
from app.core.config import get_settings
from app.llm.client import DeepSeekClient
from app.services.retrieval_service import FORBIDDEN_HINT_PHRASES

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not get_settings().DEEPSEEK_API_KEY,
        reason="DEEPSEEK_API_KEY not set (env or backend/.env); skipping live tests",
    ),
]


# Fixture problem: doubling with multi-char expected list reprs.
PROBLEM_TEXT = (
    "Write a Python function `double(nums)` that returns a NEW list where "
    "each element of the input list is doubled. The order of elements is "
    "preserved."
)
# Buggy student code: returns input unchanged. All tests fail with actual=input.
STUDENT_CODE = "def double(nums):\n    return nums\n"
FAILED_TEST_INPUTS = ["[1, 2, 3]", "[10, 20]", "[-1, -5]"]
EXPECTED_VALUES = ["[2, 4, 6]", "[20, 40]", "[-2, -10]"]

# Out-of-hints fallback markers (system prompt: "I've given as many hints
# as I can without revealing the answer. Please review the problem
# statement carefully.")
_OUT_OF_HINTS_MARKERS = ("as i can", "review the problem", "review the spec")

# Phrases that constitute algorithm dictation in English. Added after Step
# 5.1 Phase 6 smoke surfaced the LLM verbalizing the full algorithm when
# student code is structurally empty (e.g. `return 0`). The contract is
# that none of these phrases may appear in any hint — the prompt must keep
# the LLM at a conceptual level, asking questions rather than describing
# steps.
_FORBIDDEN_ALGORITHM_PHRASES = (
    "create a variable",
    "loop through",
    "loop over",
    "iterate through",
    "iterate over",
    "for each element",
    "running total",
    "accumulate",
    "return that variable",
    "after the loop",
)


@pytest.fixture
def agent() -> HintAgent:
    settings = get_settings()
    return HintAgent(llm_client=DeepSeekClient(settings))


def _assert_no_code_or_answer_leak(hint_text: str) -> None:
    assert hint_text.strip(), "expected non-empty hint text"

    assert re.search(r"\bdef\s+\w+\s*\(", hint_text) is None, (
        f"hint contains a function definition: {hint_text!r}"
    )
    assert re.search(r"\breturn\s+\S", hint_text) is None, (
        f"hint contains a return statement: {hint_text!r}"
    )
    assert "```" not in hint_text, f"hint contains a fenced code block: {hint_text!r}"

    for expected in EXPECTED_VALUES:
        assert expected not in hint_text, f"hint leaks expected value {expected!r}: {hint_text!r}"


# ---------------------------------------------------------------------------
# 1. First hint: no prior hints. Hint must contain no code and no answer leak.
# ---------------------------------------------------------------------------
async def test_first_hint_no_code_no_answer_leak(agent: HintAgent) -> None:
    hint_input = HintInput(
        problem_text=PROBLEM_TEXT,
        student_code=STUDENT_CODE,
        failed_test_inputs=FAILED_TEST_INPUTS,
        prior_hints=[],
    )

    output = await agent.generate(hint_input)

    print(f"\n=== Hint #1 from LLM ===\n{output.hint_text}\n========================")

    _assert_no_code_or_answer_leak(output.hint_text)


# ---------------------------------------------------------------------------
# 2. Second hint: prior_hints contains the first hint. Same anti-leak checks.
#    Do NOT assert text inequality — temperature=0.4 may produce similar
#    phrasing on rare occasions and the test would flake.
# ---------------------------------------------------------------------------
async def test_second_hint_passes_anti_leak(agent: HintAgent) -> None:
    first_input = HintInput(
        problem_text=PROBLEM_TEXT,
        student_code=STUDENT_CODE,
        failed_test_inputs=FAILED_TEST_INPUTS,
        prior_hints=[],
    )
    first = await agent.generate(first_input)
    _assert_no_code_or_answer_leak(first.hint_text)

    second_input = HintInput(
        problem_text=PROBLEM_TEXT,
        student_code=STUDENT_CODE,
        failed_test_inputs=FAILED_TEST_INPUTS,
        prior_hints=[first.hint_text],
    )
    second = await agent.generate(second_input)

    print(f"\n=== Hint #1 from LLM ===\n{first.hint_text}\n========================")
    print(f"\n=== Hint #2 from LLM ===\n{second.hint_text}\n========================")

    _assert_no_code_or_answer_leak(second.hint_text)


# ---------------------------------------------------------------------------
# 3. Structurally-empty student code (sum_list returns 0). The LLM has
#    nothing to "correct" structurally and is tempted to teach the entire
#    algorithm. Hint must stay conceptual (questions, not steps).
#
#    This test was added after Step 5.1 Phase 6 smoke surfaced the LLM
#    dictating algorithm steps when student code is structurally empty.
# ---------------------------------------------------------------------------
async def test_minimal_code_hint_no_algorithm_dictation(agent: HintAgent) -> None:
    sum_list_problem = (
        "Write a Python function `sum_list(nums)` that returns the sum of "
        "all numbers in the input list of integers. Return 0 for an empty list."
    )
    hint_input = HintInput(
        problem_text=sum_list_problem,
        student_code="def sum_list(nums):\n    return 0\n",
        failed_test_inputs=["[1, 2, 3]", "[5, 5, 5]", "[]"],
        prior_hints=[],
    )

    output = await agent.generate(hint_input)

    print(
        f"\n=== Sum-list minimal-code hint ===\n{output.hint_text}\n"
        "=================================="
    )

    # Same anti-code regex as test #1.
    assert output.hint_text.strip(), "expected non-empty hint text"
    assert re.search(r"\bdef\s+\w+\s*\(", output.hint_text) is None, (
        f"hint contains a function definition: {output.hint_text!r}"
    )
    assert re.search(r"\breturn\s+\S", output.hint_text) is None, (
        f"hint contains a return statement: {output.hint_text!r}"
    )
    assert "```" not in output.hint_text, f"hint contains a fenced code block: {output.hint_text!r}"

    # Anti-algorithm-dictation phrase check.
    hint_lower = output.hint_text.lower()
    for phrase in _FORBIDDEN_ALGORITHM_PHRASES:
        assert phrase not in hint_lower, (
            f"hint dictated algorithm: contained {phrase!r}: {output.hint_text!r}"
        )


# ---------------------------------------------------------------------------
# 4. Fourth hint (3 priors): either another specific hint, OR the explicit
#    "out of hints" fallback the prompt allows. Both outcomes acceptable as
#    long as no code/answer leaks.
# ---------------------------------------------------------------------------
async def test_fourth_hint_or_out_of_hints_fallback(agent: HintAgent) -> None:
    priors = [
        (
            "Your function's behavior on the input differs from the problem "
            "requirement. Re-read the spec."
        ),
        "Specifically, think about how each element of the list should change.",
        (
            "The required output has a different relationship to each input "
            "element than what your code produces."
        ),
    ]
    hint_input = HintInput(
        problem_text=PROBLEM_TEXT,
        student_code=STUDENT_CODE,
        failed_test_inputs=FAILED_TEST_INPUTS,
        prior_hints=priors,
    )

    output = await agent.generate(hint_input)

    print(f"\n=== Hint #4 from LLM ===\n{output.hint_text}\n========================")

    _assert_no_code_or_answer_leak(output.hint_text)

    # Either outcome is acceptable; just confirm one path holds.
    text_lower = output.hint_text.lower()
    is_fallback = any(marker in text_lower for marker in _OUT_OF_HINTS_MARKERS)
    is_specific_hint = bool(output.hint_text.strip())
    assert is_fallback or is_specific_hint


# ---------------------------------------------------------------------------
# 5. RAG drift regression — Step 6.2 Phase 7 surfaced LLM hints biased toward
#    algorithm-specific English when retrieved_context contained 3 nearly-
#    identical "always returns 0" diagnoses. The example leak:
#      "What single arithmetic operation can you apply to each element to
#       gradually build up the final total?"
#
#    Three-layer contract:
#      (a) anti-code regex (def/return/fence) — same as test #1
#      (b) 24-phrase forbidden list from retrieval_service.FORBIDDEN_HINT_PHRASES
#      (c) no-input-value substring — hint must not mention any failed_test_input
#          verbatim. This was added after smoke surfaced "the result should be 6
#          for [1, 2, 3]" — a Rule-4 (no expected outputs) leak that the LLM
#          smuggled through via mental computation. The prompt rule + service-
#          layer regeneration guardrail are the primary fix; this test locks
#          the contract.
#    The earlier "?" requirement was dropped: it conflated "conceptual" with
#    "ends in ?" and disagreed with the prompt's own GOOD examples that include
#    "Walk through your code mentally..." (declarative).
# ---------------------------------------------------------------------------
async def test_rag_does_not_induce_algorithm_dictation(agent: HintAgent) -> None:
    sum_list_problem = (
        "Write a Python function `sum_list(nums)` that returns the sum of "
        "all numbers in the input list of integers. Return 0 for an empty list."
    )
    # Three near-identical past-failure diagnoses — the exact corpus shape that
    # induced drift in Phase 7. If the prompt holds, the agent treats them as
    # inspiration only and stays at the conceptual level.
    retrieved = [
        RetrievedContext(
            similarity=0.83,
            past_diagnosis=(
                "Your function always returns 0, but it should compute the sum "
                "of the numbers in the list."
            ),
            past_hint_texts=[],
        ),
        RetrievedContext(
            similarity=0.82,
            past_diagnosis=(
                "Your function returns 0 regardless of the input. It needs to "
                "actually combine the elements."
            ),
            past_hint_texts=[],
        ),
        RetrievedContext(
            similarity=0.81,
            past_diagnosis=(
                "Your function returns 0 for every input, not just empty lists. "
                "The output must depend on the input."
            ),
            past_hint_texts=[],
        ),
    ]
    hint_input = HintInput(
        problem_text=sum_list_problem,
        student_code="def sum_list(nums):\n    return 0\n",
        failed_test_inputs=["[1, 2, 3]", "[5, 5, 5]", "[]"],
        prior_hints=[],
        retrieved_context=retrieved,
    )

    output = await agent.generate(hint_input)

    print(f"\n=== RAG-bias hint ===\n{output.hint_text}\n=====================")

    text = output.hint_text
    # (a) Anti-code regex.
    assert text.strip(), "expected non-empty hint text"
    assert re.search(r"\bdef\s+\w+\s*\(", text) is None, (
        f"hint contains a function definition: {text!r}"
    )
    assert re.search(r"\breturn\s+\S", text) is None, f"hint contains a return statement: {text!r}"
    assert "```" not in text, f"hint contains a fenced code block: {text!r}"

    # (b) All 24 forbidden phrases absent (case-insensitive).
    text_lower = text.lower()
    for phrase in FORBIDDEN_HINT_PHRASES:
        assert phrase not in text_lower, (
            f"hint contains forbidden phrase {phrase!r} (RAG-induced drift): {text!r}"
        )

    # (c) No failed-test-input value mentioned verbatim (Rule 5: anti-leak of
    # specific inputs and computed answers).
    for inp in hint_input.failed_test_inputs:
        stripped = inp.strip()
        if len(stripped) < 3:
            continue
        assert stripped not in text, f"hint mentions failed input value {stripped!r}: {text!r}"
