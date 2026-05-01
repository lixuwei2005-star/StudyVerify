"""Unit tests for HintAgent — no real LLM.

Ten tests covering:
- Happy path (first and second hint)
- Anti-leak guards (no 'expected' in prompt, all prior hints in prompt)
- LLM error degrades to fallback
- Edge cases: empty failed_test_inputs, >3 failed_test_inputs capped
- Contract locks: temperature=0.4, .chat called (not .complete), first-hint framing
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from app.agents.hint.agent import LLM_FALLBACK_HINT, HintAgent
from app.agents.hint.schemas import HintInput, HintOutput
from app.llm.client import DeepSeekClient
from app.llm.exceptions import LLMError

# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


def _agent(
    llm_responses: list[str | Exception] | None = None,
) -> tuple[HintAgent, AsyncMock]:
    """Build a HintAgent with a mocked LLM client. Returns (agent, chat_mock)."""
    llm = AsyncMock(spec=DeepSeekClient)
    llm.chat = AsyncMock(side_effect=llm_responses or [])
    return HintAgent(llm_client=llm), llm.chat


def _input(
    *,
    problem_text: str = "Return the sum of a list.",
    student_code: str = "def sum_list(nums):\n    return 0",
    failed_test_inputs: list[str] | None = None,
    prior_hints: list[str] | None = None,
) -> HintInput:
    return HintInput(
        problem_text=problem_text,
        student_code=student_code,
        failed_test_inputs=failed_test_inputs if failed_test_inputs is not None else ["[1, 2, 3]"],
        prior_hints=prior_hints if prior_hints is not None else [],
    )


def _captured_prompt(chat_mock: AsyncMock) -> str:
    """Return system + user prompt content concatenated."""
    messages = chat_mock.call_args.kwargs["messages"]
    return messages[0]["content"] + "\n" + messages[1]["content"]


# ---------------------------------------------------------------------------
# 1. Happy path: first hint (no prior hints), returns hint text.
# ---------------------------------------------------------------------------
async def test_generate_first_hint_returns_hint_text() -> None:
    agent, chat = _agent(llm_responses=["Think about edge cases."])

    out = await agent.generate(_input(prior_hints=[]))

    assert isinstance(out, HintOutput)
    assert out.hint_text == "Think about edge cases."
    chat.assert_awaited_once()


# ---------------------------------------------------------------------------
# 2. Second hint: prior hint appears in the prompt sent to LLM.
# ---------------------------------------------------------------------------
async def test_generate_second_hint_includes_prior_hint_in_prompt() -> None:
    prior = "Think about edge cases."
    agent, chat = _agent(llm_responses=["Consider empty input specifically."])

    await agent.generate(_input(prior_hints=[prior]))

    prompt = _captured_prompt(chat)
    assert prior in prompt


# ---------------------------------------------------------------------------
# 3. Anti-leak: prompt must never contain a sentinel expected-output value.
#    HintInput carries only failed_test_inputs (no expected field), so the
#    caller is responsible for never passing expected values in. This test
#    confirms that even if a sentinel leaks into problem_text or student_code
#    it is present — but that the HintInput schema has no expected field at all.
# ---------------------------------------------------------------------------
async def test_prompt_omits_expected_values() -> None:
    """HintInput has no expected field — the schema itself is the anti-leak guard."""
    agent, chat = _agent(llm_responses=["A hint."])
    # Sentinel value that represents an expected output — it must not be
    # reachable from HintInput since the schema has no expected field.
    sentinel = "EXPECTED_SECRET_42"
    hint_input = _input(failed_test_inputs=["[]", "[1]"])

    await agent.generate(hint_input)

    prompt = _captured_prompt(chat)
    assert sentinel not in prompt
    # Confirm HintInput schema has no expected field
    assert "expected" not in HintInput.model_fields


# ---------------------------------------------------------------------------
# 4. All prior hints appear in the prompt.
# ---------------------------------------------------------------------------
async def test_prompt_includes_all_prior_hints() -> None:
    priors = ["First nudge.", "More specific now.", "Even closer."]
    agent, chat = _agent(llm_responses=["Almost there."])

    await agent.generate(_input(prior_hints=priors))

    prompt = _captured_prompt(chat)
    for h in priors:
        assert h in prompt


# ---------------------------------------------------------------------------
# 5. LLM error → fallback hint returned, no exception raised.
# ---------------------------------------------------------------------------
async def test_llm_error_returns_fallback_hint() -> None:
    agent, chat = _agent(llm_responses=[LLMError("timeout")])

    out = await agent.generate(_input())

    assert out.hint_text == LLM_FALLBACK_HINT
    chat.assert_awaited_once()


# ---------------------------------------------------------------------------
# 6. Empty failed_test_inputs: prompt builds without crashing.
# ---------------------------------------------------------------------------
async def test_prompt_builds_with_empty_failed_test_inputs() -> None:
    agent, chat = _agent(llm_responses=["A hint."])

    out = await agent.generate(_input(failed_test_inputs=[]))

    assert out.hint_text == "A hint."
    chat.assert_awaited_once()


# ---------------------------------------------------------------------------
# 7. Failed test inputs capped at 3 — 4th not in prompt.
# ---------------------------------------------------------------------------
async def test_prompt_caps_failed_test_inputs_at_three() -> None:
    inputs = ["[1]", "[2]", "[3]", "[4, 5, 6]"]
    agent, chat = _agent(llm_responses=["A hint."])

    await agent.generate(_input(failed_test_inputs=inputs))

    prompt = _captured_prompt(chat)
    assert "[4, 5, 6]" not in prompt
    assert "[1]" in prompt
    assert "[2]" in prompt
    assert "[3]" in prompt


# ---------------------------------------------------------------------------
# 8. temperature=0.4 is used — lock against drift.
# ---------------------------------------------------------------------------
async def test_temperature_is_0_4() -> None:
    agent, chat = _agent(llm_responses=["A hint."])

    await agent.generate(_input())

    call_kwargs = chat.call_args.kwargs
    assert call_kwargs["temperature"] == pytest.approx(0.4)


# ---------------------------------------------------------------------------
# 9. .chat is called (not .complete) — lock contract.
# ---------------------------------------------------------------------------
async def test_chat_method_called_not_complete() -> None:
    agent, chat = _agent(llm_responses=["A hint."])

    await agent.generate(_input())

    chat.assert_awaited_once()
    assert not hasattr(agent.llm, "complete") or not agent.llm.complete.called  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# 10. Zero prior hints → "first hint" framing in prompt.
# ---------------------------------------------------------------------------
async def test_zero_prior_hints_produces_first_hint_framing() -> None:
    agent, chat = _agent(llm_responses=["A hint."])

    await agent.generate(_input(prior_hints=[]))

    prompt = _captured_prompt(chat)
    assert "none yet" in prompt.lower() or "first hint" in prompt.lower()
