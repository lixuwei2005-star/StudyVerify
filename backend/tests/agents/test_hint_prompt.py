"""Unit tests for build_hint_prompt — per-topic anti-leak constraint injection.

Step 11 Day 2 introduced TOPIC_ANTI_LEAK_CONSTRAINTS so the hint LLM is
explicitly forbidden from naming the algorithmic pattern for high-leak topics
(recursion, two-pointers, etc.). These tests pin the integration: matching
topics inject constraints, non-matching topics do not, and the constraint
block appears in the system prompt (where the rules live), not the user
message (where context lives).
"""

from __future__ import annotations

from app.agents.hint.prompts import TOPIC_ANTI_LEAK_CONSTRAINTS, build_hint_prompt
from app.agents.hint.schemas import HintInput


def _input(topics: list[str] | None = None) -> HintInput:
    return HintInput(
        problem_text="Return the sum of a list.",
        student_code="def sum_list(nums):\n    return 0",
        failed_test_inputs=["[1, 2, 3]"],
        prior_hints=[],
        topics=topics or [],
    )


def test_recursion_topic_injects_constraint_into_system_prompt() -> None:
    prompt = build_hint_prompt(_input(topics=["recursion"]))

    assert "## Topic-specific anti-leak constraints" in prompt["system"]
    assert TOPIC_ANTI_LEAK_CONSTRAINTS["recursion"] in prompt["system"]
    # User message stays clean — constraints are rules, not context.
    assert "Topic-specific anti-leak constraints" not in prompt["user"]


def test_two_pointers_topic_injects_constraint() -> None:
    prompt = build_hint_prompt(_input(topics=["two-pointers"]))

    assert TOPIC_ANTI_LEAK_CONSTRAINTS["two-pointers"] in prompt["system"]
    # Spot-check a forbidden phrase actually appears in the rendered block.
    assert "'left pointer'" in prompt["system"]


def test_two_pointers_constraint_includes_evasion_words() -> None:
    """Step 11.5: the two-pointers constraint must list the evasion phrases
    the LLM used in Step 11 to slip past the original constraint
    ('two indices', 'starting position', 'leftmost', etc.)."""
    constraint = TOPIC_ANTI_LEAK_CONSTRAINTS["two-pointers"]
    for evasion in (
        "'two indices'",
        "'starting position'",
        "'leftmost'",
        "'rightmost'",
        "'from both ends'",
        "'advance the pointer'",
    ):
        assert evasion in constraint, f"missing evasion phrase {evasion}"


def test_no_matching_topic_does_not_inject_constraint_section() -> None:
    # 'array' and 'math' are not in TOPIC_ANTI_LEAK_CONSTRAINTS — no block.
    prompt = build_hint_prompt(_input(topics=["array", "math"]))

    assert "## Topic-specific anti-leak constraints" not in prompt["system"]


def test_empty_topics_does_not_inject_constraint_section() -> None:
    prompt = build_hint_prompt(_input(topics=[]))

    assert "## Topic-specific anti-leak constraints" not in prompt["system"]


def test_multiple_matching_topics_inject_all_constraint_blocks() -> None:
    # tree+recursion is a common combo (binary tree traversal). Both blocks
    # must appear so the LLM sees the full forbidden vocabulary.
    prompt = build_hint_prompt(_input(topics=["tree", "recursion"]))

    assert TOPIC_ANTI_LEAK_CONSTRAINTS["tree"] in prompt["system"]
    assert TOPIC_ANTI_LEAK_CONSTRAINTS["recursion"] in prompt["system"]
    # Section header appears exactly once even with multiple matches.
    assert prompt["system"].count("## Topic-specific anti-leak constraints") == 1


def test_constraint_section_is_ordered_deterministically() -> None:
    # Insertion-order of TOPIC_ANTI_LEAK_CONSTRAINTS dict drives the output
    # order regardless of input topic ordering, so two calls with the same
    # topic set in different orders produce identical prompts.
    prompt_a = build_hint_prompt(_input(topics=["recursion", "tree"]))
    prompt_b = build_hint_prompt(_input(topics=["tree", "recursion"]))

    assert prompt_a["system"] == prompt_b["system"]
