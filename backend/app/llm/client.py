from __future__ import annotations

import asyncio
import logging
import time
from functools import lru_cache
from typing import Any

import openai
from openai import AsyncOpenAI

from app.core.config import Settings, get_settings
from app.llm.exceptions import LLMError, LLMRateLimitError, LLMTimeoutError

logger = logging.getLogger("app.llm.client")


class DeepSeekClient:
    """Async wrapper over `AsyncOpenAI` pointed at DeepSeek's OpenAI-compatible API.

    Drives its own retry loop so it can map provider exceptions onto typed
    `LLMError` subclasses for the rest of the app.
    """

    def __init__(self, settings: Settings, client: AsyncOpenAI | None = None) -> None:
        self._settings = settings
        self._client = client or AsyncOpenAI(
            api_key=settings.DEEPSEEK_API_KEY,
            base_url=settings.DEEPSEEK_BASE_URL,
            timeout=settings.LLM_TIMEOUT_SECONDS,
            max_retries=0,
        )

    async def chat(
        self,
        messages: list[dict[str, Any]],
        *,
        model: str | None = None,
        temperature: float = 0.3,
        json_mode: bool = False,
    ) -> str:
        model_name = model or self._settings.DEEPSEEK_MODEL
        kwargs: dict[str, Any] = {
            "model": model_name,
            "messages": messages,
            "temperature": temperature,
        }
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}
        effort = self._settings.DEEPSEEK_REASONING_EFFORT
        if effort and effort != "none":
            kwargs["extra_body"] = {"reasoning_effort": effort}

        max_attempts = max(1, self._settings.LLM_MAX_RETRIES)
        last_exc: Exception | None = None

        for attempt in range(1, max_attempts + 1):
            started = time.perf_counter()
            try:
                response = await self._client.chat.completions.create(**kwargs)
            except openai.APITimeoutError as exc:
                last_exc = exc
                self._log_failure(model_name, attempt, started, exc)
                if attempt >= max_attempts:
                    raise LLMTimeoutError(f"DeepSeek timed out after {attempt} attempt(s)") from exc
                continue
            except openai.RateLimitError as exc:
                last_exc = exc
                self._log_failure(model_name, attempt, started, exc)
                if attempt >= max_attempts:
                    raise LLMRateLimitError(
                        f"DeepSeek rate-limited after {attempt} attempt(s)"
                    ) from exc
                await asyncio.sleep((2 ** (attempt - 1)) * 0.5)
                continue
            except (openai.APIConnectionError, openai.InternalServerError) as exc:
                last_exc = exc
                self._log_failure(model_name, attempt, started, exc)
                if attempt >= max_attempts:
                    raise LLMError(f"DeepSeek transport error: {exc}") from exc
                await asyncio.sleep((2 ** (attempt - 1)) * 0.5)
                continue
            except openai.APIStatusError as exc:
                # 4xx (non-429): no retry. 5xx: retry.
                self._log_failure(model_name, attempt, started, exc)
                status = getattr(exc, "status_code", None)
                if status and 500 <= status < 600 and attempt < max_attempts:
                    last_exc = exc
                    await asyncio.sleep((2 ** (attempt - 1)) * 0.5)
                    continue
                raise LLMError(f"DeepSeek API error {status}: {exc}") from exc

            latency_ms = int((time.perf_counter() - started) * 1000)
            usage = getattr(response, "usage", None)
            logger.info(
                "llm.chat ok model=%s attempt=%d latency_ms=%d "
                "prompt_tokens=%s completion_tokens=%s",
                model_name,
                attempt,
                latency_ms,
                getattr(usage, "prompt_tokens", None),
                getattr(usage, "completion_tokens", None),
            )

            content = response.choices[0].message.content
            if content is None:
                raise LLMError("DeepSeek returned empty content")
            return content

        # Should be unreachable — the loop either returns or raises above.
        raise LLMError(f"DeepSeek call failed: {last_exc}")

    @staticmethod
    def _log_failure(model: str, attempt: int, started: float, exc: Exception) -> None:
        latency_ms = int((time.perf_counter() - started) * 1000)
        logger.warning(
            "llm.chat error model=%s attempt=%d latency_ms=%d exc=%s msg=%s",
            model,
            attempt,
            latency_ms,
            type(exc).__name__,
            exc,
        )


@lru_cache
def get_llm_client() -> DeepSeekClient:
    return DeepSeekClient(get_settings())
