"""Top-level test fixtures shared across all test packages.

- `sqlite_session`: fast in-memory SQLite session for unit tests.
- `pg_schema`:      creates a per-test PG schema; yields the schema name.
- `pg_session`:     async session bound to `pg_schema` for direct DB tests.
"""

import uuid
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import get_settings
from app.db import models as _models  # noqa: F401  — register metadata
from app.db.base import Base


@pytest_asyncio.fixture
async def sqlite_session() -> AsyncIterator[AsyncSession]:
    """Fresh in-memory SQLite session per test. Renamed from `session` to avoid
    collision with API-layer fixtures that wrap an HTTP-coupled session."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as s:
        yield s
    await engine.dispose()


@pytest_asyncio.fixture
async def pg_schema() -> AsyncIterator[str]:
    """Per-test Postgres schema. Yields the schema name, drops on teardown.

    Schema setup happens here (one-time, in pytest-asyncio's loop). Anything
    that needs a session inside the schema must build its own engine — see
    `pg_session` below for direct-DB use.
    """
    settings = get_settings()
    if not settings.DATABASE_URL:
        pytest.skip("DATABASE_URL not set")

    schema_name = f"test_{uuid.uuid4().hex}"
    setup_engine = create_async_engine(
        settings.DATABASE_URL,
        connect_args={"server_settings": {"search_path": schema_name}},
    )
    async with setup_engine.begin() as conn:
        await conn.execute(text(f'CREATE SCHEMA "{schema_name}"'))
        await conn.run_sync(Base.metadata.create_all)
    await setup_engine.dispose()

    try:
        yield schema_name
    finally:
        teardown_engine = create_async_engine(settings.DATABASE_URL)
        async with teardown_engine.begin() as conn:
            await conn.execute(text(f'DROP SCHEMA IF EXISTS "{schema_name}" CASCADE'))
        await teardown_engine.dispose()


@pytest_asyncio.fixture
async def pg_session(pg_schema: str) -> AsyncIterator[AsyncSession]:
    """Async session bound to the per-test PG schema."""
    settings = get_settings()
    engine = create_async_engine(
        settings.DATABASE_URL,
        connect_args={"server_settings": {"search_path": pg_schema}},
    )
    try:
        async with AsyncSession(engine, expire_on_commit=False) as s:
            yield s
    finally:
        await engine.dispose()
