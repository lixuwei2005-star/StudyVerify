from datetime import datetime
from uuid import UUID

from pydantic import BaseModel

from app.agents.solver.schemas import PlanStep, SolverOutput, TestCase
from app.sandbox.schemas import TestExecutionResult


class SolverSessionOut(BaseModel):
    """API representation of a SolverSession DB row.

    `from_attributes=True` lets FastAPI build this from the SQLAlchemy ORM
    object directly. The JSONB-shaped fields (test_cases, plan_steps,
    test_results) come out of the DB as plain dicts; Pydantic v2 validates
    them into the proper nested schemas, restoring OpenAPI typing instead
    of leaking `dict`.
    """

    model_config = {"from_attributes": True}

    id: UUID
    problem_id: str
    problem_text: str
    test_cases: list[TestCase]
    analysis: str
    plan_steps: list[PlanStep]
    code: str
    explanation: str
    verified: bool
    test_results: list[TestExecutionResult]
    confidence: float  # Decimal(3,2) on the DB; float is precise enough for [0,1]
    retry_used: bool
    total_latency_ms: int
    created_at: datetime


class SolveResponse(BaseModel):
    """Response shape for POST /api/v1/solve."""

    session_id: UUID
    output: SolverOutput


class SessionListResponse(BaseModel):
    items: list[SolverSessionOut]
    total: int
    limit: int
    offset: int
