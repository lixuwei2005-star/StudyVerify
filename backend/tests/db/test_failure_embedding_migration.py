"""Migration & fixture meta-tests for Step 6.2.

Locks two contracts:
1. `alembic upgrade head` succeeds without OPENAI_API_KEY (compose API
   startup runs alembic; migration must not depend on an LLM provider).
2. The pg_session fixture installs the `vector` extension before
   Base.metadata.create_all, so Vector(1536) columns can be created.

Plus a reduced-scope sanity check that FastAPI app boots with RAG disabled
and OPENAI_API_KEY unset.
"""

from __future__ import annotations

import os
import subprocess
import sys
import uuid
from pathlib import Path
from urllib.parse import urlparse

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.core.config import get_settings

BACKEND_DIR = Path(__file__).resolve().parents[2]


def _parse_dburl_components(url: str) -> dict[str, str]:
    """Extract user/host/port from postgresql+asyncpg://user:pass@host:port/db."""
    p = urlparse(url.replace("+asyncpg", "", 1))
    return {
        "user": p.username or "studyverify",
        "host": p.hostname or "localhost",
        "port": str(p.port or 5432),
        "db": (p.path or "/studyverify").lstrip("/"),
    }


@pytest.mark.integration
async def test_pg_fixture_creates_vector_extension(pg_session: AsyncSession) -> None:
    """Meta-test: the pg_session fixture must have installed pgvector before
    handing the session to the test, otherwise Vector(1536) columns in
    Base.metadata.create_all would not have succeeded."""
    result = await pg_session.execute(
        text("SELECT extname FROM pg_extension WHERE extname = 'vector'")
    )
    row = result.first()
    assert row is not None, "pgvector extension is not installed in the test database"
    assert row.extname == "vector"


async def _admin_exec(url: str, sql: str) -> None:
    """Execute DDL that can't run inside a transaction (CREATE/DROP DATABASE)
    using an asyncpg engine in AUTOCOMMIT isolation."""
    engine = create_async_engine(url, isolation_level="AUTOCOMMIT")
    try:
        async with engine.connect() as conn:
            await conn.execute(text(sql))
    finally:
        await engine.dispose()


@pytest.mark.integration
async def test_migration_works_without_openai_key() -> None:
    """Run `alembic upgrade head` against a per-run scratch database with
    OPENAI_API_KEY=''. The structural migration must succeed.

    Uses an out-of-band scratch DB so we never touch dev or studyverify_test.
    """
    settings = get_settings()
    if not settings.DATABASE_URL:
        pytest.skip("DATABASE_URL not set")

    scratch_name = f"studyverify_migtest_{uuid.uuid4().hex[:12]}"
    try:
        await _admin_exec(settings.DATABASE_URL, f'CREATE DATABASE "{scratch_name}"')
    except Exception as exc:
        pytest.skip(f"could not create scratch DB: {exc}")

    try:
        scratch_url = settings.DATABASE_URL.rsplit("/", 1)[0] + f"/{scratch_name}"
        env = {
            **os.environ,
            "DATABASE_URL": scratch_url,
            "OPENAI_API_KEY": "",  # the contract under test
        }

        result = subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            cwd=str(BACKEND_DIR),
            env=env,
            capture_output=True,
            text=True,
            timeout=60,
        )
        combined = result.stdout + result.stderr
        assert result.returncode == 0, (
            f"alembic upgrade head failed with empty OPENAI_API_KEY:\n{combined}"
        )
        assert "de9421cbca21" in combined
    finally:
        try:
            await _admin_exec(
                settings.DATABASE_URL, f'DROP DATABASE IF EXISTS "{scratch_name}"'
            )
        except Exception:
            pass


@pytest.mark.integration
def test_compose_api_starts_with_rag_disabled() -> None:
    """Reduced-scope contract test: full compose-up under RAG_ENABLED=false
    is too heavy for pytest. We instead boot the FastAPI app via TestClient
    and hit /health, with a Settings instance that has RAG_ENABLED=False
    and OPENAI_API_KEY=''.

    Skipped if DATABASE_URL is unset (lifespan startup needs PG reachable).
    """
    from fastapi.testclient import TestClient

    from app.core.config import Settings
    from app.core.config import get_settings as _get_settings

    if not _get_settings().DATABASE_URL:
        pytest.skip("DATABASE_URL not set")

    real_url = _get_settings().DATABASE_URL
    new_settings = Settings(
        DATABASE_URL=real_url,
        OPENAI_API_KEY="",
        RAG_ENABLED=False,
    )

    _get_settings.cache_clear()
    import app.core.config as config_mod

    original_factory = config_mod.get_settings
    config_mod.get_settings = lambda: new_settings  # type: ignore[assignment]
    try:
        from app.main import app

        with TestClient(app) as client:
            r = client.get("/health")
            assert r.status_code == 200, r.text
    finally:
        config_mod.get_settings = original_factory  # type: ignore[assignment]
        _get_settings.cache_clear()
