"""Unit tests for TestCaseGeneratorService — LLM gateway is mocked.

Asserts the parse pipeline (JSON → list[TestCase] → length check), the
retry-once invariant on parse failure, and the terminal raise behavior.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock

import pytest

from app.services.test_case_generator import (
    TestCaseGeneratorError,
    TestCaseGeneratorService,
)


def _valid_payload(n: int = 5) -> str:
    return json.dumps(
        {
            "test_cases": [
                {
                    "input": f"[{i}]",
                    "expected": str(i),
                    "description": f"case {i}",
                }
                for i in range(n)
            ]
        }
    )


def _malformed_payload() -> str:
    # Truncated JSON — json.loads will raise.
    return '{"test_cases": [{"input": "[1]", '


def _wrong_shape_payload() -> str:
    # Missing the 'test_cases' key.
    return json.dumps({"cases": []})


# ---------- happy path ----------


async def test_generate_parses_valid_payload() -> None:
    llm = AsyncMock()
    llm.chat = AsyncMock(return_value=_valid_payload(5))
    service = TestCaseGeneratorService(llm=llm)

    cases = await service.generate("Write a function that sums a list.", "sum_list", n=5)

    assert len(cases) == 5
    assert cases[0].input == "[0]"
    assert cases[0].expected == "0"
    assert cases[0].description == "case 0"
    assert llm.chat.await_count == 1


async def test_generate_passes_n_to_prompt_and_parser() -> None:
    llm = AsyncMock()
    llm.chat = AsyncMock(return_value=_valid_payload(3))
    service = TestCaseGeneratorService(llm=llm)

    cases = await service.generate("Sum a list.", "sum_list", n=3)

    assert len(cases) == 3
    # Prompt body should mention the n value (so the LLM produces the right count).
    user_msg = llm.chat.call_args.args[0][1]["content"]
    assert "Generate 3 test cases" in user_msg
    assert "exactly 3 test cases" in user_msg


# ---------- retry behavior ----------


async def test_generate_retries_once_on_malformed_then_succeeds() -> None:
    llm = AsyncMock()
    llm.chat = AsyncMock(side_effect=[_malformed_payload(), _valid_payload(5)])
    service = TestCaseGeneratorService(llm=llm)

    cases = await service.generate("Sum a list.", "sum_list", n=5)

    assert len(cases) == 5
    assert llm.chat.await_count == 2


async def test_generate_retries_on_wrong_shape_then_succeeds() -> None:
    llm = AsyncMock()
    llm.chat = AsyncMock(side_effect=[_wrong_shape_payload(), _valid_payload(5)])
    service = TestCaseGeneratorService(llm=llm)

    cases = await service.generate("Sum a list.", "sum_list", n=5)

    assert len(cases) == 5
    assert llm.chat.await_count == 2


# ---------- terminal failure ----------


async def test_generate_raises_after_two_malformed_attempts() -> None:
    llm = AsyncMock()
    llm.chat = AsyncMock(side_effect=[_malformed_payload(), _malformed_payload()])
    service = TestCaseGeneratorService(llm=llm)

    with pytest.raises(TestCaseGeneratorError) as exc_info:
        await service.generate("Sum a list.", "sum_list", n=5)

    # Caps at 2 LLM calls — not 3.
    assert llm.chat.await_count == 2
    assert "after retry" in str(exc_info.value)


async def test_generate_raises_when_count_mismatch_persists() -> None:
    """LLM returns valid JSON but wrong number of cases — retry, still wrong → raise."""
    llm = AsyncMock()
    llm.chat = AsyncMock(side_effect=[_valid_payload(3), _valid_payload(3)])
    service = TestCaseGeneratorService(llm=llm)

    with pytest.raises(TestCaseGeneratorError) as exc_info:
        await service.generate("Sum a list.", "sum_list", n=5)

    assert "expected 5 test cases, got 3" in str(exc_info.value)
    assert llm.chat.await_count == 2
