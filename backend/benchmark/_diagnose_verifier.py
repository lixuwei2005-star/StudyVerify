"""Throwaway diagnosis for Step 10 verifier false rejects.

Reads an eval artifact and writes a Markdown report explaining why reference
solutions were rejected, using the persisted raw /verify output when available.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any


DEFAULT_EVAL_PATH = Path("benchmark/results/2026-05-05_14-08-23_eval.json")
OUT_PATH = Path("benchmark/results/diagnosis-verifier.md")
TARGETED_IDS_PATH = Path("benchmark/_targeted_ids.txt")


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text())


def _load_problem_lookup(eval_data: dict[str, Any]) -> dict[str, dict[str, Any]]:
    problems: dict[str, dict[str, Any]] = {}
    for dataset in eval_data.get("datasets", []):
        path = Path(dataset)
        if not path.exists():
            continue
        data = _load_json(path)
        for problem in data.get("problems", []):
            problems[problem["id"]] = problem
    return problems


def _load_targeted_ids() -> set[str]:
    if not TARGETED_IDS_PATH.exists():
        return set()
    return {line.strip() for line in TARGETED_IDS_PATH.read_text().splitlines() if line.strip()}


def _first_present(root: Any, paths: list[tuple[Any, ...]]) -> Any:
    for path in paths:
        cur = root
        ok = True
        for part in path:
            if isinstance(cur, dict) and part in cur:
                cur = cur[part]
            elif isinstance(cur, list) and isinstance(part, int) and 0 <= part < len(cur):
                cur = cur[part]
            else:
                ok = False
                break
        if ok:
            return cur
    return None


def _extract_raw_output(ref: dict[str, Any]) -> dict[str, Any] | None:
    value = _first_present(
        ref,
        [
            ("raw_output",),
            ("data", "output"),
            ("output",),
            ("verify_response", "data", "output"),
            ("response", "data", "output"),
        ],
    )
    return value if isinstance(value, dict) else None


def _extract_sandbox_error(raw_output: dict[str, Any] | None) -> Any:
    if not isinstance(raw_output, dict):
        return None
    return _first_present(
        raw_output,
        [
            ("sandbox_error",),
            ("sandbox", "error"),
            ("execution", "sandbox_error"),
        ],
    )


def _extract_test_results(raw_output: dict[str, Any] | None) -> Any:
    if not isinstance(raw_output, dict):
        return None
    return _first_present(
        raw_output,
        [
            ("test_results",),
            ("tests",),
            ("results",),
        ],
    )


def _extract_diagnosis(raw_output: dict[str, Any] | None) -> str | None:
    if not isinstance(raw_output, dict):
        return None
    value = _first_present(
        raw_output,
        [
            ("diagnosis",),
            ("message",),
            ("reason",),
        ],
    )
    return value if isinstance(value, str) else None


def _has_value(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    return True


def _is_test_passed(test: Any) -> bool | None:
    if not isinstance(test, dict):
        return None
    for key in ("passed", "success", "ok"):
        if key in test:
            return bool(test[key])
    status = str(test.get("status", "")).lower()
    if status in {"pass", "passed", "success", "ok"}:
        return True
    if status in {"fail", "failed", "failure", "error"}:
        return False
    return None


def _failed_tests(test_results: Any) -> list[Any]:
    if not isinstance(test_results, list):
        return []
    return [test for test in test_results if _is_test_passed(test) is False]


def _all_tests_pass(test_results: Any) -> bool:
    if not isinstance(test_results, list) or not test_results:
        return False
    saw_decidable = False
    for test in test_results:
        passed = _is_test_passed(test)
        if passed is False:
            return False
        if passed is True:
            saw_decidable = True
    return saw_decidable


def _snippet(text: str | None, lines: int = 5) -> str:
    if not text:
        return "_reference_solution unavailable in loaded datasets_"
    first = text.strip("\n").splitlines()[:lines]
    return "\n".join(first) if first else "_empty reference_solution_"


def _short(value: Any, limit: int = 700) -> str:
    if value is None:
        return "_not present_"
    if not isinstance(value, str):
        value = json.dumps(value, indent=2, sort_keys=True)
    value = value.strip()
    if len(value) > limit:
        return value[:limit].rstrip() + "..."
    return value or "_empty_"


def _test_case_label(test: dict[str, Any], idx: int) -> str:
    bits = [f"test #{idx}"]
    for key in ("input", "inputs", "args", "kwargs"):
        if key in test:
            bits.append(f"{key}={_short(test[key], 180)}")
            break
    for key in ("actual", "actual_output", "output", "got"):
        if key in test:
            bits.append(f"actual={_short(test[key], 180)}")
            break
    for key in ("expected", "expected_output", "want"):
        if key in test:
            bits.append(f"expected={_short(test[key], 180)}")
            break
    if len(bits) == 1:
        bits.append(_short(test, 300))
    return "; ".join(bits)


def _hypothesis_for_sandbox(error: Any) -> str:
    text = str(error).lower()
    if "function" in text or "not found" in text or "attribute" in text:
        return "Function detection likely failed: expected entry function was not found or could not be imported."
    if "syntax" in text or "parse" in text or "indent" in text:
        return "Reference code likely hit a syntax/parse error before tests could run."
    if "import" in text or "module" in text:
        return "Reference code likely failed during import/module setup."
    return "Sandbox could not run the reference; inspect the raw error before changing verifier calibration."


def _categorize(record: dict[str, Any]) -> tuple[int, str]:
    raw_output = record["raw_output"]
    test_results = record["test_results"]
    if not isinstance(raw_output, dict):
        return 4, "unknown / missing data"
    if _has_value(record["sandbox_error"]):
        return 1, "sandbox couldn't run code"
    if isinstance(test_results, list) and test_results:
        if _failed_tests(test_results):
            return 2, "tests reported some failures"
        if _all_tests_pass(test_results) and raw_output.get("verified") is False:
            return 3, "tests passed but verifier rejected"
    return 4, "unknown / missing data"


def _build_records(eval_data: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    problems = _load_problem_lookup(eval_data)
    false_rejects: list[dict[str, Any]] = []
    all_reference_records: list[dict[str, Any]] = []
    for item in eval_data.get("per_problem_results", []):
        ref = item.get("reference_check") or {}
        raw_output = _extract_raw_output(ref)
        problem_id = item.get("problem_id")
        problem = problems.get(problem_id, {})
        record = {
            "problem_id": problem_id,
            "reference_solution": problem.get("reference_solution"),
            "raw_output": raw_output,
            "sandbox_error": _extract_sandbox_error(raw_output),
            "test_results": _extract_test_results(raw_output),
            "diagnosis": _extract_diagnosis(raw_output),
            "verifier_judged_pass": ref.get("verifier_judged_pass"),
            "verifier_correct": ref.get("verifier_correct"),
            "reference_check_keys": sorted(ref.keys()),
            "reference_check": ref,
        }
        if ref:
            all_reference_records.append(record)
        if ref.get("verifier_correct") is False:
            category, description = _categorize(record)
            record["category"] = category
            record["category_description"] = description
            false_rejects.append(record)
    return false_rejects, all_reference_records


def _append_problem_block(md: list[str], record: dict[str, Any]) -> None:
    md.append(f"### `{record['problem_id']}`")
    md.append("")
    md.append("- `verifier_judged_pass`: " f"`{record.get('verifier_judged_pass')}`")
    md.append("- `reference_solution` snippet:")
    md.append("")
    md.append("```python")
    md.append(_snippet(record.get("reference_solution")))
    md.append("```")
    md.append("")


def _render_category_1(md: list[str], records: list[dict[str, Any]]) -> None:
    md.append(f"## Category 1 - sandbox issues ({len(records)} problems)")
    md.append("")
    if not records:
        md.append("_No problems in this category._")
        md.append("")
        return
    for record in records:
        _append_problem_block(md, record)
        md.append(f"- `sandbox_error`: {_short(record['sandbox_error'])}")
        md.append(f"- Hypothesis: {_hypothesis_for_sandbox(record['sandbox_error'])}")
        md.append("")


def _render_category_2(md: list[str], records: list[dict[str, Any]]) -> None:
    md.append(f"## Category 2 - test failures ({len(records)} problems)")
    md.append("")
    if not records:
        md.append("_No problems in this category._")
        md.append("")
        return
    for record in records:
        _append_problem_block(md, record)
        failed = _failed_tests(record.get("test_results"))
        md.append("- Failed public test cases:")
        for idx, test in enumerate(failed, start=1):
            md.append(f"  - {_test_case_label(test, idx)}")
        md.append("- Hypothesis: The persisted test results say the reference failed public tests; re-check dataset reference code and test-case shape for this problem.")
        md.append("")


def _render_category_3(md: list[str], records: list[dict[str, Any]]) -> None:
    md.append(f"## Category 3 - anti-leak over-rejection ({len(records)} problems)")
    md.append("")
    if not records:
        md.append("_No problems in this category._")
        md.append("")
        return
    for record in records:
        _append_problem_block(md, record)
        md.append("- All persisted test results passed, but `verified=False`.")
        md.append(f"- Diagnosis text: {_short(record.get('diagnosis'))}")
        md.append("- Hypothesis: The LLM diagnosis/judge layer rejected code after passing tests; tune that prompt or retry threshold only if this category is large enough.")
        md.append("")


def _render_category_4(md: list[str], records: list[dict[str, Any]]) -> None:
    md.append(f"## Category 4 - unknown / missing data ({len(records)} problems)")
    md.append("")
    if not records:
        md.append("_No problems in this category._")
        md.append("")
        return
    md.append(
        "These records have `reference_check.verifier_correct=False`, but `raw_output` "
        "or its `test_results` are missing/empty, so the rejection reason is still "
        "not recoverable from this eval artifact."
    )
    md.append("")
    for record in records:
        _append_problem_block(md, record)
        md.append("- `reference_check` fields present: " f"`{', '.join(record['reference_check_keys'])}`")
        md.append(f"- `raw_output`: {_short(record.get('raw_output'))}")
        md.append(f"- `sandbox_error`: {_short(record.get('sandbox_error'))}")
        md.append(f"- `test_results`: {_short(record.get('test_results'))}")
        md.append(f"- `diagnosis`: {_short(record.get('diagnosis'))}")
        md.append("- Hypothesis: Missing or incomplete raw verifier instrumentation for this record.")
        md.append("")


def _render_subset_sanity(
    md: list[str],
    eval_data: dict[str, Any],
    all_reference_records: list[dict[str, Any]],
) -> None:
    targeted_ids = _load_targeted_ids()
    if not targeted_ids:
        return
    problem_records = eval_data.get("per_problem_results", [])
    target_problem_records = [p for p in problem_records if p.get("problem_id") in targeted_ids]
    control_problem_records = [p for p in problem_records if p.get("problem_id") not in targeted_ids]
    target_missing_ref = [p for p in target_problem_records if not p.get("reference_check")]
    control_missing_ref = [p for p in control_problem_records if not p.get("reference_check")]
    targeted = [r for r in all_reference_records if r["problem_id"] in targeted_ids]
    controls = [r for r in all_reference_records if r["problem_id"] not in targeted_ids]
    target_pass = [r for r in targeted if r.get("verifier_correct") is True]
    target_fail = [r for r in targeted if r.get("verifier_correct") is False]
    control_pass = [r for r in controls if r.get("verifier_correct") is True]
    control_fail = [r for r in controls if r.get("verifier_correct") is False]

    md.append("## Targeted rerun sanity")
    md.append("")
    md.append(f"- Targeted original false-reject problem records in this eval: {len(target_problem_records)}")
    md.append(f"- Targeted references with verifier result: {len(targeted)}")
    md.append(f"- Targeted references missing/skipped before verify: {len(target_missing_ref)}")
    md.append(f"- Targeted IDs now verifier-correct: {len(target_pass)}")
    md.append(f"- Targeted IDs still false-rejected: {len(target_fail)}")
    if target_missing_ref:
        md.append("- Targeted missing/skipped IDs: " + ", ".join(f"`{p['problem_id']}`" for p in target_missing_ref))
    md.append(f"- Control problem records in this eval: {len(control_problem_records)}")
    md.append(f"- Control references with verifier result: {len(controls)}")
    md.append(f"- Control references missing/skipped before verify: {len(control_missing_ref)}")
    md.append(f"- Control references verifier-correct: {len(control_pass)}")
    md.append(f"- Control references false-rejected: {len(control_fail)}")
    if control_fail:
        md.append("- Control failure IDs: " + ", ".join(f"`{r['problem_id']}`" for r in control_fail))
    md.append("")


def _conclusions(records_by_category: dict[int, list[dict[str, Any]]]) -> list[str]:
    counts = {idx: len(records_by_category.get(idx, [])) for idx in range(1, 5)}
    ranked = sorted(counts.items(), key=lambda item: item[1], reverse=True)
    lines = ["## Conclusions", ""]
    lines.append("Hypothesis ranking:")
    for rank, (category, count) in enumerate(ranked, start=1):
        if category == 1:
            cause = "sandbox bridge / function detection / import failure"
        elif category == 2:
            cause = "dataset reference or test-case mismatch"
        elif category == 3:
            cause = "LLM judge over-rejection after passing tests"
        else:
            cause = "eval artifact omitted or failed to produce raw verify details"
        lines.append(f"{rank}. Category {category} ({count} problems): {cause}")
    lines.append("")
    dominant_category, dominant_count = ranked[0]
    if dominant_count == 0:
        lines.append("Top data-backed hypothesis: no false rejects were present in this eval artifact.")
    elif dominant_category == 1:
        lines.append("Top data-backed hypothesis: sandbox execution/function detection is the dominant false-reject source.")
    elif dominant_category == 2:
        lines.append("Top data-backed hypothesis: the reference solution or benchmark test-case contract is mismatched for most false rejects.")
    elif dominant_category == 3:
        lines.append("Top data-backed hypothesis: verifier calibration is too strict after tests pass; the LLM diagnosis layer is rejecting valid code.")
    else:
        lines.append("Top data-backed hypothesis: raw verifier details are still missing for the dominant failure mode, so behavior fixes would be premature.")
    lines.append("")
    return lines


def _render_report(
    eval_path: Path,
    eval_data: dict[str, Any],
    records: list[dict[str, Any]],
    all_reference_records: list[dict[str, Any]],
) -> str:
    records_by_category: dict[int, list[dict[str, Any]]] = {idx: [] for idx in range(1, 5)}
    for record in records:
        records_by_category[record["category"]].append(record)

    counts = {idx: len(records_by_category[idx]) for idx in range(1, 5)}
    raw_output_present = sum(1 for r in all_reference_records if isinstance(r.get("raw_output"), dict))
    md: list[str] = []
    md.append("# Verifier False-Reject Diagnosis")
    md.append("")
    md.append(f"- Source eval: `{eval_path}`")
    md.append(f"- Reference checks inspected: {len(all_reference_records)}")
    md.append(f"- False-rejected references inspected: {len(records)}")
    md.append(f"- Reference checks with `raw_output`: {raw_output_present}/{len(all_reference_records)}")
    md.append("")
    md.append("## Summary by category")
    md.append("")
    md.append("| Category | Count | Description |")
    md.append("|---|---:|---|")
    md.append(f"| 1 | {counts[1]} | sandbox couldn't run code |")
    md.append(f"| 2 | {counts[2]} | tests reported some failures |")
    md.append(f"| 3 | {counts[3]} | tests passed but verifier rejected |")
    md.append(f"| 4 | {counts[4]} | unknown / missing data |")
    md.append("")
    md.append("## Data availability check")
    md.append("")
    if raw_output_present:
        sample = next((r for r in all_reference_records if isinstance(r.get("raw_output"), dict)), None)
        keys = sorted((sample.get("raw_output") or {}).keys()) if sample else []
        md.append("`raw_output` is present in this eval artifact.")
        md.append("")
        md.append(f"Sample `raw_output` keys: `{', '.join(keys)}`")
    else:
        md.append(
            "No reference check in this eval artifact contains `raw_output`. "
            "The artifact cannot distinguish sandbox, test-case, and LLM-judge causes."
        )
    md.append("")

    _render_subset_sanity(md, eval_data, all_reference_records)
    _render_category_1(md, records_by_category[1])
    _render_category_2(md, records_by_category[2])
    _render_category_3(md, records_by_category[3])
    _render_category_4(md, records_by_category[4])
    md.extend(_conclusions(records_by_category))
    md.append("## P0 fix paths")
    md.append("")
    md.append("- For category 1: fix sandbox bridge / function detection")
    md.append("- For category 2: re-validate dataset references")
    md.append("- For category 3: tune LLM judge prompt or relax retry conditions")
    md.append("- For category 4: improve eval pipeline error logging")
    md.append("")
    return "\n".join(md)


def main() -> None:
    eval_path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_EVAL_PATH
    eval_data = _load_json(eval_path)
    records, all_reference_records = _build_records(eval_data)
    report = _render_report(eval_path, eval_data, records, all_reference_records)
    OUT_PATH.write_text(report)
    counts = {idx: 0 for idx in range(1, 5)}
    for record in records:
        counts[record["category"]] += 1
    print(f"Wrote {OUT_PATH}")
    print("Category counts: " f"1={counts[1]} 2={counts[2]} 3={counts[3]} 4={counts[4]}")


if __name__ == "__main__":
    main()
