"""Tier-1 cross-problem retrieval-quality tests (Step 6.3).

Seeds a deterministic 30-row mini-corpus into the per-test PG schema:
10 py-001-sum-list rows clustered near centroid A,
10 py-005-factorial rows clustered near centroid B,
10 py-006-is-palindrome rows clustered near centroid C.

By default, embeddings are synthetic (deterministic, no external service).
Set RAG_REAL_EMBEDDINGS=1 to use real OpenAI text-embedding-3-small calls
(requires OPENAI_API_KEY); useful as a sanity check that synthetic centroids
are not overly favorable.

These tests assert by `RetrievedFailure.problem_id`, never by diagnosis text.
Diagnoses are model-generated and not stable labels; problem_id is stable.
"""

# Buggy-variant code strings below are intentional long fixtures; allowing E501
# for this file keeps each variant on one line so the bug is readable at a glance.
# ruff: noqa: E501

from __future__ import annotations

import os
import uuid
from collections.abc import AsyncIterator
from decimal import Decimal

import numpy as np
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import SolverSession, VerifierSession
from app.services.retrieval_service import RetrievalService

EMBEDDING_DIM = 1536
ROWS_PER_CLUSTER = 10
# Per-element noise scalar. In d=1536, a noise vector with i.i.d. N(0, sigma^2)
# entries has expected norm sigma * sqrt(d) ~= 39.2 * sigma. Within-cluster
# cosine similarity to the unit centroid is ~ 1/sqrt(1 + (sigma*sqrt(d))^2).
# 0.005 -> noise norm ~ 0.196 -> within-cluster similarity ~ 0.98, comfortably
# above min_similarity=0.7 while cross-cluster stays near 0. Earlier 0.05 was
# too large (similarity collapsed to ~0.45) and produced empty retrievals.
NOISE_SCALAR = 0.005
SYNTHETIC_RNG_SEED = 42

CLUSTER_PROBLEMS = (
    ("py-001-sum-list", "Sum a list of integers."),
    ("py-005-factorial", "Compute factorial(n)."),
    ("py-006-is-palindrome", "Check if string is palindrome."),
)

# Real-embedding mode: build failure_text via the production
# `build_failure_text` shape (problem_text + student_code + diagnosis +
# failed_inputs). This matches how production rows in the dev corpus are
# embedded, so the within-cluster similarity reaches the production
# min_similarity=0.7 threshold. Short isolated descriptions don't.
SUM_LIST_PROBLEM = (
    "Write a Python function `sum_list(nums)` that returns the sum of all "
    "integers in the input list. If the list is empty, return 0."
)
FACTORIAL_PROBLEM = (
    "Write a Python function `factorial(n)` that returns n! (the factorial "
    "of n). For n = 0, return 1. Assume n is a non-negative integer."
)
PALINDROME_PROBLEM = (
    "Write a Python function `is_palindrome(s)` that returns True if the "
    "input string reads the same forward and backward, False otherwise. "
    "Treat the empty string as a palindrome."
)

SUM_LIST_VARIANTS = [
    (
        "def sum_list(nums):\n    return 0\n",
        "Returns 0 instead of summing list elements; accumulator never updates.",
    ),
    (
        "def sum_list(nums):\n    total = 0\n    for n in nums[1:]:\n        total += n\n    return total\n",
        "Off-by-one: skips the first list element when summing integers.",
    ),
    (
        "def sum_list(nums):\n    return sum(nums) + 1\n",
        "Returns sum incremented by 1; wrong base case for the accumulator.",
    ),
    (
        "def sum_list(nums):\n    return len(nums)\n",
        "Adds list length instead of summing the integer element values.",
    ),
    (
        "def sum_list(nums):\n    return max(nums)\n",
        "Returns the maximum element instead of the sum of integers.",
    ),
    (
        "def sum_list(nums):\n    total = 0\n    for n in nums:\n        total = n\n    return total\n",
        "Assigns instead of adding; the accumulator stores only the last element.",
    ),
    (
        "def sum_list(nums):\n    total = 0\n    for n in nums:\n        total += n\n",
        "Sum is computed in the loop but the function returns None implicitly.",
    ),
    (
        "def sum_list(nums):\n    if not nums:\n        return None\n    return sum(nums)\n",
        "Empty-list case returns None instead of 0 for integer-list sum.",
    ),
    (
        "def sum_list(nums):\n    total = 1\n    for n in nums:\n        total *= n\n    return total\n",
        "Multiplies elements together instead of summing them in the integer list.",
    ),
    (
        "def sum_list(nums):\n    return sum(n for n in nums if n > 0)\n",
        "Sums only positive integers; ignores negative values in the input list.",
    ),
]

