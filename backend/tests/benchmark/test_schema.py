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

_BENCHMARK_DIR = Path(__file__).resolve().parents[2] / "benchmark"
DATASET_PATH = _BENCHMARK_DIR / "problems_part_1.json"
DATASET_PATHS = [
    _BENCHMARK_DIR / "problems_part_1.json",
    _BENCHMARK_DIR / "problems_part_2.json",
    _BENCHMARK_DIR / "problems_part_3.json",
]


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


_EXPECTED_COUNTS = {
    "problems_part_1.json": 30,
    "problems_part_2.json": 30,
    "problems_part_3.json": 40,
}


@pytest.mark.parametrize("path", DATASET_PATHS, ids=lambda p: p.name)
def test_dataset_file_parses(path: Path) -> None:
    raw = json.loads(path.read_text())
    dataset = BenchmarkDataset.model_validate(raw)
    assert len(dataset.problems) == _EXPECTED_COUNTS[path.name]
    ids = [p.id for p in dataset.problems]
    assert len(ids) == len(set(ids)), "duplicate problem IDs"


def test_total_problem_count_is_100() -> None:
    """Cumulative across all phases — the headline number for the dataset."""
    total = 0
    for path in DATASET_PATHS:
        raw = json.loads(path.read_text())
        total += len(raw["problems"])
    assert total == 100, f"benchmark should be 100 problems, found {total}"


def test_combined_datasets_have_unique_ids() -> None:
    """Across part_1 + part_2, no problem id may collide."""
    all_ids: list[str] = []
    for path in DATASET_PATHS:
        raw = json.loads(path.read_text())
        all_ids.extend(p["id"] for p in raw["problems"])
    dupes = {i for i in all_ids if all_ids.count(i) > 1}
    assert not dupes, f"id collisions across datasets: {dupes}"


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


@pytest.mark.parametrize("path", DATASET_PATHS, ids=lambda p: p.name)
def test_every_problem_has_at_least_three_variants(path: Path) -> None:
    """Quality bar from Step 9 spec: each problem ≥ 3 variants."""
    raw = json.loads(path.read_text())
    dataset = BenchmarkDataset.model_validate(raw)
    short = [p.id for p in dataset.problems if len(p.variants) < 3]
    assert not short, f"problems with <3 variants: {short}"


@pytest.mark.parametrize("path", DATASET_PATHS, ids=lambda p: p.name)
def test_every_variant_expects_at_least_one_failure(path: Path) -> None:
    """A variant with expected_failure_count==0 wouldn't exercise the
    verifier. The schema permits 0 (future use cases like no-op refactor
    variants), but every shipped dataset bans it."""
    raw = json.loads(path.read_text())
    dataset = BenchmarkDataset.model_validate(raw)
    zero_fail = [
        f"{p.id}::{v.name}"
        for p in dataset.problems
        for v in p.variants
        if v.expected_failure_count == 0
    ]
    assert not zero_fail, f"variants with 0 expected failures: {zero_fail}"
