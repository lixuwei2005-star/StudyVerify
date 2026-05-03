from __future__ import annotations

import logging
import time
from typing import Any

import openai
from openai import AsyncOpenAI

from app.core.config import Settings
from app.llm.exceptions import LLMError, LLMRateLimitError, LLMTimeoutError
from app.llm.providers.base import ChatMessage

logger = logging.getLogger("app.llm.providers.deepseek")


class DeepSeekProvider:
    """Async wrapper over `AsyncOpenAI` pointed at DeepSeek's OpenAI-compatible API.

    Does exactly one native HTTP call per chat(). Gateway owns retry.
    """

    name = "deepseek"

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
        messages: list[ChatMessage],
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

        started = time.perf_counter()
        try:
            response = await self._client.chat.completions.create(**kwargs)
        except openai.APITimeoutError as exc:
            self._log_failure(model_name, started, exc)
            raise LLMTimeoutError(f"DeepSeek timed out: {exc}") from exc
        except openai.RateLimitError as exc:
            self._log_failure(model_name, started, exc)
            raise LLMRateLimitError(f"DeepSeek rate-limited: {exc}") from exc
        except (openai.APIConnectionError, openai.InternalServerError) as exc:
            self._log_failure(model_name, started, exc)
            raise LLMError(f"DeepSeek transport error: {exc}") from exc
        except openai.APIStatusError as exc:
            self._log_failure(model_name, started, exc)
            status = getattr(exc, "status_code", None)
            raise LLMError(f"DeepSeek API error {status}: {exc}") from exc

        latency_ms = int((time.perf_counter() - started) * 1000)
        usage = getattr(response, "usage", None)
        logger.info(
            "llm.chat ok model=%s latency_ms=%d prompt_tokens=%s completion_tokens=%s",
            model_name,
            latency_ms,
            getattr(usage, "prompt_tokens", None),
            getattr(usage, "completion_tokens", None),
        )

        content = response.choices[0].message.content
        if content is None:
            raise LLMError("DeepSeek returned empty content")
        return content

    @staticmethod
    def _log_failure(model: str, started: float, exc: Exception) -> None:
        latency_ms = int((time.perf_counter() - started) * 1000)
        logger.warning(
            "llm.chat error model=%s latency_ms=%d exc=%s msg=%s",
            model,
            latency_ms,
            type(exc).__name__,
            exc,
        )