FACTORIAL_VARIANTS = [
    (
        "def factorial(n):\n    result = 1\n    for i in range(1, n):\n        result *= i\n    return result\n",
        "Off-by-one: loop excludes n so factorial(5) returns 24 not 120.",
    ),
    (
        "def factorial(n):\n    if n == 0:\n        return 0\n    result = 1\n    for i in range(2, n + 1):\n        result *= i\n    return result\n",
        "Returns 0 for n=0 instead of 1; wrong factorial base case.",
    ),
    (
        "def factorial(n):\n    result = 1\n    for i in range(2, n + 1):\n        result += i\n    return result\n",
        "Uses addition instead of multiplication when accumulating factorial product.",
    ),
    (
        "def factorial(n):\n    result = 1\n    for i in range(2, n + 1):\n        pass\n    return result\n",
        "Forgets to update accumulator inside loop; factorial always returns 1.",
    ),
    (
        "def factorial(n):\n    result = 1\n    for i in range(2, n + 1):\n        result *= i\n    return i\n",
        "Returns the loop variable i instead of the accumulated factorial product.",
    ),
    (
        "def factorial(n):\n    result = 1\n    for i in range(0, n + 1):\n        result *= i\n    return result\n",
        "Includes 0 in the factorial product; factorial of any positive n becomes 0.",
    ),
    (
        "def factorial(n):\n    return n * factorial(n - 1)\n",
        "Recursive factorial without base case; infinite recursion for any n.",
    ),
    (
        "def factorial(n):\n    return n\n",
        "Returns n itself for factorial; never enters the multiplication loop.",
    ),
    (
        "def factorial(n):\n    if n <= 1:\n        return 1\n    return n + factorial(n - 1)\n",
        "Computes n + factorial(n-1) instead of n * factorial(n-1).",
    ),
    (
        "def factorial(n):\n    result = 0\n    for i in range(2, n + 1):\n        result *= i\n    return result\n",
        "Initializes accumulator to 0 instead of 1; factorial always zero.",
    ),
]

PALINDROME_VARIANTS = [
    (
        "def is_palindrome(s):\n    return s == s\n",
        "Compares string to itself instead of to its reverse; always True.",
    ),
    (
        "def is_palindrome(s):\n    return s != s[::-1]\n",
        "Returns True for non-palindromes; reversed comparison operator.",
    ),
    (
        "def is_palindrome(s):\n    if not s:\n        return False\n    return s == s[::-1]\n",
        "Empty palindrome string returns False; wrong base case for empty input.",
    ),
    (
        "def is_palindrome(s):\n    for i in range(len(s) // 2):\n        if s[i] != s[len(s) - i]:\n            return False\n    return True\n",
        "Index error in palindrome two-pointer; uses len(s) instead of len(s)-1-i.",
    ),
    (
        "def is_palindrome(s):\n    for i in range(len(s)):\n        if s[i] != s[-i]:\n            return False\n    return True\n",
        "Off-by-one in palindrome two-pointer indexing skips middle character.",
    ),
    (
        "def is_palindrome(s):\n    return s == s[::-1].lower()\n",
        "Case-sensitive palindrome check fails for mixed-case palindrome strings.",
    ),
    (
        "def is_palindrome(s):\n    return s is s[::-1]\n",
        "Returns False for any palindrome because comparison uses 'is' not '=='.",
    ),
    (
        "def is_palindrome(s):\n    s = s.replace(' ', '')\n    return s == s[::-1]\n",
        "Strips spaces inside the palindrome check producing wrong results.",
    ),
    (
        "def is_palindrome(s):\n    return True\n",
        "Returns True regardless of input; palindrome compare branch always taken.",
    ),
    (
        "def is_palindrome(s):\n    half = s[:len(s) // 2]\n    return half == half[::-1]\n",
        "Reverses only half of the string for palindrome check; off-by-one slicing.",
    ),
]

