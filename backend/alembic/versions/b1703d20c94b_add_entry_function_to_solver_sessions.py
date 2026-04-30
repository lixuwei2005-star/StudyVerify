"""add entry_function to solver_sessions

Revision ID: b1703d20c94b
Revises: d3bd309a15f6
Create Date: 2026-04-30

3-stage populated-table migration:
  Stage 1 - add nullable column so the table is never locked without data.
  Stage 2 - backfill each existing row's entry_function from its code column,
            using the same shared extract_entry_function helper used at runtime.
            Rows that fail extraction are skipped with a warning; they are NOT
            updated and will remain NULL.
  Stage 3 - if ALL rows were backfilled (null_count == 0), enforce NOT NULL.
            If any rows remain NULL, the constraint is NOT added; the migration
            succeeds but logs a warning identifying the affected rows. Manual
            fixup is required before the NOT NULL constraint can be applied.
"""

from __future__ import annotations

import logging
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

from app.agents.solver.extraction import (
    EntryFunctionExtractionError,
    extract_entry_function,
)

revision: str = "b1703d20c94b"
down_revision: Union[str, Sequence[str], None] = "d3bd309a15f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

logger = logging.getLogger("alembic.entry_function_backfill")


def upgrade() -> None:
    # Stage 1: add nullable column
    op.add_column(
        "solver_sessions",
        sa.Column("entry_function", sa.String(length=128), nullable=True),
    )

    # Stage 2: backfill from existing code column
    bind = op.get_bind()
    rows = list(
        bind.execute(
            sa.text("SELECT id, problem_id, code FROM solver_sessions")
        ).mappings()
    )

    failed_ids = []
    for row in rows:
        try:
            entry_fn = extract_entry_function(row["code"], row["problem_id"])
        except EntryFunctionExtractionError as exc:
            logger.warning(
                "entry_function backfill skipped id=%s problem_id=%s error=%s",
                row["id"],
                row["problem_id"],
                exc,
            )
            failed_ids.append(str(row["id"]))
            continue

        bind.execute(
            sa.text(
                "UPDATE solver_sessions SET entry_function = :entry_function WHERE id = :id"
            ).bindparams(entry_function=entry_fn, id=row["id"])
        )

    if failed_ids:
        logger.warning(
            "entry_function backfill failed for %d row(s): %s — "
            "manual fixup required before NOT NULL can be enforced",
            len(failed_ids),
            ", ".join(failed_ids),
        )

    # Stage 3: conditionally enforce NOT NULL
    null_count = bind.execute(
        sa.text("SELECT count(*) FROM solver_sessions WHERE entry_function IS NULL")
    ).scalar_one()

    if null_count == 0:
        op.alter_column(
            "solver_sessions",
            "entry_function",
            existing_type=sa.String(length=128),
            nullable=False,
        )
    else:
        logger.warning(
            "entry_function remains NULL for %d solver_sessions row(s); "
            "NOT NULL constraint NOT enforced — manual fixup required",
            null_count,
        )


def downgrade() -> None:
    op.drop_column("solver_sessions", "entry_function")
