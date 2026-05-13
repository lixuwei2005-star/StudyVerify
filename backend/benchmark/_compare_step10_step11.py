"""Compare Step 10 vs Step 11 eval JSONs for the Step 11 re-eval report.

Outputs:
- headline metrics delta
- per-topic anti-leak shift
- top "leaked-then-fixed" hint examples

Usage: uv run python -m benchmark._compare_step10_step11 OLD.json NEW.json [--max-examples N]
"""
from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path


def load(p: str) -> dict:
    return json.loads(Path(p).read_text())


def iter_hints(eval_json: dict):
    for prob in eval_json["per_problem_results"]:
        pid = prob["problem_id"]
        topics = prob.get("topics") or []
        for variant in prob.get("variants") or []:
            vname = variant.get("name", "?")
            for hint in variant.get("hints") or []:
                if not hint.get("success"):
                    continue
                yield pid, topics, vname, hint


def index_hints(eval_json: dict) -> dict[tuple, dict]:
    out: dict[tuple, dict] = {}
    for pid, topics, vname, hint in iter_hints(eval_json):
        key = (pid, vname, hint["index"])
        out[key] = {"topics": topics, "hint": hint}
    return out


def fmt_pct(x: float | None) -> str:
    return "n/a" if x is None else f"{100*x:.1f}%"


def delta_pp(new: float | None, old: float | None) -> str:
    if new is None or old is None:
        return "n/a"
    d = 100 * (new - old)
    sign = "+" if d >= 0 else ""
    return f"{sign}{d:.1f} pp"


def headline_table(old: dict, new: dict) -> str:
    o, n = old["summary"], new["summary"]
    rows = [
        ("Verifier accuracy", o["verifier_accuracy"], n["verifier_accuracy"]),
        ("Anti-leak combined", o["anti_leak_success_rate"], n["anti_leak_success_rate"]),
        ("↳ Phrase filter", o["anti_leak_phrase_filter_rate"], n["anti_leak_phrase_filter_rate"]),
        ("↳ LLM judge", o["anti_leak_llm_judge_rate"], n["anti_leak_llm_judge_rate"]),
        ("Helpfulness hint_1", o["helpfulness_progression"]["hint_1"], n["helpfulness_progression"]["hint_1"]),
        ("Helpfulness hint_5", o["helpfulness_progression"]["hint_5"], n["helpfulness_progression"]["hint_5"]),
    ]
    out = ["| Metric | Step 10 | Step 11 | Δ |", "|---|---:|---:|---:|"]
    for label, ov, nv in rows:
        out.append(f"| {label} | {fmt_pct(ov)} | {fmt_pct(nv)} | {delta_pp(nv, ov)} |")
    # latency
    out.append(
        f"| Latency p95 solve | {o['latency']['solve_p95_ms']/1000:.0f}s "
        f"| {n['latency']['solve_p95_ms']/1000:.0f}s | — |"
    )
    return "\n".join(out)


def per_topic_anti_leak(eval_json: dict) -> dict[str, tuple[int, int]]:
    """Return topic -> (n_pass, n_total) for anti_leak.passes across hints whose
    parent problem lists that topic."""
    counts: dict[str, list[int]] = defaultdict(lambda: [0, 0])  # [pass, total]
    for pid, topics, vname, hint in iter_hints(eval_json):
        al = hint.get("anti_leak") or {}
        passes = bool(al.get("passes"))
        for t in topics:
            counts[t][0] += int(passes)
            counts[t][1] += 1
    return {t: (p, tot) for t, (p, tot) in counts.items()}


def topic_shift_table(old: dict, new: dict) -> str:
    old_t = per_topic_anti_leak(old)
    new_t = per_topic_anti_leak(new)
    topics = sorted(set(old_t) | set(new_t))
    rows = []
    for t in topics:
        op, otot = old_t.get(t, (0, 0))
        np_, ntot = new_t.get(t, (0, 0))
        old_rate = op / otot if otot else None
        new_rate = np_ / ntot if ntot else None
        rows.append((t, otot, ntot, old_rate, new_rate, (new_rate or 0) - (old_rate or 0)))
    rows.sort(key=lambda r: -r[5])  # largest improvement first
    out = ["| Topic | n hints (S10 / S11) | Anti-leak S10 | Anti-leak S11 | Δ |", "|---|---:|---:|---:|---:|"]
    for t, otot, ntot, ov, nv, _d in rows:
        out.append(f"| {t} | {otot} / {ntot} | {fmt_pct(ov)} | {fmt_pct(nv)} | {delta_pp(nv, ov)} |")
    return "\n".join(out)


def leaked_then_fixed_examples(old: dict, new: dict, max_n: int = 5) -> list[dict]:
    old_idx = index_hints(old)
    new_idx = index_hints(new)
    examples = []
    for key, old_rec in old_idx.items():
        new_rec = new_idx.get(key)
        if not new_rec:
            continue
        old_al = old_rec["hint"].get("anti_leak") or {}
        new_al = new_rec["hint"].get("anti_leak") or {}
        if old_al.get("passes") is False and new_al.get("passes") is True:
            examples.append({
                "problem_id": key[0],
                "variant": key[1],
                "hint_index": key[2],
                "topics": new_rec["topics"],
                "old_text": old_rec["hint"].get("text", ""),
                "new_text": new_rec["hint"].get("text", ""),
                "old_judge_reason": old_al.get("llm_judge_reason"),
                "old_phrase_matches": old_al.get("phrase_matches"),
            })
    # Prefer ones in our targeted topics
    targeted = {"recursion", "two-pointers", "linked-list", "tree", "set", "hash-table", "prefix-sum"}
    examples.sort(key=lambda e: (-len(set(e["topics"]) & targeted), e["problem_id"]))
    return examples[:max_n]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("old")
    ap.add_argument("new")
    ap.add_argument("--max-examples", type=int, default=5)
    args = ap.parse_args()
    old = load(args.old)
    new = load(args.new)

    print("## Headline (Step 10 → Step 11)\n")
    print(headline_table(old, new))
    print("\n## Per-topic anti-leak shift\n")
    print(topic_shift_table(old, new))
    print("\n## Leaked-then-fixed examples\n")
    for ex in leaked_then_fixed_examples(old, new, args.max_examples):
        print(f"### {ex['problem_id']} / {ex['variant']} / hint_{ex['hint_index']}")
        print(f"topics: {ex['topics']}")
        print(f"Step 10 hint (leaked): {ex['old_text']}")
        print(f"Step 10 judge reason: {ex['old_judge_reason']}")
        print(f"Step 10 phrase matches: {ex['old_phrase_matches']}")
        print(f"Step 11 hint (clean):  {ex['new_text']}")
        print()


if __name__ == "__main__":
    main()
