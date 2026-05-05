"""CLI entry point: load benchmark, run pipeline against prod backend, write JSON.

    uv run python -m benchmark.run_eval [--max-problems N] [--datasets a.json b.json]

Output: benchmark/results/<UTC-timestamp>_eval.json plus a printed summary.
Datasets default to all three Phase-1/2/3 files (100 problems total).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from app.llm.gateway import get_llm_gateway

from benchmark.aggregate import aggregate_results
from benchmark.api_client import StudyVerifyAPI
from benchmark.eval_pipeline import evaluate_problem

_DEFAULT_DATASETS = [
    "benchmark/problems_part_1.json",
    "benchmark/problems_part_2.json",
    "benchmark/problems_part_3.json",
]


def _git_sha() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    except Exception:
        return "unknown"


def _print_summary(summary: dict) -> None:
    L = summary["latency"]
    print()
    print("=" * 60)
    print("EVALUATION COMPLETE")
    print("=" * 60)
    print(f"Problems evaluated:        {summary['total_problems']}")
    print(f"Verifier judgments:        {summary['totals']['verifier_judgments']}")
    print(f"Hints evaluated:           {summary['totals']['hints_evaluated']}")
    print()
    print(f"Verifier accuracy:         {summary['verifier_accuracy']:.1%}")
    print(f"Anti-leak success:         {summary['anti_leak_success_rate']:.1%}")
    print(f"  Phrase filter:           {summary['anti_leak_phrase_filter_rate']:.1%}")
    print(f"  LLM judge:               {summary['anti_leak_llm_judge_rate']:.1%}")
    print()
    print("Helpfulness progression (would-fix-bug rate per hint level):")
    for idx, rate in summary["helpfulness_progression"].items():
        print(f"  {idx}: {rate:.1%}")
    print()
    print("Latency P50 / P95:")
    print(f"  /solve  : {L['solve_p50_ms']/1000:5.1f}s / {L['solve_p95_ms']/1000:5.1f}s")
    print(f"  /verify : {L['verify_p50_ms']/1000:5.1f}s / {L['verify_p95_ms']/1000:5.1f}s")
    print(f"  /hint   : {L['hint_p50_ms']/1000:5.1f}s / {L['hint_p95_ms']/1000:5.1f}s")
    print()
    print(f"Errors: solve={summary['error_summary']['solve_failures']} "
          f"verify={summary['error_summary']['verify_failures']} "
          f"hint={summary['error_summary']['hint_failures']}")
    print(f"Judge call errors: anti-leak={summary['totals']['anti_leak_judge_errors']} "
          f"helpfulness={summary['totals']['helpfulness_judge_errors']}")
    print("=" * 60)


async def _amain(args: argparse.Namespace) -> int:
    all_problems: list[dict] = []
    for path in args.datasets:
        with open(path) as f:
            data = json.load(f)
            all_problems.extend(data["problems"])

    if args.max_problems:
        all_problems = all_problems[: args.max_problems]

    print(f"Evaluating {len(all_problems)} problems against {args.api_base}...")
    api = StudyVerifyAPI(base_url=args.api_base)
    llm = get_llm_gateway()

    results: list[dict] = []
    try:
        for i, problem in enumerate(all_problems, start=1):
            print(f"  [{i:3d}/{len(all_problems)}] {problem['id']}", flush=True)
            r = await evaluate_problem(problem, api, llm)
            results.append(r)
            if i % 10 == 0:
                print(f"    ...progress checkpoint at {i}/{len(all_problems)}", flush=True)
    finally:
        await api.close()

    summary = aggregate_results(results)

    out_dir = Path("benchmark/results")
    out_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d_%H-%M-%S")
    out_path = Path(args.output) if args.output else out_dir / f"{timestamp}_eval.json"
    output = {
        "ran_at_utc": timestamp,
        "git_sha": _git_sha(),
        "api_base": args.api_base,
        "datasets": args.datasets,
        "n_problems": len(all_problems),
        "summary": summary,
        "per_problem_results": results,
    }
    out_path.write_text(json.dumps(output, indent=2))

    _print_summary(summary)
    print(f"Wrote {out_path}")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--datasets", nargs="+", default=_DEFAULT_DATASETS)
    parser.add_argument("--max-problems", type=int, default=None)
    parser.add_argument("--output", default=None)
    parser.add_argument("--api-base", default="https://api.005917.xyz")
    args = parser.parse_args()
    sys.exit(asyncio.run(_amain(args)))


if __name__ == "__main__":
    main()
