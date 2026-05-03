"""add verifier failure embedding

Revision ID: de9421cbca21
Revises: 02dbc0b244cb
Create Date: 2026-05-03 17:56:24.253054

Step 6.2 — structural-only. No row backfill, no OpenAI imports, no network
calls. Compose API startup runs `alembic upgrade head` without OPENAI_API_KEY,
so this migration must succeed in that environment. Embedding generation for
existing rows is performed by `app.scripts.backfill_embeddings` (separate CLI).
"""
from typing import Sequence, Union

import sqlalchemy as sa
from pgvector.sqlalchemy import Vector

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "de9421cbca21"
down_revision: Union[str, Sequence[str], None] = "02dbc0b244cb"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.add_column(
        "verifier_sessions",
        sa.Column(
            "failure_embedding",
            Vector(1536),
            nullable=True,
        ),
    )
    op.add_column(
        "verifier_sessions",
        sa.Column(
            "embedding_status",
            sa.String(length=16),
            nullable=False,
            server_default=sa.text("'pending'"),
        ),
    )
    op.create_check_constraint(
        "embedding_status_valid",
        "verifier_sessions",
        "embedding_status IN ('pending', 'success', 'failed')",
    )


def downgrade() -> None:
    op.drop_constraint(
        "embedding_status_valid",
        "verifier_sessions",
        type_="check",
    )
    op.drop_column("verifier_sessions", "embedding_status")
    op.drop_column("verifier_sessions", "failure_embedding")
    # Intentionally do not DROP EXTENSION vector. Future tables may reuse it.
