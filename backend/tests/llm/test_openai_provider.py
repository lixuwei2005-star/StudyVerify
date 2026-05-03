"""OpenAI provider: unit tests (mocked) + integration tests (real API, gated)."""
from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from openai import APIError, APITimeoutError

from app.core.config import get_settings
from app.llm.exceptions import LLMError, LLMTimeoutError
from app.llm.providers.openai import OpenAIProvider

_has_openai_key = bool(get_settings().OPENAI_API_KEY)

MESSAGES = [{"role": "user", "content": "Say the word 'hello' only."}]


def _settings(**overrides: Any) -> MagicMock:
    defaults = dict(
        OPENAI_API_KEY="sk-fakekey123abc456def789ghijklmn",
        OPENAI_MODEL="gpt-4o-mini",
        LLM_TIMEOUT_SECONDS=30,
    )
    defaults.update(overrides)
    return MagicMock(**defaults)


def _fake_response(content: str = "hello") -> MagicMock:
    msg = MagicMock()
    msg.content = content
    choice = MagicMock()
    choice.message = msg
    resp = MagicMock()
    resp.choices = [choice]
    return resp


def _provider_with_mock_client(settings=None) -> tuple[OpenAIProvider, AsyncMock]:
    s = settings or _settings()
    p = OpenAIProvider(settings=s)
    mock_create = AsyncMock(return_value=_fake_response())
    p._client.chat.completions.create = mock_create  # type: ignore[attr-defined]
    return p, mock_create


# ── Unit tests ─────────────────────────────────────────────────────────────────

def test_missing_api_key_raises_value_error():
    s = _settings(OPENAI_API_KEY="")
    with pytest.raises(ValueError, match="OPENAI_API_KEY"):
        OpenAIProvider(settings=s)


def test_provider_name_is_openai():
    p, _ = _provider_with_mock_client()
    assert p.name == "openai"


async def test_one_native_call_per_chat():
    p, mock_create = _provider_with_mock_client()
    await p.chat(MESSAGES)
    assert mock_create.await_count == 1


async def test_model_kwarg_overrides_settings():
    p, mock_create = _provider_with_mock_client(_settings(OPENAI_MODEL="gpt-4o-mini"))
    await p.chat(MESSAGES, model="gpt-4o")
    kw = mock_create.call_args.kwargs
    assert kw["model"] == "gpt-4o"


async def test_default_model_from_settings():
    p, mock_create = _provider_with_mock_client(_settings(OPENAI_MODEL="gpt-4o-mini"))
    await p.chat(MESSAGES)
    kw = mock_create.call_args.kwargs
    assert kw["model"] == "gpt-4o-mini"


async def test_json_mode_adds_response_format():
    p, mock_create = _provider_with_mock_client()
    await p.chat(MESSAGES, json_mode=True)
    kw = mock_create.call_args.kwargs
    assert kw["response_format"] == {"type": "json_object"}


async def test_json_mode_false_no_response_format():
    p, mock_create = _provider_with_mock_client()
    await p.chat(MESSAGES, json_mode=False)
    kw = mock_create.call_args.kwargs
    assert "response_format" not in kw


async def test_empty_response_raises_llm_error():
    s = _settings()
    p = OpenAIProvider(settings=s)
    empty_resp = MagicMock()
    empty_resp.choices = []
    p._client.chat.completions.create = AsyncMock(return_value=empty_resp)  # type: ignore[attr-defined]
    with pytest.raises(LLMError, match="empty response"):
        await p.chat(MESSAGES)


async def test_timeout_raises_llm_timeout_error():
    p, mock_create = _provider_with_mock_client()
    mock_create.side_effect = APITimeoutError(request=MagicMock())
    with pytest.raises(LLMTimeoutError):
        await p.chat(MESSAGES)
    assert mock_create.await_count == 1


async def test_api_error_raises_llm_error():
    p, mock_create = _provider_with_mock_client()
    mock_resp = MagicMock()
    mock_resp.status_code = 500
    mock_resp.headers = {}
    mock_create.side_effect = APIError(
        message="server error", request=MagicMock(), body={}
    )
    with pytest.raises(LLMError):
        await p.chat(MESSAGES)
    assert mock_create.await_count == 1


# ── Integration tests ──────────────────────────────────────────────────────────

def _real_settings() -> Any:
    from app.core.config import get_settings

    return get_settings()


@pytest.mark.integration
@pytest.mark.skipif(not _has_openai_key, reason="OPENAI_API_KEY not set")
async def test_real_chat_returns_text():
    s = _real_settings()
    p = OpenAIProvider(settings=s)
    result = await p.chat(MESSAGES)
    assert isinstance(result, str)
    assert len(result) > 0


@pytest.mark.integration
@pytest.mark.skipif(not _has_openai_key, reason="OPENAI_API_KEY not set")
async def test_json_mode_returns_valid_json():
    s = _real_settings()
    p = OpenAIProvider(settings=s)
    result = await p.chat(
        [{"role": "user", "content": 'Respond with a JSON object: {"ok": true}'}],
        json_mode=True,
    )
    parsed = json.loads(result)
    assert isinstance(parsed, dict)


@pytest.mark.integration
@pytest.mark.skipif(not _has_openai_key, reason="OPENAI_API_KEY not set")
async def test_timeout_raises_llm_timeout_error_real():
    s = MagicMock(
        OPENAI_API_KEY=get_settings().OPENAI_API_KEY,
        OPENAI_MODEL="gpt-4o-mini",
        LLM_TIMEOUT_SECONDS=0.001,  # artificially short
    )
    p = OpenAIProvider(settings=s)
    with pytest.raises(LLMTimeoutError):
        await p.chat(MESSAGES)