CLUSTER_DATA = (
    (SUM_LIST_PROBLEM, SUM_LIST_VARIANTS),
    (FACTORIAL_PROBLEM, FACTORIAL_VARIANTS),
    (PALINDROME_PROBLEM, PALINDROME_VARIANTS),
)

QUERY_DESCRIPTORS = (
    (
        SUM_LIST_PROBLEM,
        SUM_LIST_VARIANTS[0][0],
        "Returns 0 for non-empty list; sum accumulator missing the in-loop update.",
    ),
    (
        FACTORIAL_PROBLEM,
        FACTORIAL_VARIANTS[0][0],
        "Off-by-one upper bound in factorial loop; result misses the final factor.",
    ),
    (
        PALINDROME_PROBLEM,
        PALINDROME_VARIANTS[1][0],
        "Palindrome equality comparison reversed; True for non-palindrome strings.",
    ),
)


def _normalize(v: np.ndarray) -> np.ndarray:
    n = np.linalg.norm(v)
    return v / n if n > 0 else v


def _synthetic_corpus() -> tuple[list[list[float]], list[list[float]]]:
    """Returns (cluster_row_embeddings_flat[30], query_embeddings[3]).

    cluster_row_embeddings_flat: 30 vectors, ordered cluster-A 0..9, cluster-B
    10..19, cluster-C 20..29.
    """
    rng = np.random.default_rng(SYNTHETIC_RNG_SEED)
    centroids = [_normalize(rng.standard_normal(EMBEDDING_DIM)) for _ in range(3)]
    rows: list[list[float]] = []
    for c in centroids:
        for _ in range(ROWS_PER_CLUSTER):
            v = _normalize(c + NOISE_SCALAR * rng.standard_normal(EMBEDDING_DIM))
            rows.append(v.tolist())
    queries = [c.tolist() for c in centroids]
    return rows, queries


def _real_corpus() -> tuple[list[list[float]], list[list[float]]]:
    """Real OpenAI embeddings. Caller must have OPENAI_API_KEY set.

    Each row is built via the production `build_failure_text` shape (problem +
    code + diagnosis), matching the real dev corpus. Short isolated text would
    not reach min_similarity=0.7 within-cluster.
    """
    from app.core.config import get_settings
    from app.llm.embedding import build_failure_text, sync_embed_one

    settings = get_settings()
    rows: list[list[float]] = []
    for problem_text, variants in CLUSTER_DATA:
        for code, diagnosis in variants:
            failure_text = build_failure_text(
                problem_text=problem_text,
                student_code=code,
                diagnosis=diagnosis,
            )
            rows.append(sync_embed_one(failure_text, settings))
    queries: list[list[float]] = []
    for problem_text, code, diagnosis in QUERY_DESCRIPTORS:
        query_text = build_failure_text(
            problem_text=problem_text,
            student_code=code,
            diagnosis=diagnosis,
        )
        queries.append(sync_embed_one(query_text, settings))
    return rows, queries


@pytest_asyncio.fixture
async def seed_test_corpus(
    pg_session: AsyncSession,
) -> AsyncIterator[dict[str, list[float]]]:
    """Seeds 30 deterministic rows into pg_session and yields query embeddings.

    Default: synthetic centroids (no external service). Set RAG_REAL_EMBEDDINGS=1
    to embed canonical failure-text strings via OpenAI; CI must NOT depend on
    OpenAI credentials, so the default is synthetic-only.
    """
    use_real = os.environ.get("RAG_REAL_EMBEDDINGS") == "1"
    if use_real:
        from app.core.config import get_settings

        if not get_settings().OPENAI_API_KEY:
            pytest.skip("RAG_REAL_EMBEDDINGS=1 set but OPENAI_API_KEY missing")
        row_embeddings, query_embeddings = _real_corpus()
    else:
        row_embeddings, query_embeddings = _synthetic_corpus()

    # One solver row per problem cluster; 10 verifier rows attached to it. The
    # retrieval SQL joins solver_sessions to read problem_id, so the solver row
    # must exist with the correct problem_id for assertions to work.
    for cluster_idx, (problem_id, problem_text) in enumerate(CLUSTER_PROBLEMS):
        solver = SolverSession(
            id=uuid.uuid4(),
            problem_id=problem_id,
            problem_text=problem_text,
            entry_function="f",
            test_cases=[],
            analysis="test fixture",
            plan_steps=[],
            code="def f(): pass",
            explanation="test fixture",
            verified=True,
            test_results=[],
            confidence=Decimal("0.90"),
            retry_used=False,
            total_latency_ms=0,
        )
        pg_session.add(solver)
        await pg_session.flush()
        for j in range(ROWS_PER_CLUSTER):
            row_idx = cluster_idx * ROWS_PER_CLUSTER + j
            pg_session.add(
                VerifierSession(
                    id=uuid.uuid4(),
                    solver_session_id=solver.id,
                    student_code=f"def f(): return {row_idx}",
                    verified=False,
                    status="some_failed",
                    pass_count=0,
                    fail_count=1,
                    test_results=[],
                    diagnosis=f"{problem_id} synthetic diagnosis #{j}",
                    sandbox_error=None,
                    total_latency_ms=0,
                    failure_embedding=row_embeddings[row_idx],
                    embedding_status="success",
                )
            )
    await pg_session.commit()

    yield {
        "sum_list_query": query_embeddings[0],
        "factorial_query": query_embeddings[1],
        "palindrome_query": query_embeddings[2],
    }


