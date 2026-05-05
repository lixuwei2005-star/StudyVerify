"""Pure-function tests for benchmark.aggregate."""

from __future__ import annotations

from benchmark.aggregate import _p95, aggregate_results


def test_aggregate_handles_empty_input() -> None:
    out = aggregate_results([])
    assert out["total_problems"] == 0
    assert out["verifier_accuracy"] == 0.0
    assert out["anti_leak_success_rate"] == 0.0
    assert all(v == 0.0 for v in out["helpfulness_progression"].values())
    assert out["latency"]["solve_p50_ms"] == 0


def _stub_problem(verifier_correct_for_ref: bool, hint_passes: bool, would_fix: bool) -> dict:
    return {
        "problem_id": "p",
        "topics": [],
        "difficulty": "easy",
        "solve": {"success": True, "latency_ms": 1000, "error": None},
        "reference_check": {
            "success": True,
            "latency_ms": 500,
            "verifier_judged_pass": verifier_correct_for_ref,
            "expected_pass": True,
            "verifier_correct": verifier_correct_for_ref,
            "error": None,
        },
        "variants": [
            {
                "name": "v1",
                "error_pattern": "x",
                "verify": {
                    "success": True,
                    "latency_ms": 600,
                    "verifier_judged_pass": False,
                    "expected_pass": False,
                    "verifier_correct": True,
                    "error": None,
                },
                "hints": [
                    {
                        "index": i,
                        "success": True,
                        "latency_ms": 700,
                        "text": "...",
                        "anti_leak": {
                            "passes": hint_passes,
                            "phrase_filter_passes": hint_passes,
                            "phrase_matches": [],
                            "llm_judge_passes": hint_passes,
                            "llm_judge_reason": "",
                        },
                        "helpfulness": {
                            "understood": True,
                            "would_fix": would_fix,
                            "proposed_change": "",
                            "judge_error": None,
                        },
                        "error": None,
                    }
                    for i in range(1, 6)
                ],
            }
        ],
        "errors": [],
    }


def test_verifier_accuracy_all_correct() -> None:
    out = aggregate_results([_stub_problem(True, True, True)])
    # 1 ref + 1 variant = 2 judgments; both correct.
    assert out["verifier_accuracy"] == 1.0
    assert out["totals"]["verifier_judgments"] == 2


def test_verifier_accuracy_partial() -> None:
    """Reference returns wrong, variant returns right → 1/2 = 50%."""
    out = aggregate_results([_stub_problem(False, True, True)])
    assert out["verifier_accuracy"] == 0.5


def test_anti_leak_rate_all_pass() -> None:
    out = aggregate_results([_stub_problem(True, True, True)])
    # 5 hints, all pass → 100%
    assert out["anti_leak_success_rate"] == 1.0
    assert out["totals"]["hints_evaluated"] == 5


def test_anti_leak_rate_all_fail() -> None:
    out = aggregate_results([_stub_problem(True, False, True)])
    assert out["anti_leak_success_rate"] == 0.0


def test_helpfulness_progression_keys() -> None:
    out = aggregate_results([_stub_problem(True, True, True)])
    assert set(out["helpfulness_progression"].keys()) == {f"hint_{i}" for i in range(1, 6)}
    # All would_fix=True → 100% per hint level
    for v in out["helpfulness_progression"].values():
        assert v == 1.0


def test_p95_simple() -> None:
    # 100 values 1..100; p95 should be around 95 (allowing for the index calc).
    assert _p95(list(range(1, 101))) in (95, 96)


def test_p95_empty() -> None:
    assert _p95([]) == 0


def test_p95_single() -> None:
    assert _p95([42]) == 42


def test_solve_failure_counted_in_errors() -> None:
    bad = {
        "problem_id": "p",
        "topics": [],
        "difficulty": "easy",
        "solve": {"success": False, "latency_ms": 100, "error": "HTTP 502"},
        "reference_check": None,
        "variants": [],
        "errors": ["solver failed: HTTP 502"],
    }
    out = aggregate_results([bad])
    assert out["error_summary"]["solve_failures"] == 1
