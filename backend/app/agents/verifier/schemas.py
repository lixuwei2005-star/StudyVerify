"""Verifier Agent Pydantic schemas.

Two anti-leak invariants are enforced by the schema layer:

1. RedactedTestResult deliberately omits `expected`. Callers of the verifier
   API must never see the answer key. The raw sandbox row carries `expected`
   (it is needed inside the sandbox to compute pass/fail), so the verifier
   must convert sandbox rows to RedactedTestResult before returning them.

2. VerifierInput.test_cases is typed as list[TestCase] (Solver's model) so
   the verifier validates the same {input, expected, description} shape at
   its boundary. Step 4.3's persistence layer can round-trip JSONB through
   this type before dumping back to plain dicts for the sandbox.
"""

from pydantic import BaseModel, Field

from app.agents.solver.schemas import TestCase
from app.sandbox.schemas import SandboxStatus


class VerifierInput(BaseModel):
    """Stateless input. Step 4.3's service composes this from a persisted
    solver_session + caller-supplied student code."""

    problem_id: str
    problem_text: str
    entry_function: str = Field(
        description="The Python function name the student must implement; "
        "tests will call this function."
    )
    test_cases: list[TestCase] = Field(
        description="Same typed test case shape used by Solver: "
        "{input: str, expected: str, description: str}."
    )
    student_code: str


class RedactedTestResult(BaseModel):
    """Student-facing per-test result. Deliberately omits 'expected' so API
    responses cannot leak the answer key. Keep input visible (students saw
    it when running) and actual (their own output)."""

    __test__ = False  # not a pytest collection target despite the name

    input: str
    actual: str | None
    passed: bool
    duration_ms: int | None = None
    error: str | None = None


class VerifierOutput(BaseModel):
    problem_id: str

    # Outcome
    verified: bool = Field(description="True iff student code passed ALL test cases")
    status: SandboxStatus
    pass_count: int = Field(ge=0)
    fail_count: int = Field(ge=0)
    test_results: list[RedactedTestResult] = Field(default_factory=list)

    # LLM-generated or deterministic feedback
    diagnosis: str = Field(
        default="",
        description="Targeted diagnostic feedback for the student. "
        "Empty when verified=True or when sandbox status is error "
        "with no per-test signal.",
    )

    # Provenance
    sandbox_error: str | None = Field(
        default=None,
        description="If sandbox failed at infra/status level (timeout, OOM, "
        "syntax error preventing execution), the error string lives here. "
        "test_results may be empty.",
    )
