"""add topics column to solver_sessions

Revision ID: a91b4f2c7e08
Revises: de9421cbca21
Create Date: 2026-05-12

Step 11 Day 2.5 — structural-only. Adds a nullable JSONB ``topics`` column
to ``solver_sessions`` with a server default of ``'[]'`` so existing rows
hydrate as an empty list without an explicit backfill UPDATE pass. The
hint prompt's per-topic anti-leak constraint section (Step 11 Day 2) is
gated on this column being populated; legacy rows simply receive no
constraint injection (default ``[]``).
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision: str = "a91b4f2c7e08"
down_revision: Union[str, Sequence[str], None] = "de9421cbca21"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Nullable + server_default='[]' so the column add is a metadata-only
    # operation on Postgres (no table rewrite) and existing rows return [].
    op.add_column(
        "solver_sessions",
        sa.Column(
            "topics",
            JSONB(),
            nullable=True,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )


def downgrade() -> None:
    op.drop_column("solver_sessions", "topics")
