from __future__ import annotations

import logging

from openai import APIError, APITimeoutError, AsyncOpenAI

from app.core.config import Settings
from app.llm.exceptions import LLMError, LLMTimeoutError
from app.llm.providers.base import ChatMessage

logger = logging.getLogger("app.llm.providers.openai")


class OpenAIProvider:
    """OpenAI provider. Uses settings.OPENAI_MODEL by default."""

    name = "openai"

    def __init__(self, settings: Settings) -> None:
        if not settings.OPENAI_API_KEY:
            raise ValueError(
                "OpenAI provider initialized without API key. "
                "Set OPENAI_API_KEY or disable fallback."
            )
        self._client = AsyncOpenAI(
            api_key=settings.OPENAI_API_KEY,
            timeout=settings.LLM_TIMEOUT_SECONDS,
            max_retries=0,
        )
        self._model = settings.OPENAI_MODEL

    async def chat(
        self,
        messages: list[ChatMessage],
        *,
        model: str | None = None,
        temperature: float = 0.3,
        json_mode: bool = False,
    ) -> str:
        model_name = model or self._model
        kwargs: dict = {
            "model": model_name,
            "messages": messages,
            "temperature": temperature,
        }
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}

        try:
            response = await self._client.chat.completions.create(**kwargs)
        except APITimeoutError as exc:
            raise LLMTimeoutError("OpenAI timed out") from exc
        except APIError as exc:
            raise LLMError(f"OpenAI API error: {exc}") from exc

        if not response.choices or not response.choices[0].message.content:
            raise LLMError("OpenAI returned empty response")

        return response.choices[0].message.content
