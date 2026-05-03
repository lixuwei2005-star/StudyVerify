"""Backfill failure_embedding for prior failed verifier_sessions (Step 6.2).

Separate from Alembic so structural deploys never depend on OPENAI_API_KEY.
Idempotent: re-running with no flags processes only embedding_status='pending'
rows. Use --retry-failed to also re-attempt rows in 'failed' state.

Per-row commit pattern: a crash mid-run leaves processed rows at 'success'
and the rest at 'pending', so resume is just `python -m app.scripts.backfill_embeddings`.

Run:
    cd backend && uv run python -m app.scripts.backfill_embeddings
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.core.config import get_settings
from app.llm.embedding import build_failure_text, sync_embed_one
from app.repositories.verifier_repository import VerifierRepository

logger = logging.getLogger(__name__)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m app.scripts.backfill_embeddings",
        description="Backfill failure_embedding for failed verifier_sessions.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Maximum rows to process this run (default: no limit).",
    )
    parser.add_argument(
        "--retry-failed",
        action="store_true",
        help="Also process rows with embedding_status='failed' (default: skip).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Count rows that would be processed; make no API or DB write calls.",
    )
    return parser


_SELECT_PENDING = """
    SELECT
        v.id,
        v.student_code,
        v.test_results,
        v.diagnosis,
        v.sandbox_error,
        s.problem_text
    FROM verifier_sessions v
    JOIN solver_sessions s ON s.id = v.solver_session_id
    WHERE v.verified = false
      AND v.failure_embedding IS NULL
      AND v.embedding_status = ANY(:statuses)
    ORDER BY v.created_at ASC
"""


async def _run(args: argparse.Namespace) -> int:
    settings = get_settings()
    if not settings.OPENAI_API_KEY and not args.dry_run:
        print("ERROR: OPENAI_API_KEY is not set. Set it in env before running.", file=sys.stderr)
        return 1
    if not settings.DATABASE_URL:
        print("ERROR: DATABASE_URL is not set.", file=sys.stderr)
        return 1

    statuses: list[str] = ["pending"]
    if args.retry_failed:
        statuses.append("failed")

    sql = _SELECT_PENDING
    if args.limit is not None:
        sql = sql + "\n    LIMIT :limit"

    repo = VerifierRepository()
    engine = create_async_engine(settings.DATABASE_URL)
    try:
        async with AsyncSession(engine, expire_on_commit=False) as session:
            params: dict[str, object] = {"statuses": statuses}
            if args.limit is not None:
                params["limit"] = args.limit
            result = await session.execute(text(sql), params)
            rows = list(result.mappings())

            print(
                f"Found {len(rows)} rows to embed "
                f"(filter: embedding_status in {statuses}"
                f"{', limit=' + str(args.limit) if args.limit is not None else ''})."
            )

            if args.dry_run:
                print("--dry-run: no API calls, no DB writes.")
                return 0

            scanned = embedded = failed = 0
            for row in rows:
                scanned += 1
                vid: UUID = row["id"]
                try:
                    failure_text = build_failure_text(
                        problem_text=row["problem_text"] or "",
                        student_code=row["student_code"] or "",
                        test_results=list(row["test_results"] or []),
                        diagnosis=row["diagnosis"] or "",
                        sandbox_error=row["sandbox_error"],
                    )
                    embedding = sync_embed_one(failure_text, settings)
                    await repo.update_embedding(
                        session,
                        verifier_session_id=vid,
                        failure_embedding=embedding,
                        embedding_status="success",
                    )
                    await session.commit()
                    embedded += 1
                    print(f"  {vid} -> success")
                except Exception as exc:
                    await session.rollback()
                    try:
                        await repo.update_embedding(
                            session,
                            verifier_session_id=vid,
                            failure_embedding=None,
                            embedding_status="failed",
                        )
                        await session.commit()
                    except Exception as inner_exc:
                        await session.rollback()
                        logger.warning(
                            "Could not mark verifier_session %s failed: %s", vid, inner_exc
                        )
                    failed += 1
                    print(f"  {vid} -> failed: {exc}")

            print(f"\nSummary: scanned={scanned} embedded={embedded} skipped=0 failed={failed}")
            return 0
    finally:
        await engine.dispose()


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    args = _build_parser().parse_args(argv)
    return asyncio.run(_run(args))


if __name__ == "__main__":
    raise SystemExit(main())
