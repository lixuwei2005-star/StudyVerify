from typing import Literal

from pydantic import BaseModel, Field


class SandboxRunRequest(BaseModel):
    code: str
    entry_function: str
    test_cases: list[dict]
    timeout_seconds: int = 5
    memory_mb: int = 128


class TestExecutionResult(BaseModel):
    __test__ = False  # not a pytest collection target

    test_index: int
    input: str
    expected: str
    actual: str | None = None
    passed: bool
    error: str | None = None
    duration_ms: int


SandboxStatus = Literal["all_passed", "some_failed", "error", "timeout"]


class SandboxRunResult(BaseModel):
    status: SandboxStatus
    test_results: list[TestExecutionResult] = Field(default_factory=list)
    pass_count: int = 0
    fail_count: int = 0
    error: str | None = None
