"""Tests for RetrievalService and filter_dangerous_hints (Step 6.2).

Unit tests cover the pure-function filter (no DB). PG-marked tests cover
find_similar_failures against a real corpus seeded into the per-test schema.
The pg_session fixture (tests/conftest.py) installs `vector` before
Base.metadata.create_all so Vector(1536) columns exist.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import HintSession, SolverSession, VerifierSession
from app.services.retrieval_service import (
    FORBIDDEN_HINT_PHRASES,
    MAX_RETRIEVED_HINT_CHARS,
    RetrievalService,
    RetrievedFailure,
    filter_dangerous_hints,
)

# ---------------------------------------------------------------------------
# Unit: filter_dangerous_hints (pure function, no DB)
# ---------------------------------------------------------------------------


def _failure(
    hints: list[str], similarity: float = 0.9, problem_id: str = "py-001-sum-list"
) -> RetrievedFailure:
    return RetrievedFailure(
        verifier_session_id=uuid.uuid4(),
        similarity=similarity,
        diagnosis="diag",
        hint_texts=hints,
        problem_id=problem_id,
    )


def test_filter_dangerous_hints_preserves_problem_id() -> None:
    case = _failure(["loop through"], problem_id="py-005-factorial")
    [out] = filter_dangerous_hints([case])
    assert out.problem_id == "py-005-factorial"


def test_filter_dangerous_hints_removes_forbidden_phrases() -> None:
    cases = [
        _failure(["What does sum mean?"]),
        _failure(["Loop through the list and accumulate"]),
        _failure(["Good question", "Create a variable to store..."]),
        _failure(["ITERATE THROUGH the list"]),  # case-insensitive
    ]
    result = filter_dangerous_hints(cases)

    assert result[0].hint_texts == ["What does sum mean?"]
    assert result[1].hint_texts == []  # all dropped, case kept
    assert result[2].hint_texts == ["Good question"]
    assert result[3].hint_texts == []
    assert len(result) == 4  # all RetrievedFailures preserved


def test_filter_dangerous_hints_keeps_case_with_empty_hints() -> None:
    """A retrieved case is preserved even if filtering empties hint_texts;
    the diagnosis alone is still useful inspiration."""
    case = _failure(["loop through", "iterate through"], similarity=0.85)
    [out] = filter_dangerous_hints([case])
    assert out.verifier_session_id == case.verifier_session_id
    assert out.similarity == 0.85
    assert out.diagnosis == "diag"
    assert out.hint_texts == []


def test_filter_dangerous_hints_caps_hint_text_at_max_chars() -> None:
    long_hint = "Conceptual question. " + ("padding " * 200)
    [out] = filter_dangerous_hints([_failure([long_hint])])
    assert len(out.hint_texts[0]) <= MAX_RETRIEVED_HINT_CHARS
    assert out.hint_texts[0].endswith("...")


def test_forbidden_phrases_count_is_33() -> None:
    """Lock the count so future contributors notice if list shrinks."""
    assert len(FORBIDDEN_HINT_PHRASES) == 33


# ---------------------------------------------------------------------------
# PG integration: find_similar_failures over a seeded corpus
# ---------------------------------------------------------------------------

# Each row uses a distinct deterministic 1536-d unit vector so we can score
# similarity precisely. e_i is the i-th basis vector. cos(e_i, e_j) = 0 for
# i != j and 1 for i == j; query against e_0 returns row 0 with similarity=1.
_DIM = 1536


def _basis_vector(idx: int) -> list[float]:
    v = [0.0] * _DIM
    v[idx] = 1.0
    return v


def _solver_seed(problem_text: str = "Sum a list.") -> SolverSession:
    return SolverSession(
        id=uuid.uuid4(),
        problem_id="py-001-sum-list",
        problem_text=problem_text,
        entry_function="sum_list",
        test_cases=[{"input": "[1]", "expected": "1", "description": "basic"}],
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


def _verifier_seed(
    *,
    solver_id: uuid.UUID,
    embedding: list[float] | None,
    embedding_status: str = "success",
    verified: bool = False,
    diagnosis: str = "stub diagnosis",
) -> VerifierSession:
    return VerifierSession(
        id=uuid.uuid4(),
        solver_session_id=solver_id,
        student_code="def sum_list(nums): return 0",
        verified=verified,
        status="some_failed" if not verified else "all_passed",
        pass_count=0 if not verified else 1,
        fail_count=1 if not verified else 0,
        test_results=[
            {"input": "[1]", "actual": "0", "passed": False, "duration_ms": 1, "error": None}
        ],
        diagnosis=diagnosis,
        sandbox_error=None,
        total_latency_ms=42,
        failure_embedding=embedding,
        embedding_status=embedding_status,
    )


@pytest.mark.integration
async def test_top_k_limit_respected(pg_session: AsyncSession) -> None:
    solver = _solver_seed()
    pg_session.add(solver)
    await pg_session.flush()
    # 5 rows all ~similar to query (basis vector 0); top_k=2 should return 2.
    for i in range(5):
        pg_session.add(_verifier_seed(solver_id=solver.id, embedding=_basis_vector(0)))
    await pg_session.commit()

    svc = RetrievalService()
    results = await svc.find_similar_failures(
        pg_session,
        query_embedding=_basis_vector(0),
        top_k=2,
        min_similarity=0.5,
    )
    assert len(results) == 2


@pytest.mark.integration
async def test_min_similarity_filter_excludes_low_similarity(pg_session: AsyncSession) -> None:
    solver = _solver_seed()
    pg_session.add(solver)
    await pg_session.flush()
    pg_session.add(_verifier_seed(solver_id=solver.id, embedding=_basis_vector(0)))  # sim=1.0
    pg_session.add(_verifier_seed(solver_id=solver.id, embedding=_basis_vector(5)))  # sim=0.0
    await pg_session.commit()

    svc = RetrievalService()
    results = await svc.find_similar_failures(
        pg_session,
        query_embedding=_basis_vector(0),
        top_k=5,
        min_similarity=0.5,
    )
    assert len(results) == 1
    assert results[0].similarity > 0.99


@pytest.mark.integration
async def test_exclude_verifier_session_id_excludes_self(pg_session: AsyncSession) -> None:
    solver = _solver_seed()
    pg_session.add(solver)
    await pg_session.flush()
    self_row = _verifier_seed(solver_id=solver.id, embedding=_basis_vector(0))
    other = _verifier_seed(solver_id=solver.id, embedding=_basis_vector(0))
    pg_session.add_all([self_row, other])
    await pg_session.commit()

    svc = RetrievalService()
    results = await svc.find_similar_failures(
        pg_session,
        query_embedding=_basis_vector(0),
        exclude_verifier_session_id=self_row.id,
        top_k=5,
        min_similarity=0.5,
    )
    ids = {r.verifier_session_id for r in results}
    assert self_row.id not in ids
    assert other.id in ids


@pytest.mark.integration
async def test_retrieval_zero_hints_returns_empty_array(pg_session: AsyncSession) -> None:
    """LEFT JOIN + COALESCE keeps a row with no hint_sessions; hint_texts=[]."""
    solver = _solver_seed()
    pg_session.add(solver)
    await pg_session.flush()
    pg_session.add(_verifier_seed(solver_id=solver.id, embedding=_basis_vector(0)))
    await pg_session.commit()

    svc = RetrievalService()
    results = await svc.find_similar_failures(
        pg_session,
        query_embedding=_basis_vector(0),
        top_k=1,
        min_similarity=0.5,
    )
    assert len(results) == 1
    assert results[0].hint_texts == []


@pytest.mark.integration
async def test_retrieval_excludes_failed_status_rows(pg_session: AsyncSession) -> None:
    solver = _solver_seed()
    pg_session.add(solver)
    await pg_session.flush()
    success_row = _verifier_seed(solver_id=solver.id, embedding=_basis_vector(0))
    failed_row = _verifier_seed(solver_id=solver.id, embedding=None, embedding_status="failed")
    pg_session.add_all([success_row, failed_row])
    await pg_session.commit()

    svc = RetrievalService()
    results = await svc.find_similar_failures(
        pg_session,
        query_embedding=_basis_vector(0),
        top_k=5,
        min_similarity=0.5,
    )
    ids = {r.verifier_session_id for r in results}
    assert success_row.id in ids
    assert failed_row.id not in ids


@pytest.mark.integration
async def test_retrieval_excludes_pending_status_rows(pg_session: AsyncSession) -> None:
    solver = _solver_seed()
    pg_session.add(solver)
    await pg_session.flush()
    success_row = _verifier_seed(solver_id=solver.id, embedding=_basis_vector(0))
    pending_row = _verifier_seed(solver_id=solver.id, embedding=None, embedding_status="pending")
    pg_session.add_all([success_row, pending_row])
    await pg_session.commit()

    svc = RetrievalService()
    results = await svc.find_similar_failures(
        pg_session,
        query_embedding=_basis_vector(0),
        top_k=5,
        min_similarity=0.5,
    )
    ids = {r.verifier_session_id for r in results}
    assert success_row.id in ids
    assert pending_row.id not in ids


@pytest.mark.integration
async def test_hint_texts_ordered_by_hint_index(pg_session: AsyncSession) -> None:
    solver = _solver_seed()
    pg_session.add(solver)
    await pg_session.flush()
    v = _verifier_seed(solver_id=solver.id, embedding=_basis_vector(0))
    pg_session.add(v)
    await pg_session.flush()
    # Insert hints out-of-order; query should return them sorted by hint_index.
    pg_session.add_all(
        [
            HintSession(
                id=uuid.uuid4(),
                verifier_session_id=v.id,
                hint_index=2,
                hint_text="What relationship matters here?",
                prior_hints_count=1,
                total_latency_ms=10,
            ),
            HintSession(
                id=uuid.uuid4(),
                verifier_session_id=v.id,
                hint_index=1,
                hint_text="What does the spec require?",
                prior_hints_count=0,
                total_latency_ms=10,
            ),
        ]
    )
    await pg_session.commit()

    svc = RetrievalService()
    results = await svc.find_similar_failures(
        pg_session,
        query_embedding=_basis_vector(0),
        top_k=1,
        min_similarity=0.5,
    )
    assert len(results) == 1
    assert results[0].hint_texts == [
        "What does the spec require?",
        "What relationship matters here?",
    ]


@pytest.mark.integration
async def test_retrieval_filters_dangerous_hints_from_persisted_corpus(
    pg_session: AsyncSession,
) -> None:
    solver = _solver_seed()
    pg_session.add(solver)
    await pg_session.flush()
    v = _verifier_seed(solver_id=solver.id, embedding=_basis_vector(0))
    pg_session.add(v)
    await pg_session.flush()
    pg_session.add(
        HintSession(
            id=uuid.uuid4(),
            verifier_session_id=v.id,
            hint_index=1,
            hint_text="Loop through the list and accumulate the total",  # forbidden
            prior_hints_count=0,
            total_latency_ms=10,
        )
    )
    await pg_session.commit()

    svc = RetrievalService()
    [out] = await svc.find_similar_failures(
        pg_session,
        query_embedding=_basis_vector(0),
        top_k=1,
        min_similarity=0.5,
    )
    assert out.hint_texts == []  # filtered, but case retained
