"""Integration tests for gateway fallback — real LLM calls, gated by env vars."""
from __future__ import annotations

import logging
from unittest.mock import AsyncMock, patch

import pytest

from app.core.config import get_settings
from app.llm.exceptions import LLMError
from app.llm.gateway import LLMGateway, get_llm_gateway
from app.llm.providers.deepseek import DeepSeekProvider
from app.llm.providers.openai import OpenAIProvider

MESSAGES = [{"role": "user", "content": "Reply with the single word: hello"}]

_s = get_settings()
_both_keys = pytest.mark.skipif(
    not (_s.DEEPSEEK_API_KEY and _s.OPENAI_API_KEY),
    reason="Both DEEPSEEK_API_KEY and OPENAI_API_KEY required",
)
_openai_key = pytest.mark.skipif(
    not _s.OPENAI_API_KEY,
    reason="OPENAI_API_KEY not set",
)


@pytest.mark.integration
@_both_keys
async def test_real_primary_succeeds_no_fallback_call(caplog):
    get_llm_gateway.cache_clear()
    try:
        settings = get_settings()
        gw = LLMGateway(
            primary=DeepSeekProvider(settings),
            fallback=OpenAIProvider(settings),
            fallback_enabled=True,
        )
        with caplog.at_level(logging.INFO, logger="app.llm.gateway"):
            result = await gw.chat(MESSAGES)
        assert isinstance(result, str) and len(result) > 0
        assert "Falling back" not in caplog.text
    finally:
        get_llm_gateway.cache_clear()


@pytest.mark.integration
@_openai_key
async def test_simulated_primary_failure_falls_back_to_openai():
    """Monkeypatch DeepSeekProvider.chat to always fail; gateway must fall back to real OpenAI."""
    get_llm_gateway.cache_clear()
    try:
        settings = get_settings()
        openai_provider = OpenAIProvider(settings)
        deepseek_provider = DeepSeekProvider(settings)

        gw = LLMGateway(
            primary=deepseek_provider,
            fallback=openai_provider,
            fallback_enabled=True,
        )

        with patch.object(
            deepseek_provider,
            "chat",
            new=AsyncMock(side_effect=LLMError("simulated DeepSeek outage")),
        ):
            result = await gw.chat(MESSAGES)

        assert isinstance(result, str)
        assert len(result) > 0
    finally:
        get_llm_gateway.cache_clear()
