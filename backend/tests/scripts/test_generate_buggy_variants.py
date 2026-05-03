"""Unit tests for app.scripts.generate_buggy_variants (Step 6.3).

The CLI's only external boundary is the LLMGateway. We mock it with AsyncMock
so no real LLM is called. Validation logic is exercised on synthetic raw
payloads. The fixture file is read for its real shape (entry_function +
reference_solution come from the actual sample_problems.json).
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.scripts import generate_buggy_variants as gen


def _problem(entry_function: str = "factorial") -> dict:
    return {
        "problem_id": "py-005-factorial",
        "problem_text": "Compute n!",
        "entry_function": entry_function,
        "reference_solution": "def factorial(n):\n    return 1\n",
    }


def _wrapped(variants: list[dict]) -> str:
    return json.dumps({"variants": variants})


def _good_variant(name: str = "factorial", category: str = "off-by-one") -> dict:
    return {
        "category": category,
        "code": f"def {name}(n):\n    return 0\n",
    }


def _gateway_with_responses(*responses: str) -> MagicMock:
    gateway = MagicMock()
    gateway.chat = AsyncMock(side_effect=list(responses))
    return gateway


# ---- Test 1: valid wrapped JSON object parses on first attempt ----


@pytest.mark.asyncio
async def test_wrapped_object_parses_on_first_attempt() -> None:
    raw = _wrapped([_good_variant() for _ in range(3)])
    gateway = _gateway_with_responses(raw)
    result = await gen._generate(gateway, problem=_problem(), count=3, model=None)
    assert len(result) == 3
    assert all(v["category"] for v in result)
    assert gateway.chat.await_count == 1


# ---- Test 2: bare legacy JSON array is rejected and triggers retry ----


@pytest.mark.asyncio
async def test_bare_array_triggers_retry_then_succeeds() -> None:
    bare = json.dumps([_good_variant() for _ in range(2)])
    good = _wrapped([_good_variant() for _ in range(2)])
    gateway = _gateway_with_responses(bare, good)
    result = await gen._generate(gateway, problem=_problem(), count=2, model=None)
    assert len(result) == 2
    assert gateway.chat.await_count == 2


# ---- Test 3: malformed JSON triggers retry once ----


@pytest.mark.asyncio
async def test_malformed_json_triggers_retry_once() -> None:
    garbage = "not json at all {{{ ["
    good = _wrapped([_good_variant() for _ in range(2)])
    gateway = _gateway_with_responses(garbage, good)
    result = await gen._generate(gateway, problem=_problem(), count=2, model=None)
    assert len(result) == 2
    assert gateway.chat.await_count == 2


# ---- Test 4: after 2 failures, GeneratorError with clear message ----


@pytest.mark.asyncio
async def test_two_failures_raise_generator_error() -> None:
    bad1 = "not json"
    bad2 = "still not json"
    gateway = _gateway_with_responses(bad1, bad2)
    with pytest.raises(gen.GeneratorError) as excinfo:
        await gen._generate(gateway, problem=_problem(), count=2, model=None)
    assert "validation failed twice" in str(excinfo.value)
    assert gateway.chat.await_count == 2


# ---- Test 5: variant missing 'category' or 'code' is rejected ----


@pytest.mark.asyncio
async def test_variant_missing_required_keys_is_rejected() -> None:
    bad = _wrapped(
        [
            {"category": "off-by-one"},  # missing 'code'
            _good_variant(),
        ]
    )
    good = _wrapped([_good_variant() for _ in range(2)])
    gateway = _gateway_with_responses(bad, good)
    result = await gen._generate(gateway, problem=_problem(), count=2, model=None)
    assert len(result) == 2
    assert gateway.chat.await_count == 2


# ---- Test 6: variant code that does not define entry_function is rejected ----


@pytest.mark.asyncio
async def test_wrong_entry_function_is_rejected() -> None:
    wrong = _wrapped(
        [
            {"category": "off-by-one", "code": "def helper(n):\n    return 0\n"},
            _good_variant(),
        ]
    )
    good = _wrapped([_good_variant() for _ in range(2)])
    gateway = _gateway_with_responses(wrong, good)
    result = await gen._generate(gateway, problem=_problem(), count=2, model=None)
    assert all("factorial" in v["code"] for v in result)
    assert gateway.chat.await_count == 2


# ---- Test 7: syntactically invalid Python code is rejected ----


@pytest.mark.asyncio
async def test_syntactically_invalid_code_is_rejected() -> None:
    bad = _wrapped(
        [
            {
                "category": "type-confusion",
                "code": "def factorial(n)\n    return 0",
            },  # missing colon
            _good_variant(),
        ]
    )
    with pytest.raises(gen.GeneratorError) as excinfo:
        gateway = _gateway_with_responses(bad, bad)
        await gen._generate(gateway, problem=_problem(), count=2, model=None)
    assert "SyntaxError" in str(excinfo.value)