# ---------------------------------------------------------------------------
# Tier-1 retrieval quality tests
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_sum_list_query_retrieves_majority_sum_list(
    pg_session: AsyncSession,
    seed_test_corpus: dict[str, list[float]],
) -> None:
    """At top_k=5, a sum_list query should return majority sum_list rows.

    Some cross-problem retrieval is acceptable; most should match.
    """
    service = RetrievalService()
    results = await service.find_similar_failures(
        pg_session,
        query_embedding=seed_test_corpus["sum_list_query"],
        top_k=5,
        min_similarity=0.7,
    )
    same = sum(1 for r in results if r.problem_id == "py-001-sum-list")
    assert same >= 3, (
        f"Expected at least 3 of {len(results)} retrievals to be sum_list; "
        f"got {same}. problem_ids={[r.problem_id for r in results]}"
    )


@pytest.mark.integration
async def test_factorial_query_isolates_to_scalar_problems(
    pg_session: AsyncSession,
    seed_test_corpus: dict[str, list[float]],
) -> None:
    """A factorial query should not surface mostly sum_list rows.

    Tier-1 fixture seeds factorial as the only scalar cluster, so the concrete
    assertion is >= 3 factorial in top 5 and <= 1 sum_list.
    """
    service = RetrievalService()
    results = await service.find_similar_failures(
        pg_session,
        query_embedding=seed_test_corpus["factorial_query"],
        top_k=5,
        min_similarity=0.7,
    )
    factorial = sum(1 for r in results if r.problem_id == "py-005-factorial")
    sum_list = sum(1 for r in results if r.problem_id == "py-001-sum-list")
    assert factorial >= 3, (
        f"Expected at least 3 of {len(results)} to be factorial; got {factorial}. "
        f"problem_ids={[r.problem_id for r in results]}"
    )
    assert sum_list <= 1, (
        f"Expected at most 1 sum_list pollution; got {sum_list}. "
        f"problem_ids={[r.problem_id for r in results]}"
    )


@pytest.mark.integration
async def test_palindrome_query_isolates_to_string_problems(
    pg_session: AsyncSession,
    seed_test_corpus: dict[str, list[float]],
) -> None:
    """A palindrome query should isolate to string-shaped problems.

    Tier-1 fixture seeds palindrome as the only string cluster, so the concrete
    assertion is >= 3 palindrome in top 5 and <= 1 sum_list.
    """
    service = RetrievalService()
    results = await service.find_similar_failures(
        pg_session,
        query_embedding=seed_test_corpus["palindrome_query"],
        top_k=5,
        min_similarity=0.7,
    )
    palindrome = sum(1 for r in results if r.problem_id == "py-006-is-palindrome")
    sum_list = sum(1 for r in results if r.problem_id == "py-001-sum-list")
    assert palindrome >= 3, (
        f"Expected at least 3 of {len(results)} to be palindrome; got {palindrome}. "
        f"problem_ids={[r.problem_id for r in results]}"
    )
    assert sum_list <= 1, (
        f"Expected at most 1 sum_list pollution; got {sum_list}. "
        f"problem_ids={[r.problem_id for r in results]}"
    )
