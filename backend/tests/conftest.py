"""Top-level test fixtures shared across all test packages.

- `sqlite_session`: fast in-memory SQLite session for unit tests.
- `pg_schema`:      creates a per-test PG schema; yields the schema name.
- `pg_session`:     async session bound to `pg_schema` for direct DB tests.
- `app_with_overrides` + `client`: TestClient driving the FastAPI app with
   `get_db_session` rerouted into the per-test schema. Each HTTP request
   gets its own engine (created on the request's own event loop) so there
   is no loop-mismatch between pytest-asyncio's loop and TestClient's.
"""

import uuid
from collections.abc import AsyncIterator, Iterator

import pytest
import pytest_asyncio
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import get_settings
from app.db import models as _models  # noqa: F401  — register metadata
from app.db.base import Base


def _test_database_url() -> str:
    """Swap the database name in DATABASE_URL to `studyverify_test`.

    PG-marked tests need an isolated database because the dev DB has tables
    in `public` from compose-up alembic. With both `public` and the per-test
    schema in search_path (required for vector type lookup), SQLAlchemy's
    `create_all` sees the existing public tables and skips creation in the
    per-test schema — queries then fall through to the polluted public
    tables. The test database is created out-of-band by the operator
    (one-time `CREATE DATABASE studyverify_test;`).
    """
    url = get_settings().DATABASE_URL
    # Replace the path portion after the last '/' before any '?'.
    if "?" in url:
        base, q = url.rsplit("?", 1)
        return base.rsplit("/", 1)[0] + "/studyverify_test?" + q
    return url.rsplit("/", 1)[0] + "/studyverify_test"


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
    `pg_session` below for direct-DB use, and the `app_with_overrides`
    fixture for the TestClient flow which builds a fresh engine per request.
    """
    if not get_settings().DATABASE_URL:
        pytest.skip("DATABASE_URL not set")

    test_url = _test_database_url()
    schema_name = f"test_{uuid.uuid4().hex}"
    # Install pgvector at the database scope of studyverify_test BEFORE schema
    # setup. The extension is DB-wide; first test creates it, rest no-op.
    # Without this, `Base.metadata.create_all` fails on Vector(1536) columns.
    base_engine = create_async_engine(test_url)
    async with base_engine.begin() as conn:
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
    await base_engine.dispose()

    # search_path includes 'public' so the vector type (installed by CREATE
    # EXTENSION above into public schema) resolves when the test schema's
    # tables reference Vector(1536) columns. Test runs against
    # studyverify_test which has no leftover tables in public, so isolation
    # holds (unlike the dev DB whose public has alembic-created tables).
    setup_engine = create_async_engine(
        test_url,
        connect_args={"server_settings": {"search_path": f"{schema_name},public"}},
    )
    async with setup_engine.begin() as conn:
        await conn.execute(text(f'CREATE SCHEMA "{schema_name}"'))
        await conn.run_sync(Base.metadata.create_all)
    await setup_engine.dispose()

    try:
        yield schema_name
    finally:
        teardown_engine = create_async_engine(test_url)
        async with teardown_engine.begin() as conn:
            await conn.execute(text(f'DROP SCHEMA IF EXISTS "{schema_name}" CASCADE'))
        await teardown_engine.dispose()


@pytest_asyncio.fixture
async def pg_session(pg_schema: str) -> AsyncIterator[AsyncSession]:
    """Async session bound to the per-test PG schema in studyverify_test."""
    engine = create_async_engine(
        _test_database_url(),
        connect_args={"server_settings": {"search_path": f"{pg_schema},public"}},
    )
    try:
        async with AsyncSession(engine, expire_on_commit=False) as s:
            yield s
    finally:
        await engine.dispose()


@pytest.fixture
def app_with_overrides(pg_schema: str) -> Iterator[FastAPI]:
    """FastAPI app with `get_db_session` rerouted into the per-test schema.

    The override builds a fresh engine + session on each request so the
    AsyncSession lives entirely inside TestClient's per-request event loop
    (which is distinct from pytest-asyncio's). Saving and restoring
    `dependency_overrides` (rather than `clear()`) keeps any per-test agent
    overrides set later by the calling test from being clobbered.
    """
    from app.db.session import get_db_session
    from app.main import app

    old_overrides = app.dependency_overrides.copy()

    async def override_get_session() -> AsyncIterator[AsyncSession]:
        engine = create_async_engine(
            _test_database_url(),
            connect_args={"server_settings": {"search_path": f"{pg_schema},public"}},
        )
        factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        try:
            async with factory() as session:
                try:
                    yield session
                except Exception:
                    await session.rollback()
                    raise
        finally:
            await engine.dispose()

    app.dependency_overrides[get_db_session] = override_get_session
    try:
        yield app
    finally:
        app.dependency_overrides = old_overrides


@pytest.fixture
def client(app_with_overrides: FastAPI) -> Iterator[TestClient]:
    """Sync TestClient. The `with` triggers FastAPI lifespan startup/shutdown."""
    with TestClient(app_with_overrides) as c:
        yield c
