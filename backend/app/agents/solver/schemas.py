from pydantic import BaseModel, Field

from app.sandbox.schemas import TestExecutionResult


class TestCase(BaseModel):
    __test__ = False  # not a pytest collection target despite the name

    input: str
    expected: str
    description: str


class SolverInput(BaseModel):
    problem_id: str
    problem_text: str
    entry_function: str = Field(description="Exact Python function name students must implement")
    test_cases: list[TestCase]


class PlanStep(BaseModel):
    step_number: int
    action: str
    rationale: str


class SolverOutput(BaseModel):
    problem_id: str
    entry_function: str = Field(description="Python function name students must implement")
    analysis: str = Field(description="Restatement of what's being asked")
    plan_steps: list[PlanStep]
    code: str = Field(description="Final Python code, function signature included")
    explanation: str = Field(description="Plain-language explanation of the solution")
    confidence: float = Field(ge=0.0, le=1.0)
    verified: bool = Field(
        description="True iff generated code passed all sandbox-executed test cases"
    )
    test_results: list[TestExecutionResult] = Field(default_factory=list)
    retry_used: bool = Field(
        default=False,
        description="True iff the code-generation step was retried due to sandbox failure",
    )
