"""Schema enforcement for the benchmark dataset.

These tests run on the dataset file directly so any drift introduced when
adding new problems shows up at the schema layer before the slower
reference-solution validator stage. The validator stage (sandbox-running
each reference) lives in benchmark/validators.py and is run as a CLI
script, not as part of pytest.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from benchmark.schema import BenchmarkDataset, BenchmarkProblem, Variant

DATASET_PATH = Path(__file__).resolve().parents[2] / "benchmark" / "problems_part_1.json"


def _valid_problem_dict() -> dict:
    return {
        "id": "lc-001-two-sum",
        "title": "Two Sum",
        "problem_text": "Given an array, return indices of two numbers summing to target.",
        "entry_function": "two_sum",
        "reference_solution": "def two_sum(nums, target):\n    return [0, 1]\n",
        "test_cases": [
            {"input": "([1,2], 3)", "expected": "[0, 1]", "description": "basic"},
        ],
        "difficulty": "easy",
        "topics": ["array"],
        "variants": [
            {
                "name": "noop",
                "code": "def two_sum(nums, target):\n    return []\n",
                "expected_failure_count": 1,
                "error_pattern": "no-implementation",
            }
        ],
    }


# ---------- happy path ----------


def test_problem_validates() -> None:
    p = BenchmarkProblem.model_validate(_valid_problem_dict())
    assert p.id == "lc-001-two-sum"
    assert len(p.variants) == 1


def test_dataset_file_parses() -> None:
    raw = json.loads(DATASET_PATH.read_text())
    dataset = BenchmarkDataset.model_validate(raw)
    assert len(dataset.problems) == 30
    # Spot-check IDs are unique.
    ids = [p.id for p in dataset.problems]
    assert len(ids) == len(set(ids)), "duplicate problem IDs"


# ---------- schema enforcement ----------


def test_invalid_difficulty_rejected() -> None:
    bad = _valid_problem_dict() | {"difficulty": "trivial"}
    with pytest.raises(ValidationError):
        BenchmarkProblem.model_validate(bad)


def test_function_name_pattern_rejects_uppercase() -> None:
    bad = _valid_problem_dict() | {"entry_function": "TwoSum"}
    with pytest.raises(ValidationError) as exc:
        BenchmarkProblem.model_validate(bad)
    assert "entry_function" in str(exc.value)


def test_problem_id_pattern_rejects_uppercase() -> None:
    bad = _valid_problem_dict() | {"id": "LC-001"}
    with pytest.raises(ValidationError):
        BenchmarkProblem.model_validate(bad)


def test_short_problem_text_rejected() -> None:
    bad = _valid_problem_dict() | {"problem_text": "too short"}
    with pytest.raises(ValidationError):
        BenchmarkProblem.model_validate(bad)


def test_problem_must_have_at_least_one_variant() -> None:
    bad = _valid_problem_dict() | {"variants": []}
    with pytest.raises(ValidationError):
        BenchmarkProblem.model_validate(bad)


def test_variant_negative_failure_count_rejected() -> None:
    v = {
        "name": "x",
        "code": "def f():\n    pass\n",
        "expected_failure_count": -1,
        "error_pattern": "x",
    }
    with pytest.raises(ValidationError):
        Variant.model_validate(v)


# ---------- dataset-wide invariants ----------


def test_every_problem_has_at_least_three_variants() -> None:
    """Quality bar from Step 9 spec: each problem ≥ 3 variants."""
    raw = json.loads(DATASET_PATH.read_text())
    dataset = BenchmarkDataset.model_validate(raw)
    short = [p.id for p in dataset.problems if len(p.variants) < 3]
    assert not short, f"problems with <3 variants: {short}"


def test_every_variant_expects_at_least_one_failure() -> None:
    """A variant with expected_failure_count==0 wouldn't exercise the
    verifier. The schema permits 0 (for future use cases like no-op
    refactor variants), but the part-1 dataset bans it."""
    raw = json.loads(DATASET_PATH.read_text())
    dataset = BenchmarkDataset.model_validate(raw)
    zero_fail = [
        f"{p.id}::{v.name}"
        for p in dataset.problems
        for v in p.variants
        if v.expected_failure_count == 0
    ]
    assert not zero_fail, f"variants with 0 expected failures: {zero_fail}"
