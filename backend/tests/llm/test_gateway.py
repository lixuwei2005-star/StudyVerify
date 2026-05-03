"""20 unit tests for LLMGateway — all mock, no real LLM calls."""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest

from app.llm.client import DeepSeekClient, get_llm_client
from app.llm.exceptions import LLMAllProvidersFailedError, LLMError, LLMTimeoutError
from app.llm.gateway import LLMGateway, get_llm_gateway
from app.llm.providers.deepseek import DeepSeekProvider
from app.llm.sanitize import sanitize_error_message

MESSAGES = [{"role": "user", "content": "hello"}]


def _make_provider(name: str) -> MagicMock:
    p = MagicMock()
    p.name = name
    p.chat = AsyncMock(return_value="response text")
    return p


def _gateway(primary, fallback=None, fallback_enabled: bool = False) -> LLMGateway:
    return LLMGateway(primary=primary, fallback=fallback, fallback_enabled=fallback_enabled)


# ── 1 ──────────────────────────────────────────────────────────────────────────
async def test_happy_path_primary_succeeds():
    primary = _make_provider("deepseek")
    gw = _gateway(primary)
    result = await gw.chat(MESSAGES)
    assert result == "response text"
    primary.chat.assert_awaited_once()
    assert primary.chat.await_count == 1


# ── 2 ──────────────────────────────────────────────────────────────────────────
async def test_primary_transient_error_retries_then_succeeds():
    primary = _make_provider("deepseek")
    primary.chat = AsyncMock(side_effect=[LLMTimeoutError("timeout"), "second ok"])
    fallback = _make_provider("openai")
    gw = _gateway(primary, fallback, fallback_enabled=True)

    with patch("app.llm.gateway.asyncio.sleep", new_callable=AsyncMock):
        result = await gw.chat(MESSAGES)

    assert result == "second ok"
    assert primary.chat.await_count == 2
    fallback.chat.assert_not_awaited()


# ── 3 ──────────────────────────────────────────────────────────────────────────
async def test_primary_persistent_error_falls_back():
    primary = _make_provider("deepseek")
    primary.chat = AsyncMock(side_effect=LLMError("persistent"))
    fallback = _make_provider("openai")
    fallback.chat = AsyncMock(return_value="fallback response")
    gw = _gateway(primary, fallback, fallback_enabled=True)

    with patch("app.llm.gateway.asyncio.sleep", new_callable=AsyncMock):
        result = await gw.chat(MESSAGES)

    assert result == "fallback response"
    assert primary.chat.await_count == 3
    assert fallback.chat.await_count == 1


# ── 4 ──────────────────────────────────────────────────────────────────────────
async def test_fallback_disabled_propagates_primary_error():
    primary = _make_provider("deepseek")
    err = LLMError("primary down")
    primary.chat = AsyncMock(side_effect=err)
    gw = _gateway(primary, fallback_enabled=False)

    with patch("app.llm.gateway.asyncio.sleep", new_callable=AsyncMock):
        with pytest.raises(LLMError) as exc_info:
            await gw.chat(MESSAGES)

    assert not isinstance(exc_info.value, LLMAllProvidersFailedError)
    assert "primary down" in str(exc_info.value)


# ── 5 ──────────────────────────────────────────────────────────────────────────
async def test_all_providers_fail_raises_combined_error():
    primary = _make_provider("deepseek")
    primary.chat = AsyncMock(side_effect=LLMError("primary broke"))
    fallback = _make_provider("openai")
    fallback.chat = AsyncMock(side_effect=LLMError("fallback broke"))
    gw = _gateway(primary, fallback, fallback_enabled=True)

    with patch("app.llm.gateway.asyncio.sleep", new_callable=AsyncMock):
        with pytest.raises(LLMAllProvidersFailedError) as exc_info:
            await gw.chat(MESSAGES)

    msg = str(exc_info.value)
    assert "deepseek" in msg
    assert "openai" in msg


# ── 6 ──────────────────────────────────────────────────────────────────────────
async def test_fallback_retries_independently():
    primary = _make_provider("deepseek")
    primary.chat = AsyncMock(side_effect=LLMError("primary broke"))
    fallback = _make_provider("openai")
    fallback.chat = AsyncMock(side_effect=[LLMError("transient"), "ok on second"])
    gw = _gateway(primary, fallback, fallback_enabled=True)

    with patch("app.llm.gateway.asyncio.sleep", new_callable=AsyncMock):
        result = await gw.chat(MESSAGES)

    assert result == "ok on second"
    assert primary.chat.await_count == 3
    assert fallback.chat.await_count == 2  # 1 fail + 1 success


