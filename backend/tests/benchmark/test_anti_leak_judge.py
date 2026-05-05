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
