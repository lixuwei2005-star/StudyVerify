from __future__ import annotations

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import HintSession


class HintRepository:
    """Pure DB access. Never commits — caller owns the transaction."""

    async def create(
        self,
        session: AsyncSession,
        *,
        verifier_session_id: UUID,
        hint_index: int,
        hint_text: str,
        prior_hints_count: int,
        total_latency_ms: int,
    ) -> HintSession:
        row = HintSession(
            verifier_session_id=verifier_session_id,
            hint_index=hint_index,
            hint_text=hint_text,
            prior_hints_count=prior_hints_count,
            total_latency_ms=total_latency_ms,
        )
        session.add(row)
        await session.flush()
        return row

    async def get_by_id(
        self,
        session: AsyncSession,
        session_id: UUID,
    ) -> HintSession | None:
        result = await session.execute(
            select(HintSession).where(HintSession.id == session_id)
        )
        return result.scalar_one_or_none()

    async def list_by_verifier_session(
        self,
        session: AsyncSession,
        verifier_session_id: UUID,
    ) -> list[HintSession]:
        """Returns all hints for a verifier_session, ordered by hint_index ascending."""
        result = await session.execute(
            select(HintSession)
            .where(HintSession.verifier_session_id == verifier_session_id)
            .order_by(HintSession.hint_index.asc())
        )
        return list(result.scalars().all())

    async def count_by_verifier_session(
        self,
        session: AsyncSession,
        verifier_session_id: UUID,
    ) -> int:
        result = await session.execute(
            select(func.count())
            .select_from(HintSession)
            .where(HintSession.verifier_session_id == verifier_session_id)
        )
        return result.scalar_one()
