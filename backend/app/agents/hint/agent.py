"""Stateless Hint Agent.

Pure function from HintInput to HintOutput. No DB access, no FastAPI knowledge.
Constructor-injected DeepSeekClient makes the agent trivially mockable in unit tests.
A single cached instance from get_hint_agent() serves concurrent requests.
"""

from __future__ import annotations

import logging
from functools import lru_cache

from app.agents.hint.prompts import build_hint_prompt
from app.agents.hint.schemas import HintInput, HintOutput
from app.llm.client import DeepSeekClient, get_llm_client
from app.llm.exceptions import LLMError

logger = logging.getLogger(__name__)

LLM_FALLBACK_HINT = (
    "Hint service is temporarily unavailable. Please review the problem statement "
    "carefully and consider what your code does for edge-case inputs."
)


class HintError(Exception):
    """Raised when hint generation fails at infra level (reserved for future use)."""


class HintAgent:
    """Stateless hint agent with constructor-injected LLM client.

    Mirrors VerifierAgent's pattern: single .generate() method, graceful LLM
    degradation via fallback text on LLMError.
    """

    def __init__(self, llm_client: DeepSeekClient) -> None:
        self.llm = llm_client

    async def generate(self, input: HintInput) -> HintOutput:
        prompt = build_hint_prompt(input)

        try:
            response = await self.llm.chat(
                messages=[
                    {"role": "system", "content": prompt["system"]},
                    {"role": "user", "content": prompt["user"]},
                ],
                temperature=0.3,
                json_mode=False,
            )
            hint_text = response.strip()
        except LLMError as exc:
            logger.warning("LLM unavailable for hint generation: %s", exc)
            hint_text = LLM_FALLBACK_HINT

        return HintOutput(hint_text=hint_text)


@lru_cache
def get_hint_agent() -> HintAgent:
    return HintAgent(llm_client=get_llm_client())
