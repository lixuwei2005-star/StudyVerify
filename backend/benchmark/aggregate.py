"""Aggregate per-problem results into the four headline metrics.

1. Verifier accuracy: % of (reference + variant) verifies whose
   verified-pass matched the expected pass.
2. Anti-leak success: % of hints that passed both phrase filter AND LLM
   judge. Layered rates exported separately so we can attribute leaks.
3. Helpfulness progression: per-hint-index average would_fix_bug rate.
4. Latency P50/P95 per endpoint (solve, verify, hint).
"""

from __future__ import annotations

import statistics
from typing import Any


def _p95(values: list[int]) -> int:
    if not values:
        return 0
    s = sorted(values)
    idx = min(len(s) - 1, int(len(s) * 0.95))
    return s[idx]


def aggregate_results(per_problem: list[dict[str, Any]]) -> dict[str, Any]:
    verifier_total = 0
    verifier_correct = 0

    hints_total = 0
    hints_passed = 0
    hints_phrase_pass = 0
    hints_llm_pass = 0
    hints_judge_errors = 0  # how many anti-leak judge calls errored
    hints_helpful_judge_errors = 0

    helpfulness_by_index: dict[int, list[int]] = {i: [] for i in range(1, 6)}

    solve_latencies: list[int] = []
    verify_latencies: list[int] = []
    hint_latencies: list[int] = []

    err = {"solve_failures": 0, "verify_failures": 0, "hint_failures": 0}

    for prob in per_problem:
        s = prob["solve"]
        if s and s["success"]:
            solve_latencies.append(s["latency_ms"])
        elif s and not s["success"]:
            err["solve_failures"] += 1

        ref = prob["reference_check"]
        if ref:
            if ref["success"]:
                verify_latencies.append(ref["latency_ms"])
                verifier_total += 1
                if ref["verifier_correct"]:
                    verifier_correct += 1
            else:
                err["verify_failures"] += 1

        for variant in prob["variants"]:
            v = variant["verify"]
            if v and v["success"]:
                verify_latencies.append(v["latency_ms"])
                verifier_total += 1
                if v["verifier_correct"]:
                    verifier_correct += 1
            else:
                err["verify_failures"] += 1

            for h in variant["hints"]:
                if not h["success"]:
                    err["hint_failures"] += 1
                    continue
                hint_latencies.append(h["latency_ms"])
                hints_total += 1

                al = h["anti_leak"]
                if al is not None:
                    if al["passes"]:
                        hints_passed += 1
                    if al["phrase_filter_passes"]:
                        hints_phrase_pass += 1
                    if al["llm_judge_passes"]:
                        hints_llm_pass += 1
                    if "judge_error" in al.get("llm_judge_reason", ""):
                        hints_judge_errors += 1

                hp = h["helpfulness"]
                if hp is not None:
                    if hp.get("judge_error"):
                        hints_helpful_judge_errors += 1
                    helpfulness_by_index[h["index"]].append(1 if hp["would_fix"] else 0)

    return {
        "total_problems": len(per_problem),
        "verifier_accuracy": (verifier_correct / verifier_total) if verifier_total else 0.0,
        "anti_leak_success_rate": (hints_passed / hints_total) if hints_total else 0.0,
        "anti_leak_phrase_filter_rate": (hints_phrase_pass / hints_total) if hints_total else 0.0,
        "anti_leak_llm_judge_rate": (hints_llm_pass / hints_total) if hints_total else 0.0,
        "helpfulness_progression": {
            f"hint_{idx}": (sum(rs) / len(rs)) if rs else 0.0
            for idx, rs in helpfulness_by_index.items()
        },
        "latency": {
            "solve_p50_ms": int(statistics.median(solve_latencies)) if solve_latencies else 0,
            "solve_p95_ms": _p95(solve_latencies),
            "verify_p50_ms": int(statistics.median(verify_latencies)) if verify_latencies else 0,
            "verify_p95_ms": _p95(verify_latencies),
            "hint_p50_ms": int(statistics.median(hint_latencies)) if hint_latencies else 0,
            "hint_p95_ms": _p95(hint_latencies),
        },
        "totals": {
            "verifier_judgments": verifier_total,
            "hints_evaluated": hints_total,
            "anti_leak_judge_errors": hints_judge_errors,
            "helpfulness_judge_errors": hints_helpful_judge_errors,
        },
        "error_summary": err,
    }
