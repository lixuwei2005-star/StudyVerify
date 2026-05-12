"""Unit tests for HintService — orchestration only, no real DB or LLM.

HintAgent, HintRepository, VerifierRepository, SolverRepository, and
AsyncSession are all mocked so we can assert exact call ordering, kwarg
shape, the LLM-only-once-on-retry invariant, and the diagnosis-seeding
asymmetry between prior_hints_count and hint_index.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.hint.agent import HintAgent
from app.agents.hint.schemas import HintInput, HintOutput
from app.core.config import Settings
from app.db.models import HintSession, SolverSession, VerifierSession
from app.llm.embedding import EmbeddingService
from app.repositories.hint_repository import HintRepository
from app.repositories.solver_repository import SolverRepository
from app.repositories.verifier_repository import VerifierRepository
from app.services.hint_service import (
    MAX_HINTS_PER_VERIFIER_SESSION,
    DataIntegrityError,
    HintConcurrencyError,
    HintLimitExceededError,
    HintService,
    VerifierSessionNotFoundError,
    VerifierSessionPassedError,
)
from app.services.retrieval_service import RetrievalService

# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


def _solver_row() -> SolverSession:
    return SolverSession(
        id=uuid.uuid4(),
        problem_id="py-001-sum-list",
        problem_text="Return the sum of a list of integers.",
        entry_function="sum_list",
        test_cases=[{"input": "[1,2,3]", "expected": "6", "description": "basic"}],
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


def _verifier_row(
    solver_session_id: uuid.UUID,
    *,
    verified: bool = False,
    diagnosis: str = "Your function always returns 0.",
    test_results: list[dict] | None = None,
) -> VerifierSession:
    return VerifierSession(
        id=uuid.uuid4(),
        solver_session_id=solver_session_id,
        student_code="def sum_list(nums): return 0",
        verified=verified,
        status="all_passed" if verified else "some_failed",
        pass_count=1 if verified else 0,
        fail_count=0 if verified else 1,
        test_results=test_results
        if test_results is not None
        else [
            {
                "input": "[1,2,3]",
                "actual": "0",
                "passed": False,
                "duration_ms": 1,
                "error": None,
            },
            {
                "input": "[]",
                "actual": "0",
                "passed": True,
                "duration_ms": 1,
                "error": None,
            },
        ],
        diagnosis=diagnosis,
        sandbox_error=None,
        total_latency_ms=42,
    )


def _hint_row(verifier_session_id: uuid.UUID, hint_index: int = 1) -> HintSession:
    return HintSession(
        id=uuid.uuid4(),
        verifier_session_id=verifier_session_id,
        hint_index=hint_index,
        hint_text=f"Generated hint #{hint_index}",
        prior_hints_count=hint_index - 1,
        total_latency_ms=99,
    )


def _service(
    *,
    solver_row: SolverSession | None = None,
    verifier_row: VerifierSession | None = None,
    prior_hint_rows: list[HintSession] | None = None,
    prior_count: int | None = None,
    agent_output: HintOutput | None = None,
    agent_exc: Exception | None = None,
    create_side_effect: list[Exception | HintSession] | Exception | None = None,
) -> tuple[
    HintService,
    AsyncMock,  # solver_repo.get_by_id
    AsyncMock,  # verifier_repo.get_by_id
    AsyncMock,  # hint_repo.list_by_verifier_session
    AsyncMock,  # hint_repo.count_by_verifier_session
    AsyncMock,  # hint_repo.create
    AsyncMock,  # agent.generate
    MagicMock,  # session
]:
    the_solver = solver_row if solver_row is not None else _solver_row()
    the_verifier = verifier_row if verifier_row is not None else _verifier_row(the_solver.id)
    the_priors = prior_hint_rows if prior_hint_rows is not None else []
    the_count = prior_count if prior_count is not None else len(the_priors)

    solver_repo = AsyncMock(spec=SolverRepository)
    solver_repo.get_by_id = AsyncMock(return_value=the_solver)

    verifier_repo = AsyncMock(spec=VerifierRepository)
    verifier_repo.get_by_id = AsyncMock(return_value=the_verifier)

    hint_repo = AsyncMock(spec=HintRepository)
    hint_repo.list_by_verifier_session = AsyncMock(return_value=the_priors)
    hint_repo.count_by_verifier_session = AsyncMock(return_value=the_count)

    if create_side_effect is None:
        hint_repo.create = AsyncMock(
            return_value=_hint_row(the_verifier.id, hint_index=the_count + 1)
        )
    elif isinstance(create_side_effect, Exception):
        hint_repo.create = AsyncMock(side_effect=create_side_effect)
    else:
        hint_repo.create = AsyncMock(side_effect=create_side_effect)

    agent = AsyncMock(spec=HintAgent)
    if agent_exc is not None:
        agent.generate = AsyncMock(side_effect=agent_exc)
    else:
        agent.generate = AsyncMock(
            return_value=agent_output or HintOutput(hint_text="Think about edge cases.")
        )

    session = MagicMock(spec=AsyncSession)
    session.commit = AsyncMock()
    session.refresh = AsyncMock()
    session.rollback = AsyncMock()

    embedding_service = AsyncMock(spec=EmbeddingService)
    embedding_service.embed = AsyncMock(return_value=[0.1] * 1536)
    retrieval_service = AsyncMock(spec=RetrievalService)
    retrieval_service.find_similar_failures = AsyncMock(return_value=[])
    # Default RAG_ENABLED=False so orchestration-order assertions in existing
    # tests don't have to account for the embed/retrieve call pair. Tests that
    # exercise RAG override .settings on the service after construction.
    settings = Settings(RAG_ENABLED=False)

    service = HintService(
        agent=agent,
        repository=hint_repo,
        verifier_repository=verifier_repo,
        solver_repository=solver_repo,
        embedding_service=embedding_service,
        retrieval_service=retrieval_service,
        settings=settings,
    )
    return (
        service,
        solver_repo.get_by_id,
        verifier_repo.get_by_id,
        hint_repo.list_by_verifier_session,
        hint_repo.count_by_verifier_session,
        hint_repo.create,
        agent.generate,
        session,
    )


# ---------------------------------------------------------------------------
# 1. Happy path orchestration order
# ---------------------------------------------------------------------------
async def test_happy_path_orchestration_order() -> None:
    (
        service,
        solver_get,
        verifier_get,
        list_priors,
        count_priors,
        create,
        generate,
        session,
    ) = _service()

    parent = MagicMock()
    parent.attach_mock(verifier_get, "verifier_get")
    parent.attach_mock(solver_get, "solver_get")
    parent.attach_mock(list_priors, "list_priors")
    parent.attach_mock(count_priors, "count_priors")
    parent.attach_mock(generate, "generate")
    parent.attach_mock(create, "create")
    parent.attach_mock(session.commit, "commit")
    parent.attach_mock(session.refresh, "refresh")

    row, output = await service.generate_and_persist(session, uuid.uuid4())

    method_names = [c[0] for c in parent.mock_calls]
    assert method_names == [
        "verifier_get",
        "solver_get",
        "list_priors",
        "count_priors",
        "generate",
        "create",
        "commit",
        "refresh",
    ]
    assert isinstance(output, HintOutput)


# ---------------------------------------------------------------------------
# 2. VerifierSessionNotFoundError raises when verifier is missing
# ---------------------------------------------------------------------------
async def test_verifier_session_not_found_raises() -> None:
    (
        service,
        _,
        verifier_get,
        _,
        _,
        create,
        generate,
        session,
    ) = _service()
    verifier_get.return_value = None

    with pytest.raises(VerifierSessionNotFoundError):
        await service.generate_and_persist(session, uuid.uuid4())

    generate.assert_not_awaited()
    create.assert_not_awaited()
    session.commit.assert_not_called()


# ---------------------------------------------------------------------------
# 3. VerifierSessionPassedError raises when verified=True
# ---------------------------------------------------------------------------
async def test_verifier_session_passed_raises_no_llm_call() -> None:
    solver = _solver_row()
    verifier = _verifier_row(solver.id, verified=True, diagnosis="")
    (
        service,
        _,
        _,
        _,
        _,
        create,
        generate,
        session,
    ) = _service(solver_row=solver, verifier_row=verifier)

    with pytest.raises(VerifierSessionPassedError):
        await service.generate_and_persist(session, uuid.uuid4())

    generate.assert_not_awaited()
    create.assert_not_awaited()
    session.commit.assert_not_called()


# ---------------------------------------------------------------------------
# 4. Solver missing → defensive VerifierSessionNotFoundError (FK should prevent)
# ---------------------------------------------------------------------------
async def test_solver_missing_raises_defensive_error() -> None:
    (
        service,
        solver_get,
        _,
        _,
        _,
        create,
        generate,
        session,
    ) = _service()
    solver_get.return_value = None

    with pytest.raises(VerifierSessionNotFoundError):
        await service.generate_and_persist(session, uuid.uuid4())

    generate.assert_not_awaited()
    create.assert_not_awaited()


# ---------------------------------------------------------------------------
# 5. Prior hints fetched in order (returned by list_by_verifier_session)
# ---------------------------------------------------------------------------
async def test_prior_hints_fetched_in_order_and_passed_to_agent() -> None:
    solver = _solver_row()
    verifier = _verifier_row(solver.id, diagnosis="")
    priors = [
        _hint_row(verifier.id, hint_index=1),
        _hint_row(verifier.id, hint_index=2),
        _hint_row(verifier.id, hint_index=3),
    ]
    priors[0].hint_text = "First hint."
    priors[1].hint_text = "Second hint."
    priors[2].hint_text = "Third hint."

    (
        service,
        _,
        _,
        _,
        _,
        _,
        generate,
        session,
    ) = _service(
        solver_row=solver,
        verifier_row=verifier,
        prior_hint_rows=priors,
        prior_count=3,
    )

    await service.generate_and_persist(session, uuid.uuid4())

    hint_input: HintInput = generate.await_args.args[0]
    assert hint_input.prior_hints == ["First hint.", "Second hint.", "Third hint."]


# ---------------------------------------------------------------------------
# 6. failed_test_inputs extracted from verifier.test_results (only failed)
# ---------------------------------------------------------------------------
async def test_failed_test_inputs_extracted_only_from_failures() -> None:
    solver = _solver_row()
    test_results = [
        {"input": "[1]", "actual": "0", "passed": False, "duration_ms": 1, "error": None},
        {"input": "[2]", "actual": "2", "passed": True, "duration_ms": 1, "error": None},
        {"input": "[3]", "actual": "0", "passed": False, "duration_ms": 1, "error": None},
    ]
    verifier = _verifier_row(solver.id, test_results=test_results)

    (service, _, _, _, _, _, generate, session) = _service(solver_row=solver, verifier_row=verifier)

    await service.generate_and_persist(session, uuid.uuid4())

    hint_input: HintInput = generate.await_args.args[0]
    assert hint_input.failed_test_inputs == ["[1]", "[3]"]


# ---------------------------------------------------------------------------
# 7. hint_index calculated from DB count of actual hint rows
# ---------------------------------------------------------------------------
async def test_hint_index_calculated_from_db_count() -> None:
    solver = _solver_row()
    verifier = _verifier_row(solver.id, diagnosis="")
    priors = [_hint_row(verifier.id, hint_index=1), _hint_row(verifier.id, hint_index=2)]

    (service, _, _, _, _, create, _, session) = _service(
        solver_row=solver,
        verifier_row=verifier,
        prior_hint_rows=priors,
        prior_count=2,
    )

    await service.generate_and_persist(session, uuid.uuid4())

    kwargs = create.await_args.kwargs
    assert kwargs["hint_index"] == 3


# ---------------------------------------------------------------------------
# 8. Agent raises unexpectedly → no commit
# ---------------------------------------------------------------------------
async def test_agent_unexpected_raise_does_not_commit() -> None:
    (service, _, _, _, _, _, _, session) = _service(agent_exc=RuntimeError("boom"))

    with pytest.raises(RuntimeError):
        await service.generate_and_persist(session, uuid.uuid4())

    session.commit.assert_not_called()
    session.refresh.assert_not_called()


# ---------------------------------------------------------------------------
# 9. Repo create raises non-IntegrityError → no commit, no retry
# ---------------------------------------------------------------------------
async def test_repo_non_integrity_raise_does_not_commit_or_retry() -> None:
    (service, _, _, _, _, create, _, session) = _service(create_side_effect=RuntimeError("db boom"))

    with pytest.raises(RuntimeError):
        await service.generate_and_persist(session, uuid.uuid4())

    assert create.await_count == 1
    session.commit.assert_not_called()
    session.refresh.assert_not_called()


# ---------------------------------------------------------------------------
# 10. Concurrent insert retries once on IntegrityError; LLM called once only
# ---------------------------------------------------------------------------
async def test_concurrent_insert_retries_once_on_integrity_error() -> None:
    solver = _solver_row()
    verifier = _verifier_row(solver.id, diagnosis="")
    success_row = _hint_row(verifier.id, hint_index=2)

    (
        service,
        _,
        _,
        list_priors,
        _,
        create,
        generate,
        session,
    ) = _service(
        solver_row=solver,
        verifier_row=verifier,
        prior_hint_rows=[],
        prior_count=0,
        create_side_effect=[
            IntegrityError("uq_hint_sessions_verifier_index", None, Exception()),
            success_row,
        ],
    )

    # On retry we refetch the prior hints list — return one row this time
    # so the recomputed hint_index becomes 2.
    list_priors.side_effect = [[], [_hint_row(verifier.id, hint_index=1)]]

    row, output = await service.generate_and_persist(session, uuid.uuid4())

    assert row is success_row
    assert isinstance(output, HintOutput)
    assert create.await_count == 2
    # Critical: LLM called exactly once even on retry
    generate.assert_awaited_once()
    # The retry uses len(prior_hint_rows) + 1, so the second insert had hint_index=2
    second_call_kwargs = create.await_args_list[1].kwargs
    assert second_call_kwargs["hint_index"] == 2
    session.commit.assert_called_once()
    session.rollback.assert_called_once()


# ---------------------------------------------------------------------------
# 11. Concurrent insert raises HintConcurrencyError after retry exhausted
# ---------------------------------------------------------------------------
async def test_concurrent_insert_raises_after_retry_exhausted() -> None:
    (service, _, _, list_priors, _, create, _, session) = _service(
        create_side_effect=[
            IntegrityError("uq_hint_sessions_verifier_index", None, Exception()),
            IntegrityError("uq_hint_sessions_verifier_index", None, Exception()),
        ],
    )
    list_priors.side_effect = [[], []]

    with pytest.raises(HintConcurrencyError):
        await service.generate_and_persist(session, uuid.uuid4())

    assert create.await_count == 2
    session.commit.assert_not_called()
    assert session.rollback.await_count == 2


# ---------------------------------------------------------------------------
# 12. Max hints exceeded raises before LLM call
# ---------------------------------------------------------------------------
async def test_max_hints_exceeded_raises_before_llm_call() -> None:
    solver = _solver_row()
    verifier = _verifier_row(solver.id, diagnosis="")
    priors = [
        _hint_row(verifier.id, hint_index=i + 1) for i in range(MAX_HINTS_PER_VERIFIER_SESSION)
    ]

    (service, _, _, _, _, create, generate, session) = _service(
        solver_row=solver,
        verifier_row=verifier,
        prior_hint_rows=priors,
        prior_count=MAX_HINTS_PER_VERIFIER_SESSION,
    )

    with pytest.raises(HintLimitExceededError):
        await service.generate_and_persist(session, uuid.uuid4())

    generate.assert_not_awaited()
    create.assert_not_awaited()
    session.commit.assert_not_called()


# ---------------------------------------------------------------------------
# 13. Malformed persisted test_results raises DataIntegrityError
# ---------------------------------------------------------------------------
async def test_malformed_persisted_test_results_raises_data_integrity_error() -> None:
    solver = _solver_row()
    verifier = _verifier_row(
        solver.id,
        test_results=[{"wrong_key": "missing input/passed fields"}],
    )

    (service, _, _, _, _, create, generate, session) = _service(
        solver_row=solver, verifier_row=verifier
    )

    with pytest.raises(DataIntegrityError):
        await service.generate_and_persist(session, uuid.uuid4())

    generate.assert_not_awaited()
    create.assert_not_awaited()


# ---------------------------------------------------------------------------
# 14. First hint seeds prior_hints with diagnosis
# ---------------------------------------------------------------------------
async def test_first_hint_seeds_prior_hints_with_diagnosis() -> None:
    solver = _solver_row()
    verifier = _verifier_row(solver.id, diagnosis="Your function ignores the input.")

    (service, _, _, _, _, _, generate, session) = _service(
        solver_row=solver,
        verifier_row=verifier,
        prior_hint_rows=[],
        prior_count=0,
    )

    await service.generate_and_persist(session, uuid.uuid4())

    hint_input: HintInput = generate.await_args.args[0]
    assert hint_input.prior_hints == ["Your function ignores the input."]


# ---------------------------------------------------------------------------
# 15. First hint with no diagnosis → no seeding (empty prior_hints list)
# ---------------------------------------------------------------------------
async def test_first_hint_no_diagnosis_no_seeding() -> None:
    solver = _solver_row()
    verifier = _verifier_row(solver.id, diagnosis="")

    (service, _, _, _, _, _, generate, session) = _service(
        solver_row=solver,
        verifier_row=verifier,
        prior_hint_rows=[],
        prior_count=0,
    )

    await service.generate_and_persist(session, uuid.uuid4())

    hint_input: HintInput = generate.await_args.args[0]
    assert hint_input.prior_hints == []


# ---------------------------------------------------------------------------
# 16. hint_index uses DB count, not seeded prior count
# ---------------------------------------------------------------------------
async def test_hint_index_uses_db_count_not_seeded_prior_count() -> None:
    """First hint with diagnosis seeded: prior_hints_count=1 (LLM saw diagnosis),
    but hint_index=1 (no real hint rows yet)."""
    solver = _solver_row()
    verifier = _verifier_row(solver.id, diagnosis="Your function returns 0.")

    (service, _, _, _, _, create, _, session) = _service(
        solver_row=solver,
        verifier_row=verifier,
        prior_hint_rows=[],
        prior_count=0,
    )

    await service.generate_and_persist(session, uuid.uuid4())

    kwargs = create.await_args.kwargs
    assert kwargs["hint_index"] == 1
    assert kwargs["prior_hints_count"] == 1


# ---------------------------------------------------------------------------
# 17. Service-layer regeneration on forbidden phrase or input-value leak.
#     Step 6.2 Phase 7 surfaced live RAG drift (~33% rate) producing forbidden
#     phrases like "apply to each element". The unified guardrail in
#     _find_violations triggers exactly one regeneration if either an input
#     value or a forbidden phrase appears. If the second attempt is still
#     dirty, the service ships the hint anyway and logs an error.
# ---------------------------------------------------------------------------
async def test_hint_service_regenerates_on_forbidden_phrase(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """First attempt leaks 'apply to each element' (forbidden); retry is clean.

    Asserts:
    - agent.generate called exactly twice
    - Persisted hint_text is the clean retry version
    - Warning log captures the violation detail
    """
    import logging

    dirty_hint = HintOutput(
        hint_text="What single arithmetic operation can you apply to each element?"
    )
    clean_hint = HintOutput(hint_text="What relationship should the output have to the input list?")

    (service, _, _, _, _, create, generate, session) = _service(
        agent_output=dirty_hint,
    )
    # Override agent.generate to return dirty then clean across two awaits.
    generate.side_effect = [dirty_hint, clean_hint]
    generate.return_value = None  # ensure side_effect drives the values

    with caplog.at_level(logging.WARNING, logger="app.services.hint_service"):
        await service.generate_and_persist(session, uuid.uuid4())

    assert generate.await_count == 2, "regeneration retry should fire exactly once"

    persisted_hint_text = create.await_args.kwargs["hint_text"]
    assert persisted_hint_text == clean_hint.hint_text

    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert any("violations detected (attempt 1)" in r.message for r in warnings), (
        f"expected violation warning; got: {[r.message for r in warnings]}"
    )
    assert any("apply to each element" in r.getMessage() for r in warnings), (
        "violation log should name the forbidden phrase"
    )


async def test_hint_service_ships_anyway_when_retry_also_violates(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Both attempts dirty: log error and persist the second attempt anyway.

    Better to ship a borderline hint than 500 the user.
    """
    import logging

    first = HintOutput(hint_text="Iterate through the list and accumulate.")
    second = HintOutput(hint_text="Loop over the list to build up the total.")

    (service, _, _, _, _, create, generate, session) = _service(agent_output=first)
    generate.side_effect = [first, second]
    generate.return_value = None

    with caplog.at_level(logging.ERROR, logger="app.services.hint_service"):
        await service.generate_and_persist(session, uuid.uuid4())

    assert generate.await_count == 2
    persisted_hint_text = create.await_args.kwargs["hint_text"]
    assert persisted_hint_text == second.hint_text

    errors = [r for r in caplog.records if r.levelno == logging.ERROR]
    assert any("Shipping anyway" in r.message for r in errors), (
        f"expected ship-anyway error; got: {[r.message for r in errors]}"
    )


