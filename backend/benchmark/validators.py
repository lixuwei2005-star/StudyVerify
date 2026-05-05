"""Validators for benchmark datasets.

Two-layer check:
1. Schema validation (Pydantic) — fast, no I/O.
2. Reference-solution execution — runs each problem's reference_solution
   through the local subprocess sandbox runner against the problem's
   own test_cases. The reference must verify=True; otherwise the
   problem is malformed and any later evaluation against it would be
   meaningless.

Invocation:
    uv run python -m benchmark.validators benchmark/problems_part_1.json

No FastAPI / LLM dependencies — kept lightweight per Step 9 spec.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

from app.sandbox.runner import PythonSubprocessRunner
from app.sandbox.schemas import SandboxRunRequest
from benchmark.schema import BenchmarkDataset, BenchmarkProblem


async def _verify_problem(
    problem: BenchmarkProblem,
    runner: PythonSubprocessRunner,
) -> tuple[bool, str]:
    request = SandboxRunRequest(
        code=problem.reference_solution,
        entry_function=problem.entry_function,
        test_cases=[tc.model_dump() for tc in problem.test_cases],
    )
    result = await runner.run(request)
    if result.status == "all_passed":
        return True, ""
    failing = [
        f"  test {r.test_index} ({r.input!r} -> expected {r.expected!r}): "
        f"actual={r.actual!r} error={r.error!r}"
        for r in result.test_results
        if not r.passed
    ]
    detail = result.error or "\n".join(failing) or "unknown failure"
    return False, f"status={result.status}\n{detail}"


async def _verify_variants_signal_failure(
    problem: BenchmarkProblem,
    runner: PythonSubprocessRunner,
) -> list[str]:
    """Cross-check: each variant should produce expected_failure_count
    failing tests when executed. Drift here means the variant has been
    edited or the test_cases changed without updating the variant."""
    issues: list[str] = []
    for variant in problem.variants:
        request = SandboxRunRequest(
            code=variant.code,
            entry_function=problem.entry_function,
            test_cases=[tc.model_dump() for tc in problem.test_cases],
        )
        result = await runner.run(request)
        actual_fail = result.fail_count
        if actual_fail != variant.expected_failure_count:
            issues.append(
                f"  variant {variant.name!r}: expected_failure_count="
                f"{variant.expected_failure_count} but observed "
                f"{actual_fail} (status={result.status})"
            )
    return issues


async def validate_dataset(dataset: BenchmarkDataset) -> tuple[int, list[str]]:
    """Return (n_valid, errors). Each error is a multi-line problem-level report."""
    runner = PythonSubprocessRunner()
    errors: list[str] = []
    n_valid = 0
    for p in dataset.problems:
        ok, detail = await _verify_problem(p, runner)
        variant_issues = await _verify_variants_signal_failure(p, runner)
        if ok and not variant_issues:
            n_valid += 1
            continue
        block = [f"[{p.id}] {p.title}"]
        if not ok:
            block.append(f"  reference_solution failed: {detail}")
        if variant_issues:
            block.append("  variant drift:")
            block.extend(variant_issues)
        errors.append("\n".join(block))
    return n_valid, errors


def _main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: python -m benchmark.validators <dataset.json>", file=sys.stderr)
        return 2
    path = Path(argv[1])
    raw = json.loads(path.read_text())
    dataset = BenchmarkDataset.model_validate(raw)
    n_valid, errors = asyncio.run(validate_dataset(dataset))
    total = len(dataset.problems)
    if errors:
        print(f"VALIDATION FAILURES ({total - n_valid}/{total}):")
        for err in errors:
            print()
            print(err)
        print()
    print(f"All {n_valid}/{total} problems valid: schema OK, reference solutions verified.")
    return 0 if n_valid == total else 1


if __name__ == "__main__":
    sys.exit(_main(sys.argv))
