"""Schema validation for backend/tests/agents/fixtures/sample_problems.json.

These tests guard the fixture set used by the Solver/Verifier integration suite
and by the Step 6.3 buggy-variant generator + seed CLIs. They do not exercise
the LLM or the sandbox — pure structural and AST checks.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "sample_problems.json"

REQUIRED_FIELDS = (
    "problem_id",
    "problem_text",
    "entry_function",
    "test_cases",
    "reference_solution",
)


def _load_problems() -> list[dict]:
    return json.loads(FIXTURE_PATH.read_text())


def test_all_10_problems_have_unique_ids() -> None:
    problems = _load_problems()
    assert len(problems) == 10, f"expected 10 problems, got {len(problems)}"
    ids = [p["problem_id"] for p in problems]
    assert len(set(ids)) == len(ids), f"duplicate problem_id in fixture: {ids}"


def test_all_problems_have_required_fields() -> None:
    problems = _load_problems()
    for p in problems:
        for field in REQUIRED_FIELDS:
            assert field in p, f"{p.get('problem_id')!r} missing field {field!r}"
        assert isinstance(p["test_cases"], list)
        assert len(p["test_cases"]) >= 3, (
            f"{p['problem_id']} has only {len(p['test_cases'])} test_cases (need >= 3)"
        )
        for tc in p["test_cases"]:
            assert set(tc.keys()) >= {"input", "expected", "description"}, (
                f"{p['problem_id']} test_case missing fields: {tc}"
            )


def test_all_test_cases_have_distinguishable_expected_values() -> None:
    """Expected values must not be empty or single non-numeric/non-structural chars.

    Per Step 6.3 spec, distinguishable means: length > 1, OR a list/dict/tuple
    repr (starts with bracket), OR a numeric literal (digit or minus sign).
    Pure-empty or single-letter expected values produce weak retrieval signals.
    """
    problems = _load_problems()
    weak: list[str] = []
    for p in problems:
        for tc in p["test_cases"]:
            exp = tc["expected"]
            if not exp:
                weak.append(f"{p['problem_id']}: input={tc['input']!r} expected is empty")
                continue
            if len(exp) > 1:
                continue
            if exp[0] in "0123456789-[{(":
                continue
            weak.append(f"{p['problem_id']}: input={tc['input']!r} expected={exp!r}")
    assert not weak, "weak expected values found:\n" + "\n".join(weak)


def test_all_reference_solutions_define_correct_entry_function() -> None:
    problems = _load_problems()
    for p in problems:
        ref = p["reference_solution"]
        try:
            tree = ast.parse(ref)
        except SyntaxError as exc:
            pytest.fail(f"{p['problem_id']} reference_solution is not valid Python: {exc}")
        defined = {node.name for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)}
        assert p["entry_function"] in defined, (
            f"{p['problem_id']} reference_solution does not define "
            f"{p['entry_function']!r}; defines {sorted(defined) or '[none]'}"
        )
