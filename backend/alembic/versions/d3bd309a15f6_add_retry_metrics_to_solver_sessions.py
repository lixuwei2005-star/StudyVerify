"""add retry metrics to solver_sessions

Revision ID: d3bd309a15f6
Revises: 0b3015bfb3f1
Create Date: 2026-04-28 01:53:18.839001

Adds two non-null columns to solver_sessions:

    - retry_used        BOOLEAN NOT NULL  DEFAULT FALSE
    - total_latency_ms  INTEGER NOT NULL  (no DB default)

Why a 3-stage backfill for `total_latency_ms`:
    Adding a NOT NULL column without a default to a populated table
    fails immediately because Postgres has no value to put in the
    existing rows. Even though `solver_sessions` is currently empty
    in this project, this migration is written as if it were not —
    industry-standard discipline. The 3-stage pattern is:
        1. add column as NULLABLE
        2. UPDATE to backfill (zero is a sentinel for "pre-metric"
           rows; new code never inserts NULL anyway)
        3. ALTER COLUMN ... SET NOT NULL
    With this shape the migration is safe whether the table holds
    0 rows or 50M.

Why `retry_used` does NOT need 3-stage:
    It carries `server_default=FALSE`. Postgres applies the default
    to all existing rows during `ADD COLUMN`, so the single-shot
    `nullable=False` form is safe.

Why `total_latency_ms` has NO server_default in the ORM model:
    The Service layer is the single source of truth for end-to-end
    latency (it owns the `time.perf_counter()` measurement around
    `agent.solve()` + the DB write). A DB-level default would mask
    bugs where the Service forgot to compute and pass the value.
    The 3-stage UPDATE here is a one-time migration-time backfill
    for any pre-existing rows, NOT a runtime default for new inserts.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d3bd309a15f6"
down_revision: Union[str, Sequence[str], None] = "0b3015bfb3f1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # retry_used: server_default=FALSE means Postgres backfills existing rows
    # automatically during ADD COLUMN, so a single-shot NOT NULL is safe.
    op.add_column(
        "solver_sessions",
        sa.Column(
            "retry_used",
            sa.Boolean(),
            server_default=sa.false(),
            nullable=False,
        ),
    )

    # total_latency_ms: 3-stage backfill (see module docstring).
    op.add_column(
        "solver_sessions",
        sa.Column("total_latency_ms", sa.Integer(), nullable=True),
    )
    op.execute(
        "UPDATE solver_sessions SET total_latency_ms = 0 "
        "WHERE total_latency_ms IS NULL"
    )
    op.alter_column("solver_sessions", "total_latency_ms", nullable=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("solver_sessions", "total_latency_ms")
    op.drop_column("solver_sessions", "retry_used")
