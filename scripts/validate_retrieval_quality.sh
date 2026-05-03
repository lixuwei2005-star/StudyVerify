#!/usr/bin/env bash
# Tier-2 manual retrieval-quality validation against the dev DB (Step 6.3).
#
# Runs three canonical queries (sum-list, factorial, palindrome failures)
# through the same find_similar_failures SQL the production retrieval uses,
# and prints top-5 results per query for human visual review. NOT in CI.
#
# Prerequisites:
#   - compose stack up (studyverify-postgres healthy)
#   - dev DB seeded by `seed_failure_corpus.py` (>= 50 success rows expected)
#   - OPENAI_API_KEY set in backend/.env (used to embed query texts)
#
# Run from repo root:
#   bash scripts/validate_retrieval_quality.sh

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT/backend"

uv run python - <<'PYEOF'
import asyncio
import sys

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.core.config import get_settings
from app.llm.embedding import build_failure_text, sync_embed_one
from app.services.retrieval_service import RetrievalService


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
    "input string reads the same forward and backward, False otherwise."
)

QUERIES = [
    ("sum-list failure", SUM_LIST_PROBLEM,
     "def sum_list(nums):\n    return 0\n",
     "Returns 0 for non-empty list; sum accumulator missing the in-loop update."),
    ("factorial failure", FACTORIAL_PROBLEM,
     "def factorial(n):\n    result = 1\n    for i in range(1, n):\n        result *= i\n    return result\n",
     "Off-by-one upper bound in factorial loop; result misses the final factor."),
    ("palindrome failure", PALINDROME_PROBLEM,
     "def is_palindrome(s):\n    return s != s[::-1]\n",
     "Palindrome equality comparison reversed; True for non-palindrome strings."),
]


async def main() -> int:
    settings = get_settings()
    if not settings.OPENAI_API_KEY:
        print("ERROR: OPENAI_API_KEY missing; cannot embed query texts.", file=sys.stderr)
        return 1
    if not settings.DATABASE_URL:
        print("ERROR: DATABASE_URL missing.", file=sys.stderr)
        return 1

    engine = create_async_engine(settings.DATABASE_URL)
    try:
        async with AsyncSession(engine, expire_on_commit=False) as session:
            n = (await session.execute(text(
                "SELECT count(*) FROM verifier_sessions "
                "WHERE embedding_status='success' AND verified=false"
            ))).scalar()
            print(f"Corpus size: {n} rows (verified=false, embedding_status='success')")
            if n is None or n < 50:
                print(
                    f"WARN: corpus has {n} rows, expected >= 50. "
                    "Run seed_failure_corpus.py first.",
                    file=sys.stderr,
                )
                return 1

            service = RetrievalService()
            for label, problem_text, code, diagnosis in QUERIES:
                query_text = build_failure_text(
                    problem_text=problem_text,
                    student_code=code,
                    diagnosis=diagnosis,
                )
                emb = sync_embed_one(query_text, settings)
                results = await service.find_similar_failures(
                    session,
                    query_embedding=emb,
                    top_k=5,
                    min_similarity=0.7,
                )
                print()
                print(f"QUERY: {label}")
                if not results:
                    print("  (no results above min_similarity=0.7)")
                    continue
                print(f"  {'sim':>6}  {'problem_id':22s}  verifier_id   diagnosis")
                for r in results:
                    diag = (r.diagnosis or "").replace("\n", " ")[:80]
                    print(
                        f"  {r.similarity:6.3f}  {r.problem_id:22s}  "
                        f"{str(r.verifier_session_id)[:8]}...  {diag}"
                    )
        return 0
    finally:
        await engine.dispose()


sys.exit(asyncio.run(main()))
PYEOF
