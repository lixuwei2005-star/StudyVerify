"""Top-level test fixtures shared across all test packages.

Promoted from tests/db/conftest.py so tests/repositories/, tests/services/,
and tests/api/ can also use the SQLite-in-memory data-layer fixture.
"""

from collections.abc import AsyncIterator

import pytest_asyncio
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

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
