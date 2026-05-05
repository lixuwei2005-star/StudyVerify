"""Pydantic schema for the StudyVerify evaluation benchmark.

A BenchmarkProblem bundles a reference solution with student-style buggy
variants. The variant.expected_failure_count is the number of test cases
the variant should fail when executed in the sandbox — used by the eval
loop to assert "verifier saw the right number of failures" without
requiring an exact diff. error_pattern is a short label that lets us
report metrics by bug class (e.g. accuracy on off-by-one bugs).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

Difficulty = Literal["easy", "medium", "hard"]


class TestCaseDict(BaseModel):
    input: str
    expected: str
    description: str = ""


class Variant(BaseModel):
    name: str = Field(min_length=1)
    code: str = Field(min_length=1)
    expected_failure_count: int = Field(ge=0)
    error_pattern: str = Field(min_length=1)


class BenchmarkProblem(BaseModel):
    id: str = Field(pattern=r"^[a-z0-9-]+$")
    title: str = Field(min_length=1)
    problem_text: str = Field(min_length=20)
    entry_function: str = Field(pattern=r"^[a-z_][a-z0-9_]*$")
    reference_solution: str = Field(min_length=1)
    test_cases: list[TestCaseDict] = Field(min_length=1)
    difficulty: Difficulty
    topics: list[str] = Field(min_length=1)
    variants: list[Variant] = Field(min_length=1)


class BenchmarkDataset(BaseModel):
    version: str
    generated_at: str
    problems: list[BenchmarkProblem]
