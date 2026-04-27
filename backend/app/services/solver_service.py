import time

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.solver.agent import SolverAgent
from app.agents.solver.schemas import SolverInput, SolverOutput
from app.db.models import SolverSession
from app.repositories.solver_repository import SolverRepository


class SolverService:
    """Orchestrates SolverAgent + SolverRepository inside one DB transaction.

    Owns the end-to-end latency measurement and the commit boundary; the
    Repository never commits. Returns the persisted ORM row alongside the
    agent's SolverOutput so the API layer can build a response shape that
    includes both the new session_id and the full output.

    Session lifetime: the AsyncSession is passed *per call* to
    `solve_and_persist`, NOT held on the instance. This is deliberate —
    the service is a stateless shell, so the request-scoped session
    injected by FastAPI's `get_db_session` dependency stays bound to its
    own request even though the Service object is shared. Do not refactor
    `session` onto __init__: that would tie session lifetime to Service
    construction, leaking sessions across requests and breaking the
    "Service owns the commit boundary, dependency owns the session
    boundary" contract.
    """

    def __init__(self, agent: SolverAgent, repository: SolverRepository) -> None:
        self.agent = agent
        self.repository = repository

    async def solve_and_persist(
        self, session: AsyncSession, solver_input: SolverInput
    ) -> tuple[SolverSession, SolverOutput]:
        start = time.perf_counter()

        output = await self.agent.solve(solver_input)

        total_latency_ms = int((time.perf_counter() - start) * 1000)

        row = await self.repository.create(
            session,
            problem_id=output.problem_id,
            problem_text=solver_input.problem_text,
            test_cases=[tc.model_dump() for tc in solver_input.test_cases],
            analysis=output.analysis,
            plan_steps=[ps.model_dump() for ps in output.plan_steps],
            code=output.code,
            explanation=output.explanation,
            verified=output.verified,
            test_results=[tr.model_dump() for tr in output.test_results],
            confidence=output.confidence,
            retry_used=output.retry_used,
            total_latency_ms=total_latency_ms,
        )
        await session.commit()
        await session.refresh(row)
        return row, output
