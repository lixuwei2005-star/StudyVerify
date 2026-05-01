from __future__ import annotations

from pydantic import BaseModel, Field


class HintInput(BaseModel):
    """Stateless input. Service composes from persisted verifier_session + queried prior hints."""

    problem_text: str
    student_code: str = Field(
        description="Latest version of student code at time of verification failure"
    )
    failed_test_inputs: list[str] = Field(
        description="Inputs of tests that failed; used for context without revealing expected outputs"
    )
    prior_hints: list[str] = Field(
        default_factory=list,
        description="Hints already shown to the student in this verifier_session, oldest first. "
        "May include the verifier's one-shot diagnosis as a seeded entry on the first hint request.",
    )


class HintOutput(BaseModel):
    hint_text: str = Field(
        description="The next progressive hint, one notch more specific than the last in prior_hints"
    )
