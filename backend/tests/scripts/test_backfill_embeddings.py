"""Unit tests for app.scripts.backfill_embeddings (Step 6.2).

The CLI's only external boundaries are: (1) the OpenAI embedding call (via
sync_embed_one), (2) the AsyncSession + engine, (3) VerifierRepository. All
three are mocked here. PG isn't required for these tests; the SQL goes
through the mocked session.execute and never reaches a database.
"""

from __future__ import annotations

import argparse
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

from app.llm.embedding import EmbeddingError
from app.scripts import backfill_embeddings as bf


def _row(rid: uuid.UUID | None = None) -> dict:
    return {
        "id": rid or uuid.uuid4(),
        "student_code": "def f(x): return 0",
        "test_results": [
            {"input": "[1]", "actual": "0", "passed": False, "duration_ms": 1, "error": None}
        ],
        "diagnosis": "stub diagnosis",
        "sandbox_error": None,
        "problem_text": "Sum a list.",
    }


def _mock_session(rows: list[dict]) -> MagicMock:
    """AsyncSession mock that yields itself from `async with` and returns
    `rows` from session.execute(...).mappings()."""
    session = MagicMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=None)

    result = MagicMock()
    result.mappings = MagicMock(return_value=list(rows))
    session.execute = AsyncMock(return_value=result)
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    return session


def _mock_engine() -> MagicMock:
    engine = MagicMock()
    engine.dispose = AsyncMock()
    return engine


def _patch_settings(openai_key: str = "sk-fake", db_url: str = "postgresql+asyncpg://x@x/x"):
    settings = MagicMock()
    settings.OPENAI_API_KEY = openai_key
    settings.DATABASE_URL = db_url
    settings.EMBEDDING_MODEL = "text-embedding-3-small"
    return settings


async def test_backfill_command_resumable() -> None:
    """Two pending rows. Both embed successfully, status updated to 'success'.
    Re-running with no rows pending is a clean no-op (resumable shape)."""
    rows = [_row(), _row()]
    session = _mock_session(rows)
    repo = AsyncMock()
    repo.update_embedding = AsyncMock()

    with (
        patch.object(bf, "get_settings", return_value=_patch_settings()),
        patch.object(bf, "create_async_engine", return_value=_mock_engine()),
        patch.object(bf, "AsyncSession", return_value=session),
        patch.object(bf, "VerifierRepository", return_value=repo),
        patch.object(bf, "sync_embed_one", return_value=[0.1] * 1536),
    ):
        rc = await bf._run(argparse.Namespace(limit=None, retry_failed=False, dry_run=False))

    assert rc == 0
    assert repo.update_embedding.await_count == 2
    # All update_embedding calls should write 'success' status (no row failed).
    for call in repo.update_embedding.call_args_list:
        assert call.kwargs["embedding_status"] == "success"
    # Per-row commit pattern: 2 commits (one per row).
    assert session.commit.await_count == 2


async def test_backfill_command_skips_rows_with_status_failed() -> None:
    """Default run filters statuses=['pending'] in the SQL parameters; passing
    --retry-failed flips that to ['pending','failed']. Verify by inspecting
    the kwargs the CLI passes to session.execute."""
    session = _mock_session([])
    with (
        patch.object(bf, "get_settings", return_value=_patch_settings()),
        patch.object(bf, "create_async_engine", return_value=_mock_engine()),
        patch.object(bf, "AsyncSession", return_value=session),
        patch.object(bf, "VerifierRepository", return_value=AsyncMock()),
    ):
        # Default: only 'pending'
        await bf._run(argparse.Namespace(limit=None, retry_failed=False, dry_run=False))
        assert session.execute.await_args.args[1]["statuses"] == ["pending"]

        # --retry-failed: include 'failed'
        await bf._run(argparse.Namespace(limit=None, retry_failed=True, dry_run=False))
        assert session.execute.await_args.args[1]["statuses"] == ["pending", "failed"]


async def test_backfill_command_dry_run_makes_no_writes() -> None:
    """--dry-run reports the count and exits without calling the embedding API
    or update_embedding."""
    rows = [_row(), _row()]
    session = _mock_session(rows)
    repo = AsyncMock()
    repo.update_embedding = AsyncMock()

    with (
        patch.object(bf, "get_settings", return_value=_patch_settings()),
        patch.object(bf, "create_async_engine", return_value=_mock_engine()),
        patch.object(bf, "AsyncSession", return_value=session),
        patch.object(bf, "VerifierRepository", return_value=repo),
        patch.object(bf, "sync_embed_one") as embed,
    ):
        rc = await bf._run(argparse.Namespace(limit=None, retry_failed=False, dry_run=True))

    assert rc == 0
    embed.assert_not_called()
    repo.update_embedding.assert_not_awaited()
    session.commit.assert_not_called()


async def test_backfill_command_fails_fast_on_missing_openai_key() -> None:
    """Without OPENAI_API_KEY (and not --dry-run), exit 1 before any DB work."""
    session = _mock_session([])
    with (
        patch.object(bf, "get_settings", return_value=_patch_settings(openai_key="")),
        patch.object(bf, "create_async_engine", return_value=_mock_engine()),
        patch.object(bf, "AsyncSession", return_value=session),
    ):
        rc = await bf._run(argparse.Namespace(limit=None, retry_failed=False, dry_run=False))

    assert rc == 1
    session.execute.assert_not_called()


async def test_backfill_command_marks_failed_on_embed_error() -> None:
    """Per-row embed exception → mark row 'failed' and continue. Final status
    is success=0 failed=1, return code stays 0 (per-row failure isn't a
    process-level failure)."""
    rows = [_row()]
    session = _mock_session(rows)
    repo = AsyncMock()
    repo.update_embedding = AsyncMock()

    with (
        patch.object(bf, "get_settings", return_value=_patch_settings()),
        patch.object(bf, "create_async_engine", return_value=_mock_engine()),
        patch.object(bf, "AsyncSession", return_value=session),
        patch.object(bf, "VerifierRepository", return_value=repo),
        patch.object(bf, "sync_embed_one", side_effect=EmbeddingError("openai 5xx")),
    ):
        rc = await bf._run(argparse.Namespace(limit=None, retry_failed=False, dry_run=False))

    assert rc == 0
    assert repo.update_embedding.await_count == 1
    assert repo.update_embedding.call_args.kwargs["embedding_status"] == "failed"
    assert repo.update_embedding.call_args.kwargs["failure_embedding"] is None
