from __future__ import annotations

import asyncio
import logging
from functools import lru_cache

from app.core.config import Settings, get_settings
from app.llm.exceptions import LLMAllProvidersFailedError, LLMError, LLMTimeoutError
from app.llm.providers.base import ChatMessage, LLMProvider
from app.llm.providers.deepseek import DeepSeekProvider
from app.llm.providers.openai import OpenAIProvider
from app.llm.sanitize import sanitize_error_message

logger = logging.getLogger("app.llm.gateway")

MAX_ATTEMPTS_PER_PROVIDER = 3
BACKOFF_BASE_SECONDS = 0.5


class LLMGateway:
    """Routes chat() calls through primary -> fallback chain.

    Each provider gets up to MAX_ATTEMPTS_PER_PROVIDER total attempts. After
    primary is exhausted, the gateway falls through to fallback if configured.
    If all providers fail, raises LLMAllProvidersFailedError.

    Stateless. One cached instance serves concurrent requests.
    """

    def __init__(
        self,
        primary: LLMProvider,
        fallback: LLMProvider | None,
        fallback_enabled: bool,
    ) -> None:
        self._primary = primary
        self._fallback = fallback
        self._fallback_enabled = fallback_enabled and fallback is not None

    async def chat(
        self,
        messages: list[ChatMessage],
        *,
        model: str | None = None,
        temperature: float = 0.3,
        json_mode: bool = False,
    ) -> str:
        primary_error: Exception | None = None

        try:
            return await self._call_with_retry(
                self._primary,
                messages,
                model,
                temperature,
                json_mode,
            )
        except (LLMError, LLMTimeoutError) as exc:
            primary_error = exc
            logger.warning(
                "Primary provider %s exhausted retries: %s",
                self._primary.name,
                sanitize_error_message(str(exc)),
            )

        if not self._fallback_enabled:
            raise primary_error  # type: ignore[misc]

        assert self._fallback is not None
        try:
            logger.info(
                "Falling back from %s to %s",
                self._primary.name,
                self._fallback.name,
            )
            return await self._call_with_retry(
                self._fallback,
                messages,
                model,
                temperature,
                json_mode,
            )
        except (LLMError, LLMTimeoutError) as fallback_error:
            logger.error(
                "Fallback provider %s also failed: %s",
                self._fallback.name,
                sanitize_error_message(str(fallback_error)),
            )
            raise LLMAllProvidersFailedError(
                f"Primary ({self._primary.name}) failed: "
                f"{sanitize_error_message(str(primary_error))}; "
                f"Fallback ({self._fallback.name}) failed: "
                f"{sanitize_error_message(str(fallback_error))}"
            ) from fallback_error

    async def _call_with_retry(
        self,
        provider: LLMProvider,
        messages: list[ChatMessage],
        model: str | None,
        temperature: float,
        json_mode: bool,
    ) -> str:
        last_error: Exception | None = None
        for attempt in range(MAX_ATTEMPTS_PER_PROVIDER):
            try:
                return await provider.chat(
                    messages,
                    model=model,
                    temperature=temperature,
                    json_mode=json_mode,
                )
            except (LLMError, LLMTimeoutError) as exc:
                last_error = exc
                if attempt < MAX_ATTEMPTS_PER_PROVIDER - 1:
                    backoff = BACKOFF_BASE_SECONDS * (2**attempt)
                    logger.warning(
                        "%s attempt %d/%d failed, retrying in %.1fs: %s",
                        provider.name,
                        attempt + 1,
                        MAX_ATTEMPTS_PER_PROVIDER,
                        backoff,
                        sanitize_error_message(str(exc)),
                    )
                    await asyncio.sleep(backoff)
                    continue
                raise
        raise last_error  # type: ignore[misc]


@lru_cache
def get_llm_gateway() -> LLMGateway:
    settings = get_settings()
    primary = DeepSeekProvider(settings)

    fallback: LLMProvider | None = None

    if settings.LLM_FALLBACK_ENABLED:
        if settings.LLM_FALLBACK_PROVIDER != "openai":
            raise ValueError(
                f"LLM_FALLBACK_ENABLED=true but "
                f"LLM_FALLBACK_PROVIDER={settings.LLM_FALLBACK_PROVIDER!r} "
                "is not supported. Use 'openai' or set "
                "LLM_FALLBACK_ENABLED=false."
            )
        if not settings.OPENAI_API_KEY:
            raise ValueError(
                "LLM_FALLBACK_ENABLED=true but OPENAI_API_KEY is empty. "
                "Either set OPENAI_API_KEY or set LLM_FALLBACK_ENABLED=false "
                "in your .env."
            )
        fallback = OpenAIProvider(settings)

    return LLMGateway(
        primary=primary,
        fallback=fallback,
        fallback_enabled=fallback is not None,
    )
