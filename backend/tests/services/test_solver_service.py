"""Unit tests for SolverService — orchestration only, no real DB or LLM.

Both the SolverAgent and the SolverRepository are mocked so we can assert
exact call ordering, kwarg shape, and the commit/no-commit invariants.
The session is a MagicMock(spec=AsyncSession); we only assert that the
service called .commit() / .refresh() the right number of times.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.solver.agent import SolverAgent
from app.agents.solver.schemas import (
    PlanStep,
    SolverInput,
    SolverOutput,
    TestCase,
)
from app.db.models import SolverSession
from app.repositories.solver_repository import SolverRepository
from app.sandbox.schemas import TestExecutionResult
from app.services.solver_service import SolverService


def _input() -> SolverInput:
    return SolverInput(
        problem_id="py-001-sum-list",
        problem_text="Write sum_list(nums) returning the sum, or 0 if empty.",
        entry_function="sum_list",
        test_cases=[
            TestCase(input="[1,2,3]", expected="6", description="basic"),
            TestCase(input="[]", expected="0", description="empty"),
        ],
    )


def _output(retry_used: bool = False) -> SolverOutput:
    return SolverOutput(
        problem_id="py-001-sum-list",
        entry_function="sum_list",
        analysis="restate",
        plan_steps=[PlanStep(step_number=1, action="a", rationale="r")],
        code="def sum_list(nums):\n    return sum(nums)\n",
        explanation="builtin",
        confidence=0.9,
        verified=True,
        test_results=[
            TestExecutionResult(
                test_index=0,
                input="[1,2,3]",
                expected="6",
                actual="6",
                passed=True,
                error=None,
                duration_ms=1,
            )
        ],
        retry_used=retry_used,
    )


def _service(
    output: SolverOutput | None = None,
    agent_exc: Exception | None = None,
    repo_exc: Exception | None = None,
) -> tuple[SolverService, AsyncMock, AsyncMock, MagicMock]:
    agent = AsyncMock(spec=SolverAgent)
    if agent_exc is not None:
        agent.solve = AsyncMock(side_effect=agent_exc)
    else:
        agent.solve = AsyncMock(return_value=output or _output())

    repo = AsyncMock(spec=SolverRepository)
    if repo_exc is not None:
        repo.create = AsyncMock(side_effect=repo_exc)
    else:
        row = SolverSession(
            id=uuid.uuid4(),
            problem_id="py-001-sum-list",
            problem_text="-",
            entry_function="sum_list",
            test_cases=[],
            analysis="-",
            plan_steps=[],
            code="-",
            explanation="-",
            verified=True,
            test_results=[],
            confidence=0.9,
            retry_used=output.retry_used if output else False,
            total_latency_ms=0,
        )
        repo.create = AsyncMock(return_value=row)

    session = MagicMock(spec=AsyncSession)
    session.commit = AsyncMock()
    session.refresh = AsyncMock()
    session.rollback = AsyncMock()

    return SolverService(agent=agent, repository=repo), agent.solve, repo.create, session


# ---------- happy-path orchestration ----------


async def test_solve_and_persist_calls_agent_then_repo_then_commit_then_refresh():
    service, solve, create, session = _service(_output(retry_used=False))

    parent = MagicMock()
    parent.attach_mock(solve, "solve")
    parent.attach_mock(create, "create")
    parent.attach_mock(session.commit, "commit")
    parent.attach_mock(session.refresh, "refresh")

    row, output = await service.solve_and_persist(session, _input())

    # Order: agent.solve → repo.create → session.commit → session.refresh
    method_names = [c[0] for c in parent.mock_calls]
    assert method_names == ["solve", "create", "commit", "refresh"]
    assert isinstance(output, SolverOutput)
    assert row.problem_id == "py-001-sum-list"


async def test_solve_and_persist_passes_total_latency_ms_to_repository():
    service, _, create, session = _service(_output())

    await service.solve_and_persist(session, _input())

    kwargs = create.await_args.kwargs
    assert kwargs["total_latency_ms"] >= 0
    # Sanity: a no-op mocked agent returns instantly, so a sane upper bound
    # catches obvious unit-conversion bugs (seconds vs ms).
    assert kwargs["total_latency_ms"] < 5000


async def test_solve_and_persist_propagates_retry_used_to_repository():
    service_t, _, create_t, session_t = _service(_output(retry_used=True))
    service_f, _, create_f, session_f = _service(_output(retry_used=False))

    await service_t.solve_and_persist(session_t, _input())
    await service_f.solve_and_persist(session_f, _input())

    assert create_t.await_args.kwargs["retry_used"] is True
    assert create_f.await_args.kwargs["retry_used"] is False


async def test_solve_and_persist_propagates_topics_to_repository():
    """Topics arrive on SolverInput from the API and must reach the repository's
    create() so they're persisted on solver_sessions. The Hint Agent later
    reads solver_row.topics to inject per-topic anti-leak constraints."""
    service, _, create, session = _service(_output())

    input_with_topics = SolverInput(
        problem_id="py-001-sum-list",
        problem_text="Return the sum of a list.",
        entry_function="sum_list",
        test_cases=[TestCase(input="[]", expected="0", description="empty")],
        topics=["recursion", "two-pointers"],
    )
    await service.solve_and_persist(session, input_with_topics)

    kwargs = create.await_args.kwargs
    assert kwargs["topics"] == ["recursion", "two-pointers"]


async def test_solve_and_persist_defaults_topics_to_empty_list():
    """Existing callers that don't supply topics keep working: SolverInput's
    default_factory=list produces [], which reaches the repo unchanged."""
    service, _, create, session = _service(_output())

    await service.solve_and_persist(session, _input())  # no topics in helper

    assert create.await_args.kwargs["topics"] == []


async def test_solve_and_persist_serializes_pydantic_nested_fields():
    """SolverInput.test_cases (TestCase), SolverOutput.plan_steps (PlanStep),
    and SolverOutput.test_results (TestExecutionResult) must arrive at the
    repo as plain dicts so the JSONB columns store JSON-shaped data."""
    service, _, create, session = _service(_output())

    await service.solve_and_persist(session, _input())

    kwargs = create.await_args.kwargs
    assert isinstance(kwargs["test_cases"], list)
    assert all(isinstance(tc, dict) for tc in kwargs["test_cases"])
    assert isinstance(kwargs["plan_steps"], list)
    assert all(isinstance(ps, dict) for ps in kwargs["plan_steps"])
    assert isinstance(kwargs["test_results"], list)
    assert all(isinstance(tr, dict) for tr in kwargs["test_results"])


# ---------- error paths: no commit ----------


async def test_solve_and_persist_does_not_commit_when_agent_raises():
    sentinel = RuntimeError("agent boom")
    service, _, create, session = _service(agent_exc=sentinel)

    with pytest.raises(RuntimeError, match="agent boom"):
        await service.solve_and_persist(session, _input())

    create.assert_not_awaited()
    session.commit.assert_not_called()
    session.refresh.assert_not_called()


async def test_solve_and_persist_does_not_commit_when_repository_raises():
    sentinel = RuntimeError("repo boom")
    service, solve, create, session = _service(_output(), repo_exc=sentinel)

    with pytest.raises(RuntimeError, match="repo boom"):
        await service.solve_and_persist(session, _input())

    solve.assert_awaited_once()
    create.assert_awaited_once()
    session.commit.assert_not_called()
    session.refresh.assert_not_called()