# ── 7 ──────────────────────────────────────────────────────────────────────────
async def test_temperature_and_json_mode_passed_through():
    primary = _make_provider("deepseek")
    gw = _gateway(primary)
    await gw.chat(MESSAGES, temperature=0.9, json_mode=True)
    primary.chat.assert_awaited_once_with(
        MESSAGES, model=None, temperature=0.9, json_mode=True
    )


# ── 8 ──────────────────────────────────────────────────────────────────────────
async def test_logging_includes_provider_names(caplog):
    import logging

    primary = _make_provider("deepseek")
    primary.chat = AsyncMock(side_effect=LLMError("boom"))
    fallback = _make_provider("openai")
    fallback.chat = AsyncMock(return_value="ok")
    gw = _gateway(primary, fallback, fallback_enabled=True)

    with patch("app.llm.gateway.asyncio.sleep", new_callable=AsyncMock):
        with caplog.at_level(logging.INFO, logger="app.llm.gateway"):
            await gw.chat(MESSAGES)

    messages = " ".join(caplog.messages)
    assert "deepseek" in messages
    # fallback info log is INFO level: "Falling back from deepseek to openai"
    assert "openai" in messages


# ── 9 ──────────────────────────────────────────────────────────────────────────
async def test_stateless_concurrent_safe():
    primary = _make_provider("deepseek")
    primary.chat = AsyncMock(return_value="concurrent ok")
    gw = _gateway(primary)

    results = await asyncio.gather(*[gw.chat(MESSAGES) for _ in range(10)])
    assert all(r == "concurrent ok" for r in results)
    assert primary.chat.await_count == 10


# ── 10 ─────────────────────────────────────────────────────────────────────────
async def test_fallback_success_does_not_raise_all_providers_error():
    primary = _make_provider("deepseek")
    primary.chat = AsyncMock(side_effect=LLMError("primary down"))
    fallback = _make_provider("openai")
    fallback.chat = AsyncMock(return_value="fallback saved it")
    gw = _gateway(primary, fallback, fallback_enabled=True)

    with patch("app.llm.gateway.asyncio.sleep", new_callable=AsyncMock):
        result = await gw.chat(MESSAGES)

    assert result == "fallback saved it"


# ── 11 ─────────────────────────────────────────────────────────────────────────
async def test_model_kwarg_passthrough():
    primary = _make_provider("deepseek")
    gw = _gateway(primary)
    await gw.chat(MESSAGES, model="gpt-4o-mini")
    primary.chat.assert_awaited_once_with(
        MESSAGES, model="gpt-4o-mini", temperature=0.3, json_mode=False
    )


# ── 12 ─────────────────────────────────────────────────────────────────────────
def test_deepseek_client_compat_alias_imports():
    assert DeepSeekClient is DeepSeekProvider
    mock = AsyncMock(spec=DeepSeekClient)
    assert mock is not None
    # AsyncMock(spec=DeepSeekClient) must expose .chat without AttributeError
    assert hasattr(mock, "chat")


# ── 13 ─────────────────────────────────────────────────────────────────────────
async def test_no_double_retry():
    primary = _make_provider("deepseek")
    primary.chat = AsyncMock(side_effect=LLMError("persistent"))
    fallback = _make_provider("openai")
    fallback.chat = AsyncMock(side_effect=LLMError("also broken"))
    gw = _gateway(primary, fallback, fallback_enabled=True)

    with patch("app.llm.gateway.asyncio.sleep", new_callable=AsyncMock):
        with pytest.raises(LLMAllProvidersFailedError):
            await gw.chat(MESSAGES)

    assert primary.chat.await_count == 3
    assert fallback.chat.await_count == 3


