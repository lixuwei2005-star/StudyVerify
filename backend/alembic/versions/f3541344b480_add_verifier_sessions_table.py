"""add verifier_sessions table

Revision ID: f3541344b480
Revises: b1703d20c94b
Create Date: 2026-04-30

Fresh-table migration — no backfill needed (table starts empty).

Schema notes:
- FK solver_session_id ON DELETE RESTRICT: cannot delete a solver_session
  while any verifier_session references it (protects student history).
- status CHECK constraint enforces the SandboxStatus literal at the DB level
  as defense in depth against direct SQL writes that bypass the ORM.
- 3 indexes: solver_session_id (list queries), created_at (ordering),
  verified (analytics queries on pass/fail rates).
- diagnosis has server_default='' so rows never hold NULL for an LLM text
  field; empty string is the canonical "no diagnosis yet" value.
- pass_count / fail_count default to 0 server-side.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "f3541344b480"
down_revision: Union[str, Sequence[str], None] = "b1703d20c94b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "verifier_sessions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("solver_session_id", sa.Uuid(), nullable=False),
        sa.Column("student_code", sa.Text(), nullable=False),
        sa.Column("verified", sa.Boolean(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("pass_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("fail_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column(
            "test_results",
            postgresql.JSONB(astext_type=sa.Text()).with_variant(sa.JSON(), "sqlite"),
            nullable=False,
        ),
        sa.Column("diagnosis", sa.Text(), server_default=sa.text("''"), nullable=False),
        sa.Column("sandbox_error", sa.Text(), nullable=True),
        sa.Column("total_latency_ms", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["solver_session_id"],
            ["solver_sessions.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_verifier_sessions")),
    )

    op.create_index(
        "ix_verifier_sessions_solver_session_id",
        "verifier_sessions",
        ["solver_session_id"],
        unique=False,
    )
    op.create_index(
        "ix_verifier_sessions_created_at",
        "verifier_sessions",
        ["created_at"],
        unique=False,
    )
    op.create_index(
        "ix_verifier_sessions_verified",
        "verifier_sessions",
        ["verified"],
        unique=False,
    )

    op.create_check_constraint(
        "status_valid",
        "verifier_sessions",
        "status IN ('all_passed', 'some_failed', 'error', 'timeout')",
    )


def downgrade() -> None:
    op.drop_constraint(
        op.f("ck_verifier_sessions_status_valid"),
        "verifier_sessions",
        type_="check",
    )
    op.drop_table("verifier_sessions")
