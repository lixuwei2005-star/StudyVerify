from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class HintRequest(BaseModel):
    """API input. Service queries prior hints itself; client doesn't pass them
    — single source of truth is the DB. Extra fields are ignored (Pydantic
    default), so client-supplied prior_hints would be silently dropped.
    """

    verifier_session_id: UUID


class HintResponse(BaseModel):
    """API output for POST /api/v1/hint."""

    session_id: UUID
    hint_index: int
    hint_text: str


class HintSessionOut(BaseModel):
    """Persistent record representation for GET endpoints."""

    model_config = {"from_attributes": True}

    id: UUID
    verifier_session_id: UUID
    hint_index: int
    hint_text: str
    prior_hints_count: int
    total_latency_ms: int
    created_at: datetime


class HintSessionListResponse(BaseModel):
    items: list[HintSessionOut]
    total: int
