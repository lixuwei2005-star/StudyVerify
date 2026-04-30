from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import VerifierSession


class VerifierRepository:
    """Pure DB access for the verifier_sessions table.

    Transaction discipline: this layer never commits. The Service that owns
    the business transaction calls session.commit(). create() uses flush()
    so the row's server-generated id is populated without ending the txn.
    """

    async def create(
        self,
        session: AsyncSession,
        *,
        solver_session_id: UUID,
        student_code: str,
        verified: bool,
        status: str,
        pass_count: int,
        fail_count: int,
        test_results: list[dict],
        diagnosis: str,
        sandbox_error: str | None,
        total_latency_ms: int,
    ) -> VerifierSession:
        row = VerifierSession(
            solver_session_id=solver_session_id,
            student_code=student_code,
            verified=verified,
            status=status,
            pass_count=pass_count,
            fail_count=fail_count,
            test_results=test_results,
            diagnosis=diagnosis,
            sandbox_error=sandbox_error,
            total_latency_ms=total_latency_ms,
        )
        session.add(row)
        await session.flush()
        return row

    async def get_by_id(
        self, session: AsyncSession, session_id: UUID
    ) -> VerifierSession | None:
        result = await session.execute(
            select(VerifierSession).where(VerifierSession.id == session_id)
        )
        return result.scalar_one_or_none()

    async def list_by_solver_session(
        self,
        session: AsyncSession,
        solver_session_id: UUID,
        *,
        limit: int = 10,
        offset: int = 0,
    ) -> list[VerifierSession]:
        result = await session.execute(
            select(VerifierSession)
            .where(VerifierSession.solver_session_id == solver_session_id)
            .order_by(VerifierSession.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(result.scalars().all())

    async def count_by_solver_session(
        self,
        session: AsyncSession,
        solver_session_id: UUID,
    ) -> int:
        result = await session.execute(
            select(func.count())
            .select_from(VerifierSession)
            .where(VerifierSession.solver_session_id == solver_session_id)
        )
        return result.scalar_one()
