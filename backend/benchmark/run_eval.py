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
import random
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

_DEFAULT_CONCURRENCY = 3  # bounded parallelism over per-problem evaluations.
# DeepSeek caps at 60 RPS; one problem's peak in-flight is ~2 (judge calls
# pipelined with hint calls), so 3 concurrent problems stays comfortably
# under the limit.


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

    if args.problem_ids:
        requested_ids = set(args.problem_ids)
        targeted = [p for p in all_problems if p["id"] in requested_ids]
        missing_ids = sorted(requested_ids - {p["id"] for p in targeted})
        if missing_ids:
            print(f"Warning: problem IDs not found: {', '.join(missing_ids)}", flush=True)
        if args.sample_controls:
            pool = [p for p in all_problems if p["id"] not in requested_ids]
            n_controls = min(args.sample_controls, len(pool))
            targeted.extend(random.sample(pool, n_controls))
        all_problems = targeted

    if args.max_problems:
        all_problems = all_problems[: args.max_problems]

    print(
        f"Evaluating {len(all_problems)} problems against {args.api_base} "
        f"(concurrency={args.concurrency})...",
        flush=True,
    )
    api = StudyVerifyAPI(base_url=args.api_base)
    llm = get_llm_gateway()

    n = len(all_problems)
    sem = asyncio.Semaphore(args.concurrency)
    completed = 0

    async def _run_one(idx: int, problem: dict) -> dict:
        nonlocal completed
        async with sem:
            print(f"  [{idx:3d}/{n}] {problem['id']} ...started", flush=True)
            r = await evaluate_problem(problem, api, llm)
            completed += 1
            print(f"  [{idx:3d}/{n}] {problem['id']} ...done ({completed}/{n} complete)", flush=True)
            if completed % 10 == 0:
                print(f"    ...progress checkpoint at {completed}/{n}", flush=True)
            return r

    try:
        results = await asyncio.gather(
            *(_run_one(i, p) for i, p in enumerate(all_problems, start=1))
        )
        results = list(results)
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
    parser.add_argument(
        "--problem-ids",
        nargs="+",
        default=None,
        help="Only evaluate these problem IDs",
    )
    parser.add_argument(
        "--sample-controls",
        type=int,
        default=10,
        help="When --problem-ids is set, also add this many random outside-filter controls",
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=_DEFAULT_CONCURRENCY,
        help="Max concurrent per-problem evaluations (default 3). DeepSeek caps at 60 RPS.",
    )
    args = parser.parse_args()
    sys.exit(asyncio.run(_amain(args)))


if __name__ == "__main__":
    main()
