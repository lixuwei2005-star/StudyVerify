import logging
import time
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.solver.schemas import TestCase
from app.agents.verifier.agent import VerifierAgent
from app.agents.verifier.schemas import VerifierInput, VerifierOutput
from app.db.models import VerifierSession
from app.llm.embedding import EmbeddingService, build_failure_text
from app.repositories.solver_repository import SolverRepository
from app.repositories.verifier_repository import VerifierRepository

logger = logging.getLogger(__name__)


class SolverSessionNotFoundError(Exception):
    """Raised when verify request references a missing solver_session_id."""


class DataIntegrityError(Exception):
    """Raised when persisted solver data is malformed for verifier input."""


class VerifierService:
    """Orchestrates VerifierAgent + VerifierRepository inside one DB transaction.

    Session lifetime: the AsyncSession is passed *per call*, NOT held on
    the instance. The service is a stateless shell; session lifetime is owned
    by FastAPI's get_db_session dependency.
    """

    def __init__(
        self,
        agent: VerifierAgent,
        repository: VerifierRepository,
        solver_repository: SolverRepository,
        embedding_service: EmbeddingService,
    ) -> None:
        self.agent = agent
        self.repository = repository
        self.solver_repository = solver_repository
        self.embedding_service = embedding_service

    async def verify_and_persist(
        self,
        session: AsyncSession,
        solver_session_id: UUID,
        student_code: str,
    ) -> tuple[VerifierSession, VerifierOutput]:
        solver_row = await self.solver_repository.get_by_id(session, solver_session_id)
        if solver_row is None:
            raise SolverSessionNotFoundError(f"solver_session {solver_session_id} not found")

        try:
            test_cases = [TestCase(**tc) for tc in solver_row.test_cases]
        except (TypeError, ValidationError) as exc:
            raise DataIntegrityError("persisted solver_session has malformed test_cases") from exc

        verifier_input = VerifierInput(
            problem_id=solver_row.problem_id,
            problem_text=solver_row.problem_text,
            entry_function=solver_row.entry_function,
            test_cases=test_cases,
            student_code=student_code,
        )

        start = time.perf_counter()
        output = await self.agent.verify(verifier_input)
        total_latency_ms = int((time.perf_counter() - start) * 1000)

        row = await self.repository.create(
            session,
            solver_session_id=solver_session_id,
            student_code=student_code,
            verified=output.verified,
            status=output.status,
            pass_count=output.pass_count,
            fail_count=output.fail_count,
            test_results=[tr.model_dump() for tr in output.test_results],
            diagnosis=output.diagnosis,
            sandbox_error=output.sandbox_error,
            total_latency_ms=total_latency_ms,
        )
        await session.commit()
        await session.refresh(row)

        # RAG hook: embed failed verifier sessions for similarity retrieval.
        # Embedding failure must NOT propagate — the verifier response is
        # authoritative; a failed embedding only means this row is unavailable
        # as a future RAG candidate (embedding_status='failed').
        if not output.verified and output.test_results:
            try:
                failure_text = build_failure_text(
                    problem_text=verifier_input.problem_text,
                    student_code=verifier_input.student_code,
                    failed_test_inputs=[tr.input for tr in output.test_results if not tr.passed],
                    diagnosis=output.diagnosis,
                    sandbox_error=output.sandbox_error,
                )
                embedding = await self.embedding_service.embed(failure_text)
                await self.repository.update_embedding(
                    session,
                    verifier_session_id=row.id,
                    failure_embedding=embedding,
                    embedding_status="success",
                )
                await session.commit()
                await session.refresh(row)
            except Exception as exc:
                logger.warning(
                    "Embedding generation failed for verifier_session %s: %s. "
                    "Marking embedding_status=failed.",
                    row.id,
                    exc,
                )
                try:
                    await session.rollback()
                    await self.repository.update_embedding(
                        session,
                        verifier_session_id=row.id,
                        failure_embedding=None,
                        embedding_status="failed",
                    )
                    await session.commit()
                    await session.refresh(row)
                except Exception as exc2:
                    logger.error(
                        "Failed to mark embedding_status=failed for verifier_session %s: %s",
                        row.id,
                        exc2,
                    )
                    # Swallow — the verifier response itself must still succeed.

        return row, output
