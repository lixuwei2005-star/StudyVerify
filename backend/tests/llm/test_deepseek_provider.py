"""Unit tests for DeepSeekProvider — one native call per chat(), no retry."""
from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import openai
import pytest

from app.llm.exceptions import LLMError, LLMRateLimitError, LLMTimeoutError
from app.llm.providers.deepseek import DeepSeekProvider

MESSAGES = [{"role": "user", "content": "hello"}]


def _settings(**overrides: Any) -> MagicMock:
    defaults = dict(
        DEEPSEEK_API_KEY="sk-fake",
        DEEPSEEK_BASE_URL="https://api.deepseek.com/v1",
        DEEPSEEK_MODEL="deepseek-v4-flash",
        DEEPSEEK_REASONING_EFFORT="none",
        LLM_TIMEOUT_SECONDS=30,
    )
    defaults.update(overrides)
    return MagicMock(**defaults)


def _fake_response(content: str = "answer text") -> MagicMock:
    msg = MagicMock()
    msg.content = content
    choice = MagicMock()
    choice.message = msg
    resp = MagicMock()
    resp.choices = [choice]
    resp.usage = MagicMock(prompt_tokens=10, completion_tokens=5)
    return resp


def _provider(settings=None, *, async_client: AsyncMock | None = None) -> DeepSeekProvider:
    s = settings or _settings()
    client = async_client or AsyncMock()
    client.chat = MagicMock()
    client.chat.completions = MagicMock()
    client.chat.completions.create = AsyncMock(return_value=_fake_response())
    return DeepSeekProvider(settings=s, client=client)


async def test_one_native_call_per_chat():
    p = _provider()
    await p.chat(MESSAGES)
    assert p._client.chat.completions.create.await_count == 1


async def test_model_kwarg_overrides_settings():
    s = _settings(DEEPSEEK_MODEL="deepseek-v4-flash")
    p = _provider(s)
    await p.chat(MESSAGES, model="deepseek-r1")
    call_kwargs = p._client.chat.completions.create.call_args.kwargs
    assert call_kwargs["model"] == "deepseek-r1"


async def test_default_model_from_settings():
    s = _settings(DEEPSEEK_MODEL="deepseek-v4-flash")
    p = _provider(s)
    await p.chat(MESSAGES)
    call_kwargs = p._client.chat.completions.create.call_args.kwargs
    assert call_kwargs["model"] == "deepseek-v4-flash"


async def test_json_mode_adds_response_format():
    p = _provider()
    await p.chat(MESSAGES, json_mode=True)
    call_kwargs = p._client.chat.completions.create.call_args.kwargs
    assert call_kwargs["response_format"] == {"type": "json_object"}


async def test_json_mode_false_no_response_format():
    p = _provider()
    await p.chat(MESSAGES, json_mode=False)
    call_kwargs = p._client.chat.completions.create.call_args.kwargs
    assert "response_format" not in call_kwargs


async def test_reasoning_effort_adds_extra_body():
    s = _settings(DEEPSEEK_REASONING_EFFORT="medium")
    p = _provider(s)
    await p.chat(MESSAGES)
    call_kwargs = p._client.chat.completions.create.call_args.kwargs
    assert call_kwargs["extra_body"] == {"reasoning_effort": "medium"}


async def test_reasoning_effort_none_no_extra_body():
    s = _settings(DEEPSEEK_REASONING_EFFORT="none")
    p = _provider(s)
    await p.chat(MESSAGES)
    call_kwargs = p._client.chat.completions.create.call_args.kwargs
    assert "extra_body" not in call_kwargs


async def test_timeout_raises_llm_timeout_error():
    p = _provider()
    p._client.chat.completions.create = AsyncMock(
        side_effect=openai.APITimeoutError(request=MagicMock())
    )
    with pytest.raises(LLMTimeoutError):
        await p.chat(MESSAGES)
    assert p._client.chat.completions.create.await_count == 1


async def test_rate_limit_raises_llm_rate_limit_error():
    p = _provider()
    p._client.chat.completions.create = AsyncMock(
        side_effect=openai.RateLimitError(
            message="rate limited", response=MagicMock(), body={}
        )
    )
    with pytest.raises(LLMRateLimitError):
        await p.chat(MESSAGES)
    assert p._client.chat.completions.create.await_count == 1


async def test_connection_error_raises_llm_error():
    p = _provider()
    p._client.chat.completions.create = AsyncMock(
        side_effect=openai.APIConnectionError(request=MagicMock())
    )
    with pytest.raises(LLMError):
        await p.chat(MESSAGES)
    assert p._client.chat.completions.create.await_count == 1


async def test_api_status_error_raises_llm_error():
    p = _provider()
    mock_resp = MagicMock()
    mock_resp.status_code = 400
    mock_resp.headers = {}
    p._client.chat.completions.create = AsyncMock(
        side_effect=openai.APIStatusError(
            message="bad request", response=mock_resp, body={}
        )
    )
    with pytest.raises(LLMError):
        await p.chat(MESSAGES)
    assert p._client.chat.completions.create.await_count == 1


async def test_empty_content_raises_llm_error():
    p = _provider()
    p._client.chat.completions.create = AsyncMock(
        return_value=_fake_response(content=None)  # type: ignore[arg-type]
    )
    with pytest.raises(LLMError, match="empty content"):
        await p.chat(MESSAGES)


async def test_provider_name_is_deepseek():
    p = _provider()
    assert p.name == "deepseek"
