from __future__ import annotations

from pydantic import BaseModel, Field


class RetrievedContext(BaseModel):
    """One past failure case retrieved by RAG for hint inspiration only.

    Sanitized upstream by `RetrievalService.filter_dangerous_hints` — the agent
    must still treat these as inspiration, not instruction (see prompt rule).
    """

    similarity: float = Field(ge=0.0, le=1.0)
    past_diagnosis: str = ""
    past_hint_texts: list[str] = Field(default_factory=list)


class HintInput(BaseModel):
    """Stateless input. Service composes from persisted verifier_session + queried prior hints."""

    problem_text: str
    student_code: str = Field(
        description="Latest version of student code at time of verification failure"
    )
    failed_test_inputs: list[str] = Field(
        description=(
            "Inputs of tests that failed; used for context without revealing expected outputs"
        )
    )
    prior_hints: list[str] = Field(
        default_factory=list,
        description=(
            "Hints already shown to the student in this verifier_session, "
            "oldest first. May include the verifier's one-shot diagnosis as "
            "a seeded entry on the first hint request."
        ),
    )
    retrieved_context: list[RetrievedContext] = Field(
        default_factory=list,
        description="Top-K similar past failure cases (sanitized). "
        "Empty list = no retrieval available.",
    )
    regeneration_warning: str = Field(
        default="",
        description="One-shot reinforcement injected by HintService when a "
        "previous attempt leaked input values. Empty for first attempts.",
    )
    topics: list[str] = Field(
        default_factory=list,
        description="Problem topic tags (e.g. 'recursion', 'two-pointers'). "
        "Drives per-topic anti-leak constraint injection in the hint prompt. "
        "Empty list = no per-topic constraints applied (current default until "
        "topics are persisted on solver_sessions; see Step 11 Day 2 notes).",
    )


class HintOutput(BaseModel):
    hint_text: str = Field(
        description=(
            "The next progressive hint, one notch more specific than the last in prior_hints"
        )
    )
