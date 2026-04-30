from datetime import datetime
from uuid import UUID

from pydantic import BaseModel

from app.agents.verifier.schemas import RedactedTestResult, VerifierOutput
from app.sandbox.schemas import SandboxStatus


class VerifyRequest(BaseModel):
    """API input — references an existing solver_session by ID.

    The client never supplies entry_function, problem_text, or test_cases;
    those are loaded from the persisted solver row to prevent client drift.
    """

    solver_session_id: UUID
    student_code: str


class VerifyResponse(BaseModel):
    """API output for POST /api/v1/verify."""

    session_id: UUID
    output: VerifierOutput


class VerifierSessionOut(BaseModel):
    """Persistent record representation for GET endpoints."""

    model_config = {"from_attributes": True}

    id: UUID
    solver_session_id: UUID
    student_code: str
    verified: bool
    status: SandboxStatus
    pass_count: int
    fail_count: int
    test_results: list[RedactedTestResult]
    diagnosis: str
    sandbox_error: str | None
    total_latency_ms: int
    created_at: datetime


class VerifierSessionListResponse(BaseModel):
    items: list[VerifierSessionOut]
    total: int
    limit: int
    offset: int
