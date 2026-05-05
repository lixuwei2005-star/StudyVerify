"""Shape tests for benchmark.eval_pipeline.evaluate_problem.

The API client and gateway are mocked; we just confirm the orchestration
threads success and failure paths through the right structure without
calling the real backend.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

from benchmark.eval_pipeline import evaluate_problem
from benchmark.helpful_judge import quotes_hint


# ---------- quotes_hint ----------


def test_quotes_hint_exact_5_word_run() -> None:
    assert quotes_hint(
        proposed_change="I will check the relationship between the elements first.",
        hint_text="Think about the relationship between the elements when summing.",
    )


def test_quotes_hint_below_threshold() -> None:
    assert not quotes_hint(
        proposed_change="Use a hash map to store seen numbers.",
        hint_text="What relationship must exist between two numbers?",
    )


def test_quotes_hint_punctuation_insensitive() -> None:
    # Punctuation between words shouldn't break the match.
    assert quotes_hint(
        proposed_change="...the relationship, between, the elements...",
        hint_text="Think about the relationship between the elements when summing.",
    )


def test_quotes_hint_too_short_hint() -> None:
    # Hint with fewer than 5 words can never be quoted at threshold 5.
    assert not quotes_hint(
        proposed_change="anything goes here",
        hint_text="Try harder",
    )


def test_quotes_hint_case_insensitive() -> None:
    assert quotes_hint(
        proposed_change="THE RELATIONSHIP BETWEEN THE ELEMENTS",
        hint_text="the relationship between the elements matters",
    )


def _problem() -> dict:
    return {
        "id": "test-p1",
        "title": "Test",
        "problem_text": "Return n + 1 for any integer n.",
        "entry_function": "inc",
        "reference_solution": "def inc(n):\n    return n + 1\n",
        "test_cases": [{"input": "1", "expected": "2", "description": "basic"}],
        "difficulty": "easy",
        "topics": ["math"],
        "variants": [
            {
                "name": "noop",
                "code": "def inc(n):\n    return n\n",
                "expected_failure_count": 1,
                "error_pattern": "no-implementation",
            }
        ],
    }


def _ok(data: dict) -> dict:
    return {"success": True, "latency_ms": 100, "data": data, "error": None}


def _fail(error: str) -> dict:
    return {"success": False, "latency_ms": 50, "data": None, "error": error}


async def test_evaluate_problem_handles_solver_failure() -> None:
    api = AsyncMock()
    api.solve = AsyncMock(return_value=_fail("HTTP 502"))
    llm = AsyncMock()

    result = await evaluate_problem(_problem(), api, llm)

    assert result["solve"]["success"] is False
    assert "solver failed" in result["errors"][0]
    # Must not have attempted reference verify or variants
    assert result["reference_check"] is None
    assert result["variants"] == []


async def test_evaluate_problem_full_success_shape() -> None:
    api = AsyncMock()
    api.solve = AsyncMock(return_value=_ok({"session_id": "s1"}))
    api.verify = AsyncMock(
        side_effect=[
            _ok({"session_id": "v-ref", "output": {"verified": True}}),
            _ok({"session_id": "v-var", "output": {"verified": False}}),
        ]
    )
    api.hint = AsyncMock(
        return_value=_ok({"session_id": "h", "hint_index": 1, "hint_text": "ok hint"})
    )

    llm = AsyncMock()
    llm.chat = AsyncMock(
        side_effect=[
            # hint 1 anti-leak judge
            '{"leaks": false, "reason": ""}',
            # hint 1 helpfulness judge
            '{"understood_hint": true, "would_fix_bug": false, "proposed_change": "x"}',
        ]
        * 5
    )

    result = await evaluate_problem(_problem(), api, llm)

    assert result["solve"]["success"] is True
    assert result["reference_check"]["verifier_correct"] is True
    assert len(result["variants"]) == 1
    v = result["variants"][0]
    assert v["verify"]["verifier_correct"] is True  # variant verified=False, expected fail = True
    assert len(v["hints"]) == 5
    assert all(h["text"] == "ok hint" for h in v["hints"])
    assert all(h["anti_leak"]["passes"] for h in v["hints"])


async def test_evaluate_problem_handles_variant_verify_failure() -> None:
    api = AsyncMock()
    api.solve = AsyncMock(return_value=_ok({"session_id": "s1"}))
    api.verify = AsyncMock(
        side_effect=[
            _ok({"session_id": "v-ref", "output": {"verified": True}}),
            _fail("HTTP 504"),
        ]
    )
    api.hint = AsyncMock()  # should never be called
    llm = AsyncMock()

    result = await evaluate_problem(_problem(), api, llm)

    assert len(result["variants"]) == 1
    assert result["variants"][0]["verify"]["success"] is False
    assert result["variants"][0]["hints"] == []
    api.hint.assert_not_called()
