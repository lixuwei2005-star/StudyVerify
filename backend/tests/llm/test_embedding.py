"""Unit tests for EmbeddingService and build_failure_text (Step 6.2).

EmbeddingService construction must succeed without OPENAI_API_KEY (DI graph
instantiates it eagerly even when RAG_ENABLED=false). The key check happens
at embed() call time. AsyncOpenAI is mocked so no network calls fire.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.config import Settings
from app.llm.embedding import (
    EMBEDDING_DIM,
    EmbeddingError,
    EmbeddingService,
    build_failure_text,
)


def _settings(**overrides: Any) -> Settings:
    defaults = dict(OPENAI_API_KEY="sk-fakekey", EMBEDDING_MODEL="text-embedding-3-small")
    defaults.update(overrides)
    return Settings(**defaults)


def _fake_response(vector: list[float] | None = None) -> MagicMock:
    item = MagicMock()
    item.embedding = vector if vector is not None else [0.1] * EMBEDDING_DIM
    resp = MagicMock()
    resp.data = [item]
    return resp


# ---------- EmbeddingService.embed ----------


async def test_embed_happy_path_returns_1536_floats() -> None:
    svc = EmbeddingService(_settings())
    fake_client = MagicMock()
    fake_client.embeddings.create = AsyncMock(return_value=_fake_response())
    with patch("app.llm.embedding.AsyncOpenAI", return_value=fake_client):
        result = await svc.embed("any non-empty text")

    assert isinstance(result, list)
    assert len(result) == EMBEDDING_DIM
    assert all(isinstance(x, float) for x in result)
    fake_client.embeddings.create.assert_awaited_once()


async def test_embed_empty_text_raises_value_error() -> None:
    svc = EmbeddingService(_settings())
    with pytest.raises(ValueError, match="empty"):
        await svc.embed("   ")


async def test_embed_without_api_key_raises_embedding_error() -> None:
    """Construction must succeed; only embed() should raise when key absent."""
    svc = EmbeddingService(_settings(OPENAI_API_KEY=""))
    with pytest.raises(EmbeddingError, match="OPENAI_API_KEY"):
        await svc.embed("hi")


async def test_embed_api_error_wrapped_as_embedding_error() -> None:
    svc = EmbeddingService(_settings())
    fake_client = MagicMock()
    fake_client.embeddings.create = AsyncMock(side_effect=RuntimeError("openai 5xx"))
    with patch("app.llm.embedding.AsyncOpenAI", return_value=fake_client):
        with pytest.raises(EmbeddingError, match="OpenAI embedding failed"):
            await svc.embed("hi")


# ---------- build_failure_text ----------


def test_build_failure_text_with_all_fields_has_section_labels() -> None:
    text = build_failure_text(
        problem_text="Sum a list.",
        student_code="def f(n): return 0",
        failed_test_inputs=["[1,2,3]", "[]"],
        diagnosis="Always returns 0.",
        sandbox_error=None,
    )
    assert "PROBLEM:" in text
    assert "CODE:" in text
    assert "DIAGNOSIS:" in text
    assert "FAILED INPUTS:" in text
    assert "Sum a list." in text
    assert "Always returns 0." in text
    assert "[1,2,3]" in text


def test_build_failure_text_minimal_fields() -> None:
    text = build_failure_text(student_code="def f(): pass")
    assert text.startswith("CODE:")
    assert "PROBLEM:" not in text
    assert "DIAGNOSIS:" not in text
    assert "FAILED INPUTS:" not in text


def test_build_failure_text_caps_long_code_with_middle_truncate() -> None:
    long_code = "x" * 5000
    text = build_failure_text(student_code=long_code)
    # 1500 char cap on code, plus "CODE:\n" (6 chars).
    assert len(text) <= 1500 + 10
    assert "..." in text


def test_build_failure_text_caps_failed_inputs_to_5() -> None:
    inputs = [f"[input{i}]" for i in range(20)]
    text = build_failure_text(student_code="x", failed_test_inputs=inputs)
    assert "[input0]" in text
    assert "[input4]" in text
    assert "[input5]" not in text  # 6th and beyond dropped
