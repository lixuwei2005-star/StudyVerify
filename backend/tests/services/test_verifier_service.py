"""Unit tests for VerifierService — orchestration only, no real DB or LLM.

VerifierAgent, VerifierRepository, SolverRepository, and AsyncSession are
all mocked so we can assert exact call ordering, kwarg shape, and the
commit/no-commit invariants.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.verifier.agent import VerifierAgent, VerifierError
from app.agents.verifier.schemas import RedactedTestResult, VerifierOutput
from app.db.models import SolverSession, VerifierSession
from app.llm.embedding import EmbeddingService
from app.repositories.solver_repository import SolverRepository
from app.repositories.verifier_repository import VerifierRepository
from app.services.verifier_service import (
    DataIntegrityError,
    SolverSessionNotFoundError,
    VerifierService,
)


def _solver_row(
    test_cases: list[dict] | None = None,
) -> SolverSession:
    return SolverSession(
        id=uuid.uuid4(),
        problem_id="py-001-sum-list",
        problem_text="Sum a list.",
        entry_function="sum_list",
        test_cases=test_cases or [{"input": "[1,2,3]", "expected": "6", "description": "basic"}],
        analysis="-",
        plan_steps=[],
        code="def sum_list(nums): return sum(nums)",
        explanation="-",
        verified=True,
        test_results=[],
        confidence=Decimal("0.90"),
        retry_used=False,
        total_latency_ms=10,
    )


def _verifier_output(verified: bool = True) -> VerifierOutput:
    return VerifierOutput(
        problem_id="py-001-sum-list",
        verified=verified,
        status="all_passed" if verified else "some_failed",
        pass_count=1 if verified else 0,
        fail_count=0 if verified else 1,
        test_results=[
            RedactedTestResult(
                input="[1,2,3]",
                actual="6" if verified else "0",
                passed=verified,
                duration_ms=1,
                error=None,
            )
        ],
        diagnosis="" if verified else "Off-by-one in sum.",
        sandbox_error=None,
    )


def _verifier_row(solver_session_id: uuid.UUID) -> VerifierSession:
    return VerifierSession(
        id=uuid.uuid4(),
        solver_session_id=solver_session_id,
        student_code="def sum_list(nums): return sum(nums)",
        verified=True,
        status="all_passed",
        pass_count=1,
        fail_count=0,
        test_results=[],
        diagnosis="",
        sandbox_error=None,
        total_latency_ms=42,
    )


def _service(
    *,
    solver_row: SolverSession | None = None,
    agent_output: VerifierOutput | None = None,
    agent_exc: Exception | None = None,
    repo_exc: Exception | None = None,
) -> tuple[VerifierService, MagicMock, MagicMock, MagicMock, MagicMock]:
    the_solver_row = solver_row if solver_row is not None else _solver_row()
    the_output = agent_output or _verifier_output()
    the_verifier_row = _verifier_row(the_solver_row.id)

    solver_repo = AsyncMock(spec=SolverRepository)
    solver_repo.get_by_id = AsyncMock(return_value=the_solver_row)

    agent = AsyncMock(spec=VerifierAgent)
    if agent_exc is not None:
        agent.verify = AsyncMock(side_effect=agent_exc)
    else:
        agent.verify = AsyncMock(return_value=the_output)

    verifier_repo = AsyncMock(spec=VerifierRepository)
    if repo_exc is not None:
        verifier_repo.create = AsyncMock(side_effect=repo_exc)
    else:
        verifier_repo.create = AsyncMock(return_value=the_verifier_row)
    verifier_repo.update_embedding = AsyncMock()

    embedding_service = AsyncMock(spec=EmbeddingService)
    embedding_service.embed = AsyncMock(return_value=[0.1] * 1536)

    session = MagicMock(spec=AsyncSession)
    session.commit = AsyncMock()
    session.refresh = AsyncMock()
    session.rollback = AsyncMock()

    service = VerifierService(
        agent=agent,
        repository=verifier_repo,
        solver_repository=solver_repo,
        embedding_service=embedding_service,
    )
    return service, solver_repo.get_by_id, agent.verify, verifier_repo.create, session


# ---------- happy path ----------


async def test_happy_path_orchestration_order() -> None:
    service, get_by_id, verify, create, session = _service()
    solver_id = uuid.uuid4()

    parent = MagicMock()
    parent.attach_mock(get_by_id, "get_by_id")
    parent.attach_mock(verify, "verify")
    parent.attach_mock(create, "create")
    parent.attach_mock(session.commit, "commit")
    parent.attach_mock(session.refresh, "refresh")

    row, output = await service.verify_and_persist(
        session, solver_id, "def sum_list(n): return sum(n)"
    )

    method_names = [c[0] for c in parent.mock_calls]
    assert method_names == ["get_by_id", "verify", "create", "commit", "refresh"]
    assert isinstance(output, VerifierOutput)


# ---------- error: solver not found ----------


async def test_solver_session_not_found_raises() -> None:
    service, get_by_id, verify, create, session = _service()
    get_by_id.return_value = None

    with pytest.raises(SolverSessionNotFoundError):
        await service.verify_and_persist(session, uuid.uuid4(), "code")

    verify.assert_not_awaited()
    create.assert_not_awaited()
    session.commit.assert_not_called()


# ---------- error propagation ----------


async def test_verifier_error_propagates_from_agent() -> None:
    service, _, verify, create, session = _service(agent_exc=VerifierError("Docker unavailable"))

    with pytest.raises(VerifierError):
        await service.verify_and_persist(session, uuid.uuid4(), "code")


async def test_agent_raise_does_not_commit() -> None:
    service, _, _, _, session = _service(agent_exc=RuntimeError("boom"))

    with pytest.raises(RuntimeError):
        await service.verify_and_persist(session, uuid.uuid4(), "code")

    session.commit.assert_not_called()
    session.refresh.assert_not_called()


async def test_repo_raise_does_not_commit() -> None:
    service, _, _, create, session = _service(repo_exc=RuntimeError("db boom"))

    with pytest.raises(RuntimeError):
        await service.verify_and_persist(session, uuid.uuid4(), "code")

    session.commit.assert_not_called()
    session.refresh.assert_not_called()


# ---------- latency ----------


async def test_total_latency_ms_measured_around_agent_call() -> None:
    service, _, _, create, session = _service()

    await service.verify_and_persist(session, uuid.uuid4(), "code")

    kwargs = create.await_args.kwargs
    assert kwargs["total_latency_ms"] >= 0
    assert kwargs["total_latency_ms"] < 10_000


# ---------- test_case round-trip ----------


async def test_test_case_round_trip_from_solver_row() -> None:
    """solver_row.test_cases list[dict] → TestCase objects in VerifierInput."""
    service, _, verify, _, session = _service()

    await service.verify_and_persist(session, uuid.uuid4(), "code")

    verifier_input = verify.await_args.args[0]
    from app.agents.solver.schemas import TestCase

    assert all(isinstance(tc, TestCase) for tc in verifier_input.test_cases)
    assert verifier_input.test_cases[0].input == "[1,2,3]"
    assert verifier_input.test_cases[0].expected == "6"


async def test_malformed_persisted_test_cases_raises_data_integrity_error() -> None:
    bad_solver_row = _solver_row(test_cases=[{"wrong_key": "no input/expected/description"}])
    service, _, _, _, session = _service(solver_row=bad_solver_row)

    with pytest.raises(DataIntegrityError):
        await service.verify_and_persist(session, uuid.uuid4(), "code")


# ---------- anti-leak: redacted results only ----------


async def test_service_persists_only_redacted_results() -> None:
    """test_results stored in the DB must not contain an 'expected' key."""
    output = _verifier_output(verified=False)
    service, _, _, create, session = _service(agent_output=output)

    await service.verify_and_persist(session, uuid.uuid4(), "code")

    kwargs = create.await_args.kwargs
    for item in kwargs["test_results"]:
        assert "expected" not in item, f"'expected' leaked into stored test result: {item}"


# ---------- regression: embedding failure must not crash /verify ----------


async def test_verify_and_persist_handles_embedding_failure() -> None:
    """Embedding failure (e.g., missing OPENAI_API_KEY) must NOT propagate
    as a 500 to the user. The verifier response is authoritative; embedding
    failure only means the row is unavailable as a future RAG candidate.

    Step 7 Phase 7 production deploy to Oracle Cloud surfaced this: prod
    .env had empty OPENAI_API_KEY so embed() raised every time, and the
    except branch did session.rollback() then accessed row.id, triggering
    a sync lazy-reload that asyncpg raised as MissingGreenlet. Mac dev had
    a real key so the rollback branch was never exercised. Fix caches
    verifier_id before any commit/rollback that expires ORM attributes.
    """
    service, _, _, _, session = _service(agent_output=_verifier_output(verified=False))
    service.embedding_service.embed = AsyncMock(
        side_effect=Exception("OpenAI API key not configured")
    )

    # Must not raise — verify response should still reach the caller.
    row, output = await service.verify_and_persist(
        session, uuid.uuid4(), "def sum_list(nums): return 0"
    )

    assert output.verified is False
    assert isinstance(row, VerifierSession)

    # embed raised, so the success-path update_embedding was never called;
    # the except branch ran update_embedding(embedding_status='failed') once.
    update_embedding = service.repository.update_embedding
    assert update_embedding.await_count == 1
    failed_call_kwargs = update_embedding.await_args.kwargs
    assert failed_call_kwargs["embedding_status"] == "failed"
    assert failed_call_kwargs["failure_embedding"] is None

    # Rollback fired before the failed-path update.
    session.rollback.assert_awaited_once()