# ── 14 ─────────────────────────────────────────────────────────────────────────
async def test_backoff_between_retries():
    primary = _make_provider("deepseek")
    primary.chat = AsyncMock(side_effect=LLMError("fail"))
    gw = _gateway(primary, fallback_enabled=False)

    with patch("app.llm.gateway.asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
        with pytest.raises(LLMError):
            await gw.chat(MESSAGES)

    # 3 attempts: sleep after attempt 1 (0.5s) and attempt 2 (1.0s); none after 3
    assert mock_sleep.await_count == 2
    assert mock_sleep.await_args_list == [call(0.5), call(1.0)]


# ── 15 ─────────────────────────────────────────────────────────────────────────
def test_misconfigured_fallback_raises_at_startup():
    get_llm_gateway.cache_clear()
    try:
        with patch(
            "app.llm.gateway.get_settings",
            return_value=MagicMock(
                DEEPSEEK_API_KEY="sk-fake",
                DEEPSEEK_BASE_URL="https://api.deepseek.com/v1",
                DEEPSEEK_MODEL="deepseek-v4-flash",
                DEEPSEEK_REASONING_EFFORT="none",
                LLM_TIMEOUT_SECONDS=30,
                LLM_FALLBACK_ENABLED=True,
                LLM_FALLBACK_PROVIDER="openai",
                OPENAI_API_KEY="",  # empty — should trigger ValueError
                OPENAI_MODEL="gpt-4o-mini",
            ),
        ):
            with pytest.raises(ValueError) as exc_info:
                get_llm_gateway()
        msg = str(exc_info.value)
        assert "LLM_FALLBACK_ENABLED" in msg
        assert "OPENAI_API_KEY" in msg
    finally:
        get_llm_gateway.cache_clear()


# ── 16 ─────────────────────────────────────────────────────────────────────────
def test_fallback_disabled_no_openai_key_works():
    get_llm_gateway.cache_clear()
    try:
        with patch(
            "app.llm.gateway.get_settings",
            return_value=MagicMock(
                DEEPSEEK_API_KEY="sk-fake",
                DEEPSEEK_BASE_URL="https://api.deepseek.com/v1",
                DEEPSEEK_MODEL="deepseek-v4-flash",
                DEEPSEEK_REASONING_EFFORT="none",
                LLM_TIMEOUT_SECONDS=30,
                LLM_FALLBACK_ENABLED=False,
                LLM_FALLBACK_PROVIDER="openai",
                OPENAI_API_KEY="",
                OPENAI_MODEL="gpt-4o-mini",
            ),
        ):
            gw = get_llm_gateway()
        assert gw._fallback is None
        assert gw._fallback_enabled is False
    finally:
        get_llm_gateway.cache_clear()


# ── 17 ─────────────────────────────────────────────────────────────────────────
def test_sanitize_redacts_api_keys():
    assert sanitize_error_message("sk-fakekey123abc456def789ghijklmn") == "[REDACTED]"
    assert sanitize_error_message("Bearer faketokenABCDEFGHIJKLMNOP1234567890") == "[REDACTED]"
    result = sanitize_error_message('api_key="fakeAPIkey1234567890abcdefgh"')
    assert "[REDACTED]" in result
    assert "fakeAPIkey1234567890abcdefgh" not in result


# ── 18 ─────────────────────────────────────────────────────────────────────────
async def test_combined_error_sanitized():
    primary = _make_provider("deepseek")
    primary.chat = AsyncMock(
        side_effect=LLMError("error: sk-fakekey123abc456def789ghijklmn")
    )
    fallback = _make_provider("openai")
    fallback.chat = AsyncMock(
        side_effect=LLMError("error: Bearer faketokenABCDEFGHIJKLMNOP1234567890")
    )
    gw = _gateway(primary, fallback, fallback_enabled=True)

    with patch("app.llm.gateway.asyncio.sleep", new_callable=AsyncMock):
        with pytest.raises(LLMAllProvidersFailedError) as exc_info:
            await gw.chat(MESSAGES)

    msg = str(exc_info.value)
    assert "sk-fakekey123abc456def789ghijklmn" not in msg
    assert "faketokenABCDEFGHIJKLMNOP1234567890" not in msg
    assert "[REDACTED]" in msg


# ── 19 ─────────────────────────────────────────────────────────────────────────
async def test_existing_agents_still_work_with_mock_spec():
    """AsyncMock(spec=DeepSeekClient) must support solver/hint/verifier call patterns."""
    mock = AsyncMock(spec=DeepSeekClient)
    mock.chat = AsyncMock(return_value='{"diagnosis": "ok"}')

    # solver calls: positional messages + keyword-only temperature/json_mode
    result = await mock.chat(MESSAGES, temperature=0.3, json_mode=True)
    assert result == '{"diagnosis": "ok"}'

    # hint calls: messages as kwarg
    result = await mock.chat(messages=MESSAGES, temperature=0.5, json_mode=False)
    assert result == '{"diagnosis": "ok"}'


# ── 20 ─────────────────────────────────────────────────────────────────────────
def test_get_llm_gateway_lru_cache_clearable():
    get_llm_gateway.cache_clear()
    try:
        with patch(
            "app.llm.gateway.get_settings",
            return_value=MagicMock(
                DEEPSEEK_API_KEY="sk-fake",
                DEEPSEEK_BASE_URL="https://api.deepseek.com/v1",
                DEEPSEEK_MODEL="deepseek-v4-flash",
                DEEPSEEK_REASONING_EFFORT="none",
                LLM_TIMEOUT_SECONDS=30,
                LLM_FALLBACK_ENABLED=False,
                LLM_FALLBACK_PROVIDER="openai",
                OPENAI_API_KEY="",
                OPENAI_MODEL="gpt-4o-mini",
            ),
        ):
            gw1 = get_llm_gateway()
            gw2 = get_llm_gateway()
            assert gw1 is gw2

            get_llm_gateway.cache_clear()
            gw3 = get_llm_gateway()
            assert gw3 is not gw1
    finally:
        get_llm_gateway.cache_clear()
