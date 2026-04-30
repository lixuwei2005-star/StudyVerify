import uuid
from datetime import datetime
from decimal import Decimal

import sqlalchemy as sa
from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, Numeric, String, Text, Uuid, false, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON

from app.db.base import Base

# JSONB on Postgres, JSON on SQLite — same Python interface.
JSONType = JSONB().with_variant(JSON(), "sqlite")


class SolverSession(Base):
    __tablename__ = "solver_sessions"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True, native_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    problem_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    problem_text: Mapped[str] = mapped_column(Text, nullable=False)
    test_cases: Mapped[list] = mapped_column(JSONType, nullable=False)

    analysis: Mapped[str] = mapped_column(Text, nullable=False)
    plan_steps: Mapped[list] = mapped_column(JSONType, nullable=False)
    code: Mapped[str] = mapped_column(Text, nullable=False)
    explanation: Mapped[str] = mapped_column(Text, nullable=False)

    verified: Mapped[bool] = mapped_column(Boolean, nullable=False, index=True)
    test_results: Mapped[list] = mapped_column(JSONType, nullable=False)
    confidence: Mapped[Decimal] = mapped_column(Numeric(3, 2), nullable=False)

    entry_function: Mapped[str] = mapped_column(String(128), nullable=False)

    retry_used: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=false(),
    )
    total_latency_ms: Mapped[int] = mapped_column(Integer, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        index=True,
    )

    def __repr__(self) -> str:
        return f"<SolverSession {self.id} {self.problem_id} verified={self.verified}>"


class VerifierSession(Base):
    __tablename__ = "verifier_sessions"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True, native_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    solver_session_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True, native_uuid=True),
        ForeignKey("solver_sessions.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    student_code: Mapped[str] = mapped_column(Text, nullable=False)
    verified: Mapped[bool] = mapped_column(Boolean, nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    pass_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=sa.text("0")
    )
    fail_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=sa.text("0")
    )
    test_results: Mapped[list] = mapped_column(JSONType, nullable=False)
    diagnosis: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=sa.text("''")
    )
    sandbox_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    total_latency_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        index=True,
    )

    def __repr__(self) -> str:
        return f"<VerifierSession {self.id} solver={self.solver_session_id} verified={self.verified}>"
