"""Drive /solve -> /verify against the local compose stack to seed the
failed-verifier corpus with embeddings (Step 6.3).

Default behavior is seed-missing-only, idempotent across reruns.
Destructive reseed requires both --delete-existing and --yes-dev-db,
refuses non-localhost DB URLs, prints a deletion plan first, and deletes
in FK order: hint_sessions -> verifier_sessions -> solver_sessions.

Run from backend/:
    uv run python -m app.scripts.seed_failure_corpus \\
      --variants tests/agents/fixtures/buggy_variants.json \\
      --api-base http://localhost:8000
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import logging
import sys
from pathlib import Path
from urllib.parse import urlparse

import httpx
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.core.config import get_settings

logger = logging.getLogger(__name__)

LOCALHOST_HOSTS = frozenset({"localhost", "127.0.0.1", "studyverify-postgres"})

FIXTURE_PROBLEMS_PATH = (
    Path(__file__).resolve().parent.parent.parent
    / "tests"
    / "agents"
    / "fixtures"
    / "sample_problems.json"
)

EXISTS_SQL = text(
    """
    SELECT 1
    FROM verifier_sessions v
    JOIN solver_sessions s ON v.solver_session_id = s.id
    WHERE s.problem_id = :problem_id
      AND v.student_code = :student_code
    LIMIT 1
    """
)

COUNT_SEEDED_SQL = text(
    """
    SELECT s.problem_id, count(v.*) AS n
    FROM verifier_sessions v
    JOIN solver_sessions s ON v.solver_session_id = s.id
    WHERE v.embedding_status = 'success'
      AND v.verified = false
      AND s.problem_id = ANY(:problem_ids)
    GROUP BY s.problem_id
    ORDER BY s.problem_id
    """
)

DELETION_PLAN_SQL = text(
    """
    SELECT
      (SELECT count(*) FROM hint_sessions h
        JOIN verifier_sessions v ON h.verifier_session_id = v.id
        JOIN solver_sessions s ON v.solver_session_id = s.id
        WHERE s.problem_id = ANY(:pids)) AS hints,
      (SELECT count(*) FROM verifier_sessions v
        JOIN solver_sessions s ON v.solver_session_id = s.id
        WHERE s.problem_id = ANY(:pids)) AS verifiers,
      (SELECT count(*) FROM solver_sessions
        WHERE problem_id = ANY(:pids)) AS solvers
    """
)

DELETE_HINTS_SQL = text(
    """
    DELETE FROM hint_sessions
    WHERE verifier_session_id IN (
      SELECT v.id FROM verifier_sessions v
      JOIN solver_sessions s ON v.solver_session_id = s.id
      WHERE s.problem_id = ANY(:pids)
    )
    """
)

DELETE_VERIFIERS_SQL = text(
    """
    DELETE FROM verifier_sessions
    WHERE solver_session_id IN (
      SELECT id FROM solver_sessions WHERE problem_id = ANY(:pids)
    )
    """
)

DELETE_SOLVERS_SQL = text(
    """
    DELETE FROM solver_sessions
    WHERE problem_id = ANY(:pids)
      AND id NOT IN (SELECT solver_session_id FROM verifier_sessions)
    """
)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m app.scripts.seed_failure_corpus",
        description="Seed failed verifier_sessions for the RAG corpus.",
    )
    parser.add_argument("--variants", required=True, help="Path to buggy_variants.json")
    parser.add_argument("--api-base", default="http://localhost:8000", help="FastAPI base URL")
    parser.add_argument(
        "--problem-filter",
        default=None,
        help="Only seed this problem_id (default: all problems in the variants file)",
    )
    parser.add_argument("--dry-run", action="store_true", help="No API or DB writes")
    parser.add_argument(
        "--delete-existing",
        action="store_true",
        help="Destructive reseed; requires --yes-dev-db and localhost DB",
    )
    parser.add_argument(
        "--yes-dev-db",
        action="store_true",
        help="Skip the confirmation prompt for --delete-existing",
    )
    return parser


def variant_hash(student_code: str) -> str:
    return hashlib.sha256(student_code.strip().encode("utf-8")).hexdigest()


def _flatten_variants(raw: dict, problem_filter: str | None) -> list[tuple[str, str, str]]:
    """Returns a flat list of (problem_id, category, student_code)."""
    out: list[tuple[str, str, str]] = []
    for pid, items in raw.items():
        if problem_filter and pid != problem_filter:
            continue
        for v in items:
            out.append((pid, v["category"], v["code"]))
    return out


def _problem_lookup() -> dict[str, dict]:
    return {p["problem_id"]: p for p in json.loads(FIXTURE_PROBLEMS_PATH.read_text())}


def _localhost_check_or_exit(database_url: str) -> None:
    host = urlparse(database_url).hostname
    if host not in LOCALHOST_HOSTS:
        print(
            f"REFUSED: --delete-existing requires localhost DB; got hostname={host!r} "
            f"in DATABASE_URL. Allowed: {sorted(LOCALHOST_HOSTS)}",
            file=sys.stderr,
        )
        sys.exit(1)


async def _print_deletion_plan(session: AsyncSession, pids: list[str]) -> None:
    row = (await session.execute(DELETION_PLAN_SQL, {"pids": pids})).one()
    print(
        f"Will delete: {row.hints} hint_sessions, {row.verifiers} verifier_sessions, "
        f"{row.solvers} solver_sessions across problems {pids}"
    )


async def _delete_in_fk_order(session: AsyncSession, pids: list[str]) -> None:
    await session.execute(DELETE_HINTS_SQL, {"pids": pids})
    await session.execute(DELETE_VERIFIERS_SQL, {"pids": pids})
    await session.execute(DELETE_SOLVERS_SQL, {"pids": pids})
    await session.commit()


async def _exists(session: AsyncSession, problem_id: str, student_code: str) -> bool:
    row = (
        await session.execute(EXISTS_SQL, {"problem_id": problem_id, "student_code": student_code})
    ).scalar_one_or_none()
    return row is not None


async def _seed_one(
    client: httpx.AsyncClient,
    *,
    api_base: str,
    problem: dict,
) -> tuple[str, dict]:
    """POST /solve, then return (solver_session_id, solver_response_json)."""
    payload = {
        "problem_id": problem["problem_id"],
        "problem_text": problem["problem_text"],
        "test_cases": problem["test_cases"],
    }
    r = await client.post(f"{api_base}/api/v1/solve", json=payload, timeout=120.0)
    r.raise_for_status()
    body = r.json()
    return body["session_id"], body


async def _verify_one(
    client: httpx.AsyncClient,
    *,
    api_base: str,
    solver_session_id: str,
    student_code: str,
) -> dict:
    payload = {"solver_session_id": solver_session_id, "student_code": student_code}
    r = await client.post(f"{api_base}/api/v1/verify", json=payload, timeout=60.0)
    r.raise_for_status()
    return r.json()


async def _run(args: argparse.Namespace) -> int:
    settings = get_settings()
    if not settings.DATABASE_URL:
        print("ERROR: DATABASE_URL is not set.", file=sys.stderr)
        return 1

    raw = json.loads(Path(args.variants).read_text())
    problems = _problem_lookup()
    flat = _flatten_variants(raw, args.problem_filter)
    if not flat:
        print(
            f"No variants to process (filter={args.problem_filter!r}).",
            file=sys.stderr,
        )
        return 1

    pids = sorted({pid for pid, _, _ in flat})
    print(f"Variants file: {args.variants} ({len(flat)} entries across {len(pids)} problems)")

    if args.dry_run:
        for pid, cat, code in flat:
            h = variant_hash(code)[:12]
            print(f"  WOULD-SEED pid={pid} hash={h} category={cat!r}")
        print(
            f"\n--dry-run: no API calls, no DB writes. "
            f"attempted={len(flat)} seeded=0 skipped=0 failed=0"
        )
        return 0

    engine = create_async_engine(settings.DATABASE_URL)
    try:
        if args.delete_existing:
            _localhost_check_or_exit(settings.DATABASE_URL)
            async with AsyncSession(engine, expire_on_commit=False) as s:
                await _print_deletion_plan(s, pids)
                if not args.yes_dev_db:
                    answer = input("Type 'yes' to continue: ").strip().lower()
                    if answer != "yes":
                        print("Aborted by user.", file=sys.stderr)
                        return 1
                await _delete_in_fk_order(s, pids)
                print("Deleted existing rows for target problems.")

        attempted = seeded = skipped = failed = accidental_pass = 0
        async with AsyncSession(engine, expire_on_commit=False) as session:
            async with httpx.AsyncClient() as client:
                for pid, cat, code in flat:
                    attempted += 1
                    h = variant_hash(code)[:12]
                    if await _exists(session, pid, code):
                        skipped += 1
                        print(f"  SKIP pid={pid} hash={h} (already seeded)")
                        continue
                    try:
                        solver_id, _ = await _seed_one(
                            client, api_base=args.api_base, problem=problems[pid]
                        )
                        verify_body = await _verify_one(
                            client,
                            api_base=args.api_base,
                            solver_session_id=solver_id,
                            student_code=code,
                        )
                        verified = bool(verify_body["output"]["verified"])
                        verifier_id = verify_body["session_id"]
                        if verified:
                            accidental_pass += 1
                            print(
                                f"  WARN pid={pid} hash={h} category={cat!r} "
                                f"verified=true (accidental_pass) verifier={verifier_id}"
                            )
                        else:
                            seeded += 1
                            print(
                                f"  SEED pid={pid} hash={h} category={cat!r} verifier={verifier_id}"
                            )
                    except Exception as exc:
                        failed += 1
                        print(f"  FAIL pid={pid} hash={h} category={cat!r}: {exc}")

            embedding_success = 0
            if pids:
                rows = list((await session.execute(COUNT_SEEDED_SQL, {"problem_ids": pids})).all())
                embedding_success = sum(int(r.n) for r in rows)
                print("\nPer-problem embedded rows (verified=false, success):")
                for r in rows:
                    print(f"  {r.problem_id}: {r.n}")

        print(
            f"\nSummary: attempted={attempted} seeded={seeded} skipped={skipped} "
            f"failed={failed} accidental_pass={accidental_pass} "
            f"embedding_success={embedding_success}"
        )
        return 0
    finally:
        await engine.dispose()


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    args = _build_parser().parse_args(argv)
    return asyncio.run(_run(args))


if __name__ == "__main__":
    raise SystemExit(main())
