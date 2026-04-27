from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import SolverSession


class SolverRepository:
    """Pure DB access for the solver_sessions table.

    Storage-agnostic boundary: knows nothing about Agents, Services, or
    Pydantic schemas. Receives plain dicts/primitives, returns ORM rows.

    Transaction discipline: this layer never commits. The Service that owns
    the business transaction calls session.commit(). create() uses flush()
    so the row's server-generated id is populated without ending the txn.
    """

    async def create(
        self,
        session: AsyncSession,
        *,
        problem_id: str,
        problem_text: str,
        test_cases: list[dict],
        analysis: str,
        plan_steps: list[dict],
        code: str,
        explanation: str,
        verified: bool,
        test_results: list[dict],
        confidence: float,
        retry_used: bool,
        total_latency_ms: int,
    ) -> SolverSession:
        row = SolverSession(
            problem_id=problem_id,
            problem_text=problem_text,
            test_cases=test_cases,
            analysis=analysis,
            plan_steps=plan_steps,
            code=code,
            explanation=explanation,
            verified=verified,
            test_results=test_results,
            confidence=confidence,
            retry_used=retry_used,
            total_latency_ms=total_latency_ms,
        )
        session.add(row)
        await session.flush()
        return row

    async def get_by_id(
        self, session: AsyncSession, session_id: UUID
    ) -> SolverSession | None:
        result = await session.execute(
            select(SolverSession).where(SolverSession.id == session_id)
        )
        return result.scalar_one_or_none()

    async def list_by_problem(
        self,
        session: AsyncSession,
        problem_id: str,
        *,
        limit: int = 10,
        offset: int = 0,
    ) -> list[SolverSession]:
        result = await session.execute(
            select(SolverSession)
            .where(SolverSession.problem_id == problem_id)
            .order_by(SolverSession.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(result.scalars().all())

    async def count_by_problem(
        self, session: AsyncSession, problem_id: str
    ) -> int:
        result = await session.execute(
            select(func.count())
            .select_from(SolverSession)
            .where(SolverSession.problem_id == problem_id)
        )
        return result.scalar_one()