async def test_hint_service_no_retry_when_clean() -> None:
    """Clean first attempt → no regeneration, exactly 1 LLM call."""
    clean = HintOutput(hint_text="What does the word 'sum' mean for a list of numbers?")

    (service, _, _, _, _, _, generate, session) = _service(agent_output=clean)

    await service.generate_and_persist(session, uuid.uuid4())

    assert generate.await_count == 1, "clean hint should not trigger retry"


async def test_hint_service_propagates_solver_topics_into_hint_input() -> None:
    """solver_row.topics must reach the HintAgent so per-topic anti-leak
    constraints fire. Without this plumbing the Day 2 prompt machinery
    silently no-ops in production."""
    solver = _solver_row()
    solver.topics = ["recursion", "tree"]
    verifier = _verifier_row(solver.id)

    (service, _, _, _, _, _, generate, session) = _service(
        solver_row=solver, verifier_row=verifier
    )

    await service.generate_and_persist(session, verifier.id)

    hint_input = generate.await_args.args[0]
    assert isinstance(hint_input, HintInput)
    assert hint_input.topics == ["recursion", "tree"]


async def test_hint_service_defaults_to_empty_topics_when_solver_topics_none() -> None:
    """Legacy solver_sessions rows (predating the column) hydrate topics=None
    via SQLAlchemy; the service must coerce to [] so HintInput validation
    succeeds and no per-topic constraint section is injected."""
    solver = _solver_row()
    solver.topics = None  # legacy row shape
    verifier = _verifier_row(solver.id)

    (service, _, _, _, _, _, generate, session) = _service(
        solver_row=solver, verifier_row=verifier
    )

    await service.generate_and_persist(session, verifier.id)

    hint_input = generate.await_args.args[0]
    assert hint_input.topics == []
