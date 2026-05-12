"""Tests for anti-leak phrase filter and LLM judge wrapper.

Phrase filter is pure and synchronous — easy to assert. LLM judge is
mocked at the gateway boundary so the test is fast and deterministic.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from benchmark.anti_leak_judge import (
    check_llm_judge,
    check_no_leak,
    check_phrase_filter,
)


# ---------- phrase filter ----------


def test_phrase_filter_catches_loop_through() -> None:
    ok, matches = check_phrase_filter("Try to loop through the list and accumulate.")
    assert not ok
    assert "loop through" in matches


def test_phrase_filter_catches_iterate_over() -> None:
    ok, matches = check_phrase_filter("You should iterate over each element.")
    assert not ok
    assert "iterate over" in matches


def test_phrase_filter_catches_running_sum() -> None:
    ok, matches = check_phrase_filter("Keep a running sum as you go.")
    assert not ok
    assert "running sum" in matches or "running total" in matches


def test_phrase_filter_passes_socratic_hint() -> None:
    ok, matches = check_phrase_filter(
        "What value should the function return when the input has no elements?"
    )
    assert ok
    assert matches == []


def test_phrase_filter_case_insensitive() -> None:
    ok, _ = check_phrase_filter("Use SUM() to add them")
    assert not ok


# ---------- Step 11 Day 1: new entries derived from Step 10 LLM-judge catches ----------


def test_phrase_filter_catches_dictionary_lookup() -> None:
    ok, matches = check_phrase_filter(
        "Compare that to the expression you use in the dictionary lookup."
    )
    assert not ok
    assert "dictionary lookup" in matches


def test_phrase_filter_catches_slice_notation() -> None:
    ok, matches = check_phrase_filter(
        "Python's slice notation lets you specify a start, stop, and step."
    )
    assert not ok
    assert "slice notation" in matches


def test_phrase_filter_catches_complement() -> None:
    ok, matches = check_phrase_filter(
        "Which number matches the complement needed to reach the target?"
    )
    assert not ok
    assert "complement" in matches


def test_phrase_filter_catches_step_value_and_negative_step() -> None:
    ok, matches = check_phrase_filter(
        "What step value would let you traverse with a negative step?"
    )
    assert not ok
    assert "step value" in matches
    assert "negative step" in matches


def test_phrase_filter_catches_bare_list_comprehension() -> None:
    # Without the "use" prefix that the old entry required.
    ok, matches = check_phrase_filter(
        "A list comprehension can build the result in a single expression."
    )
    assert not ok
    assert "list comprehension" in matches


def test_phrase_filter_catches_string_method() -> None:
    ok, matches = check_phrase_filter(
        "Consider a Python string method that converts characters to lowercase."
    )
    assert not ok
    assert "string method" in matches


def test_phrase_filter_catches_dot_lower() -> None:
    ok, matches = check_phrase_filter("How can you call .lower() on c directly?")
    assert not ok
    assert ".lower()" in matches


def test_phrase_filter_catches_slice_literals() -> None:
    ok, matches = check_phrase_filter("What does the slice [:-1] exclude from the reversal?")
    assert not ok
    assert "[:-1]" in matches


def test_phrase_filter_passes_socratic_trace_hint() -> None:
    """Regression: a tracing/debugging Socratic hint must still pass.

    "Trace through" and "test cases" are common in valid Socratic hints
    — our Step 11 additions must not catch them.
    """
    ok, matches = check_phrase_filter(
        "Trace through what your code returns for the empty test case."
    )
    assert ok
    assert matches == []


def test_phrase_filter_passes_edge_case_hint() -> None:
    """Regression: asking about an edge case shouldn't trigger anything."""
    ok, matches = check_phrase_filter(
        "Did you handle the case where the input is empty or has one element?"
    )
    assert ok
    assert matches == []


# ---------- LLM judge wrapper ----------


async def test_llm_judge_passes_when_judge_says_no_leak() -> None:
    llm = AsyncMock()
    llm.chat = AsyncMock(return_value='{"leaks": false, "reason": "Socratic question"}')
    passes, reason = await check_llm_judge("clean hint", "problem", llm)
    assert passes is True
    assert reason == "Socratic question"


async def test_llm_judge_fails_when_judge_says_leak() -> None:
    llm = AsyncMock()
    llm.chat = AsyncMock(return_value='{"leaks": true, "reason": "names range()"}')
    passes, _ = await check_llm_judge("hint with range()", "problem", llm)
    assert passes is False


async def test_llm_judge_lenient_on_judge_error() -> None:
    """Judge returns malformed JSON: count as pass (lenient) but record reason."""
    llm = AsyncMock()
    llm.chat = AsyncMock(return_value="not json {{{")
    passes, reason = await check_llm_judge("hint", "problem", llm)
    assert passes is True
    assert "judge_error" in reason


async def test_llm_judge_lenient_on_chat_exception() -> None:
    llm = AsyncMock()
    llm.chat = AsyncMock(side_effect=RuntimeError("upstream timeout"))
    passes, reason = await check_llm_judge("hint", "problem", llm)
    assert passes is True
    assert "judge_error" in reason


# ---------- combined ----------


async def test_check_no_leak_both_layers_pass() -> None:
    llm = AsyncMock()
    llm.chat = AsyncMock(return_value='{"leaks": false, "reason": "ok"}')
    out = await check_no_leak("Did you handle the empty case?", "problem", llm)
    assert out["passes"] is True
    assert out["phrase_filter_passes"] is True
    assert out["llm_judge_passes"] is True


async def test_check_no_leak_overall_fails_if_either_fails() -> None:
    """Phrase pass, judge fails → overall fail."""
    llm = AsyncMock()
    llm.chat = AsyncMock(return_value='{"leaks": true, "reason": "subtle leak"}')
    out = await check_no_leak("clean-looking hint", "problem", llm)
    assert out["passes"] is False
    assert out["phrase_filter_passes"] is True
    assert out["llm_judge_passes"] is False
