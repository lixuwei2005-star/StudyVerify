"""Throwaway diagnosis for Step 10 verifier false rejects.

Reads the Step 9 Phase B eval artifact and writes a Markdown report explaining
what can be diagnosed from the persisted per-problem records.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


EVAL_PATH = Path("benchmark/results/2026-05-05_14-08-23_eval.json")
OUT_PATH = Path("benchmark/results/diagnosis-verifier.md")


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


def _extract_output(ref: dict[str, Any]) -> dict[str, Any]:
    candidates = [
        ref,
        ref.get("data"),
        _first_present(ref, [("data", "output")]),
        ref.get("output"),
        ref.get("verify_response"),
        ref.get("response"),
        _first_present(ref, [("verify_response", "data", "output")]),
        _first_present(ref, [("response", "data", "output")]),
    ]
    merged: dict[str, Any] = {}
    for candidate in candidates:
        if isinstance(candidate, dict):
            merged.update(candidate)
    return merged


def _extract_sandbox_error(ref: dict[str, Any], output: dict[str, Any]) -> Any:
    return _first_present(
        {"ref": ref, "output": output},
        [
            ("ref", "sandbox_error"),
            ("ref", "error"),
            ("ref", "data", "output", "sandbox_error"),
            ("ref", "output", "sandbox_error"),
            ("ref", "verify_response", "data", "output", "sandbox_error"),
            ("ref", "response", "data", "output", "sandbox_error"),
            ("output", "sandbox_error"),
            ("output", "error"),
        ],
    )


def _extract_test_results(ref: dict[str, Any], output: dict[str, Any]) -> Any:
    return _first_present(
        {"ref": ref, "output": output},
        [
            ("ref", "test_results"),
            ("ref", "data", "output", "test_results"),
            ("ref", "output", "test_results"),
            ("ref", "verify_response", "data", "output", "test_results"),
            ("ref", "response", "data", "output", "test_results"),
            ("output", "test_results"),
            ("output", "tests"),
            ("output", "results"),
        ],
    )


def _extract_diagnosis(ref: dict[str, Any], output: dict[str, Any]) -> str | None:
    value = _first_present(
        {"ref": ref, "output": output},
        [
            ("ref", "diagnosis"),
            ("ref", "data", "output", "diagnosis"),
            ("ref", "output", "diagnosis"),
            ("ref", "verify_response", "data", "output", "diagnosis"),
            ("ref", "response", "data", "output", "diagnosis"),
            ("output", "diagnosis"),
            ("output", "message"),
            ("output", "reason"),
        ],
    )
    return value if isinstance(value, str) else None


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
    failed = []
    for test in test_results:
        passed = _is_test_passed(test)
        if passed is False:
            failed.append(test)
    return failed


def _all_tests_pass(test_results: Any) -> bool:
    if not isinstance(test_results, list) or not test_results:
        return False
    seen_decidable = False
    for test in test_results:
        passed = _is_test_passed(test)
        if passed is False:
            return False
        if passed is True:
            seen_decidable = True
    return seen_decidable


def _snippet(text: str | None, lines: int = 5) -> str:
    if not text:
        return "_reference_solution unavailable in loaded datasets_"
    first = text.strip("\n").splitlines()[:lines]
    return "\n".join(first) if first else "_empty reference_solution_"


def _short(value: Any, limit: int = 500) -> str:
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
            bits.append(f"{key}={_short(test[key], 160)}")
            break
    for key in ("actual", "actual_output", "output", "got"):
        if key in test:
            bits.append(f"actual={_short(test[key], 160)}")
            break
    for key in ("expected", "expected_output", "want"):
        if key in test:
            bits.append(f"expected={_short(test[key], 160)}")
            break
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
    sandbox_error = record["sandbox_error"]
    test_results = record["test_results"]
    if sandbox_error is not None:
        return 1, "sandbox couldn't run code"
    if isinstance(test_results, list) and test_results:
        if _failed_tests(test_results):
            return 2, "tests reported some failures"
        if _all_tests_pass(test_results) and record["verifier_judged_pass"] is False:
            return 3, "tests passed but verifier rejected"
    return 4, "unknown / missing data"


def _build_records(eval_data: dict[str, Any]) -> list[dict[str, Any]]:
    problems = _load_problem_lookup(eval_data)
    records: list[dict[str, Any]] = []
    for item in eval_data.get("per_problem_results", []):
        ref = item.get("reference_check") or {}
        if ref.get("verifier_correct") is not False:
            continue

        output = _extract_output(ref)
        problem_id = item.get("problem_id")
        problem = problems.get(problem_id, {})
        sandbox_error = _extract_sandbox_error(ref, output)
        if sandbox_error is None and ref.get("success") is True and ref.get("error") is None:
            # A successful API call with no error is not a sandbox error. Keep it
            # as missing detail instead of misclassifying a null summary field.
            sandbox_error = None
        test_results = _extract_test_results(ref, output)
        diagnosis = _extract_diagnosis(ref, output)
        record = {
            "problem_id": problem_id,
            "reference_solution": problem.get("reference_solution"),
            "sandbox_error": sandbox_error,
            "test_results": test_results,
            "diagnosis": diagnosis,
            "verifier_judged_pass": ref.get("verifier_judged_pass"),
            "reference_check_keys": sorted(ref.keys()),
            "reference_check": ref,
        }
        category, description = _categorize(record)
        record["category"] = category
        record["category_description"] = description
        records.append(record)
    return records


def _append_problem_block(md: list[str], record: dict[str, Any]) -> None:
    md.append(f"### `{record['problem_id']}`")
    md.append("")
    md.append("- `verifier_judged_pass`: "
              f"`{record.get('verifier_judged_pass')}`")
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
        "These records have `reference_check.verifier_correct=False`, but the eval "
        "artifact does not include `sandbox_error`, `test_results`, or `diagnosis`. "
        "That means the original rejection reason cannot be recovered from "
        "`2026-05-05_14-08-23_eval.json` alone."
    )
    md.append("")
    for record in records:
        _append_problem_block(md, record)
        md.append("- `reference_check` fields present: "
                  f"`{', '.join(record['reference_check_keys'])}`")
        md.append(f"- `sandbox_error`: {_short(record.get('sandbox_error'))}")
        md.append(f"- `test_results`: {_short(record.get('test_results'))}")
        md.append(f"- `diagnosis`: {_short(record.get('diagnosis'))}")
        md.append("- Hypothesis: Missing instrumentation in the eval artifact, not enough evidence to tell whether sandbox, dataset tests, or the LLM judge caused this rejection.")
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
            cause = "eval artifact omitted raw verify details"
        lines.append(f"{rank}. Category {category} ({count} problems): {cause}")
    lines.append("")
    if counts[4] == sum(counts.values()) and counts[4] > 0:
        lines.append(
            "Top data-backed hypothesis: the Step 9 eval pipeline discarded the "
            "raw `/verify` output for reference checks. Every false reject in this "
            "artifact has only the summary fields, so the immediate root cause is "
            "not identifiable from the saved JSON. A follow-up diagnostic run must "
            "persist `output.test_results`, `output.diagnosis`, and any "
            "`sandbox_error` before deciding between sandbox, dataset, or LLM-judge fixes."
        )
        lines.append("")
    return lines


def _render_report(eval_data: dict[str, Any], records: list[dict[str, Any]]) -> str:
    records_by_category: dict[int, list[dict[str, Any]]] = {idx: [] for idx in range(1, 5)}
    for record in records:
        records_by_category[record["category"]].append(record)

    counts = {idx: len(records_by_category[idx]) for idx in range(1, 5)}
    md: list[str] = []
    md.append("# Verifier False-Reject Diagnosis")
    md.append("")
    md.append(f"- Source eval: `{EVAL_PATH}`")
    md.append(f"- False-rejected references inspected: {len(records)}")
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
    md.append(
        "The persisted false-reject records contain only the eval summary fields "
        "`success`, `latency_ms`, `verifier_judged_pass`, `expected_pass`, "
        "`verifier_correct`, and `error`. They do not include the raw `/verify` "
        "payload needed to inspect sandbox errors, per-test outcomes, or LLM "
        "diagnosis text."
    )
    md.append("")

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
    md.append("## Instrumentation gap to close before fixing")
    md.append("")
    md.append(
        "Because this artifact places all 60 failures in Category 4, the safest "
        "next step is not a verifier behavior change. First, run or patch a "
        "diagnostic capture that persists the full reference `/verify` output for "
        "these same problem IDs, including `output.verified`, `output.test_results`, "
        "`output.diagnosis`, and any sandbox error. Only then can Step 10 choose "
        "between sandbox, dataset, and LLM-judge fixes without guessing."
    )
    md.append("")
    return "\n".join(md)


def main() -> None:
    eval_data = _load_json(EVAL_PATH)
    records = _build_records(eval_data)
    report = _render_report(eval_data, records)
    OUT_PATH.write_text(report)
    counts = {idx: 0 for idx in range(1, 5)}
    for record in records:
        counts[record["category"]] += 1
    print(f"Wrote {OUT_PATH}")
    print(
        "Category counts: "
        f"1={counts[1]} 2={counts[2]} 3={counts[3]} 4={counts[4]}"
    )


if __name__ == "__main__":
    main()
