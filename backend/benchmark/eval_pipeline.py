"""Per-problem evaluation orchestration.

For one BenchmarkProblem, runs:
    1. /solve (once) — capture solver_session_id and latency.
    2. /verify on reference_solution — should be verified=True.
    3. For each variant:
        a. /verify on variant.code — should be verified=False.
        b. 5x /hint, with anti-leak audit + helpfulness audit per hint.

Returns a dict with the per-call success flags, latencies, judge outputs,
and any errors encountered. Aggregation happens in aggregate.py.
"""

from __future__ import annotations

from typing import Any

from app.llm.gateway import LLMGateway

from benchmark.anti_leak_judge import check_no_leak
from benchmark.api_client import StudyVerifyAPI
from benchmark.helpful_judge import check_helpful

N_HINTS_PER_VARIANT = 5


async def evaluate_problem(
    problem: dict[str, Any], api: StudyVerifyAPI, llm: LLMGateway
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "problem_id": problem["id"],
        "topics": problem.get("topics", []),
        "difficulty": problem.get("difficulty", "easy"),
        "solve": None,
        "reference_check": None,
        "variants": [],
        "errors": [],
    }

    # ---- Step 1: solve ----
    solve = await api.solve(problem)
    result["solve"] = {
        "success": solve["success"],
        "latency_ms": solve["latency_ms"],
        "error": solve["error"],
    }
    if not solve["success"]:
        result["errors"].append(f"solver failed: {solve['error']}")
        return result

    solver_session_id = solve["data"]["session_id"]

    # ---- Step 2: verify reference (expected pass) ----
    ref_v = await api.verify(solver_session_id, problem["reference_solution"])
    if ref_v["success"]:
        verified = bool(ref_v["data"]["output"]["verified"])
        result["reference_check"] = {
            "success": True,
            "latency_ms": ref_v["latency_ms"],
            "verifier_judged_pass": verified,
            "expected_pass": True,
            "verifier_correct": verified is True,
            "raw_output": ref_v["data"]["output"],
            "error": None,
        }
    else:
        result["reference_check"] = {
            "success": False,
            "latency_ms": ref_v["latency_ms"],
            "verifier_judged_pass": None,
            "expected_pass": True,
            "verifier_correct": False,
            "raw_output": None,
            "error": ref_v["error"],
        }
        result["errors"].append(f"reference verify failed: {ref_v['error']}")

    # ---- Step 3: each variant ----
    for variant in problem["variants"]:
        v_record: dict[str, Any] = {
            "name": variant["name"],
            "error_pattern": variant["error_pattern"],
            "verify": None,
            "hints": [],
        }

        v = await api.verify(solver_session_id, variant["code"])
        if v["success"]:
            v_verified = bool(v["data"]["output"]["verified"])
            v_record["verify"] = {
                "success": True,
                "latency_ms": v["latency_ms"],
                "verifier_judged_pass": v_verified,
                "expected_pass": False,
                "verifier_correct": v_verified is False,
                "raw_output": v["data"]["output"],
                "error": None,
            }
        else:
            v_record["verify"] = {
                "success": False,
                "latency_ms": v["latency_ms"],
                "verifier_judged_pass": None,
                "expected_pass": False,
                "verifier_correct": False,
                "raw_output": None,
                "error": v["error"],
            }
            result["variants"].append(v_record)
            continue

        verifier_session_id = v["data"]["session_id"]

        # ---- Step 4: 5 hints per variant ----
        for hint_idx in range(1, N_HINTS_PER_VARIANT + 1):
            h = await api.hint(verifier_session_id)
            hint_record: dict[str, Any] = {
                "index": hint_idx,
                "success": h["success"],
                "latency_ms": h["latency_ms"],
                "text": None,
                "anti_leak": None,
                "helpfulness": None,
                "error": h["error"],
            }
            if h["success"]:
                text = h["data"]["hint_text"]
                hint_record["text"] = text
                hint_record["anti_leak"] = await check_no_leak(
                    text, problem["problem_text"], llm
                )
                hint_record["helpfulness"] = await check_helpful(
                    problem["problem_text"],
                    variant["code"],
                    text,
                    hint_idx,
                    llm,
                )
            v_record["hints"].append(hint_record)

        result["variants"].append(v_record)

    return result
