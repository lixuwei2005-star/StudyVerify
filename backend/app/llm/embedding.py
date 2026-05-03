"""OpenAI embedding service for RAG retrieval (Step 6.2).

Construction must NOT fail when OPENAI_API_KEY is absent — the FastAPI
dependency graph instantiates this service even when RAG_ENABLED=false, and
verifier persistence must degrade gracefully when embedding generation can't
run. The key check happens at embed() call time, not __init__.
"""

from __future__ import annotations

import logging

from openai import AsyncOpenAI, OpenAI

from app.core.config import Settings, get_settings
from app.llm.exceptions import LLMError

logger = logging.getLogger(__name__)

DEFAULT_EMBEDDING_MODEL = "text-embedding-3-small"
EMBEDDING_DIM = 1536

MAX_CODE_CHARS = 1500
MAX_FAILED_INPUT_CHARS = 200
MAX_DIAGNOSIS_CHARS = 500
MAX_FAILED_INPUTS = 5


class EmbeddingError(LLMError):
    """Raised when embedding generation fails."""


class EmbeddingService:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._client: AsyncOpenAI | None = None
        self._model = settings.EMBEDDING_MODEL or DEFAULT_EMBEDDING_MODEL

    async def embed(self, text: str) -> list[float]:
        if not text or not text.strip():
            raise ValueError("Cannot embed empty text")
        if not self._settings.OPENAI_API_KEY:
            raise EmbeddingError("OPENAI_API_KEY is not set")
        if self._client is None:
            self._client = AsyncOpenAI(api_key=self._settings.OPENAI_API_KEY)
        try:
            response = await self._client.embeddings.create(
                input=text,
                model=self._model,
            )
        except Exception as exc:
            raise EmbeddingError(f"OpenAI embedding failed: {exc}") from exc

        if not response.data or not response.data[0].embedding:
            raise EmbeddingError("Empty embedding response")
        return list(response.data[0].embedding)


def sync_embed_one(text: str, settings: Settings | None = None) -> list[float]:
    """Blocking single-shot embed for CLI scripts (e.g. backfill).

    Avoids async-runtime juggling inside argparse handlers. Same key/model
    semantics as EmbeddingService.embed.
    """
    if not text or not text.strip():
        raise ValueError("Cannot embed empty text")
    settings = settings or get_settings()
    if not settings.OPENAI_API_KEY:
        raise EmbeddingError("OPENAI_API_KEY is not set")
    client = OpenAI(api_key=settings.OPENAI_API_KEY)
    model = settings.EMBEDDING_MODEL or DEFAULT_EMBEDDING_MODEL
    try:
        response = client.embeddings.create(input=text, model=model)
    except Exception as exc:
        raise EmbeddingError(f"OpenAI embedding failed: {exc}") from exc
    if not response.data or not response.data[0].embedding:
        raise EmbeddingError("Empty embedding response")
    return list(response.data[0].embedding)


def _middle_truncate(value: str, max_chars: int) -> str:
    if len(value) <= max_chars:
        return value
    keep = max_chars - 3
    head = keep // 2
    tail = keep - head
    return f"{value[:head]}...{value[-tail:]}"


def _truncate(value: str, max_chars: int) -> str:
    if len(value) <= max_chars:
        return value
    return value[: max_chars - 3] + "..."


def build_failure_text(
    *,
    problem_text: str = "",
    student_code: str = "",
    failed_test_inputs: list[str] | None = None,
    test_results: list[dict] | None = None,
    diagnosis: str | None = None,
    sandbox_error: str | None = None,
) -> str:
    """Build a weighted, capped text representation of a failure for embedding."""
    inputs = list(failed_test_inputs) if failed_test_inputs else []
    if not inputs and test_results:
        inputs = [
            str(tr["input"]) for tr in test_results if not tr.get("passed", False) and "input" in tr
        ]

    sections: list[str] = []
    if problem_text and problem_text.strip():
        sections.append(f"PROBLEM:\n{problem_text.strip()}")

    if student_code and student_code.strip():
        sections.append("CODE:\n" + _middle_truncate(student_code.strip(), MAX_CODE_CHARS))

    if diagnosis and diagnosis.strip():
        sections.append("DIAGNOSIS:\n" + _truncate(diagnosis.strip(), MAX_DIAGNOSIS_CHARS))

    if inputs:
        capped = [_truncate(str(inp), MAX_FAILED_INPUT_CHARS) for inp in inputs[:MAX_FAILED_INPUTS]]
        sections.append("FAILED INPUTS:\n" + "\n".join(f"- {inp}" for inp in capped))

    if sandbox_error and sandbox_error.strip():
        sections.append("ERROR:\n" + _truncate(sandbox_error.strip(), MAX_DIAGNOSIS_CHARS))

    return "\n\n".join(sections)


_embedding_service: EmbeddingService | None = None


def get_embedding_service() -> EmbeddingService:
    global _embedding_service
    if _embedding_service is None:
        _embedding_service = EmbeddingService(get_settings())
    return _embedding_service
