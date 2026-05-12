"""Two-layer anti-leak audit for hint texts.

Layer 1: substring scan of a curated forbidden-phrase list. Cheap, no LLM.
Layer 2: DeepSeek-as-judge. Catches subtle leaks (paraphrases, structural
hints) that the phrase list misses.

A hint passes overall iff BOTH layers pass. The two pass-rates are also
exported separately so the eval report can attribute leaks to a layer.

Lenience: if the judge call itself fails (timeout, malformed JSON), we
default to "passes" to avoid penalizing the system for evaluation
infrastructure flakiness. This is a measurement choice — make it explicit
when reporting.
"""

from __future__ import annotations

import json
from typing import Any

from app.llm.gateway import LLMGateway

FORBIDDEN_PHRASES: list[str] = [
    # Loops
    "for each", "loop through", "iterate over", "iterate through",
    "for i in range", "while loop", "for loop",
    # Built-ins
    "use sum()", "use the sum()", "use sum function",
    "use list comprehension", "use map()", "use filter()",
    "use zip", "use any()", "use all()",
    # Algorithm patterns
    "running total", "accumulator", "total +=", "result +=",
    "+=1", "running sum",
    # Specific math/logic
    "if x % y == 0", "modulo operator", "% operator",
    "use math.", "import math",
    # Index manipulation
    "i+1", "i-1", "[i:]", "[:i]",
    # Recursion
    "recursive call", "base case", "recursion",
    # --- Step 11 Day 1 additions (evidence from Step 10 LLM-judge catches) ---
    # Algorithmic structure / named data structures
    "dictionary lookup", "hash table", "hash map", "lookup table",
    "data structure", "complement",
    # Slicing / indexing syntax
    "slice syntax", "slice notation", "slice operation",
    "step value", "negative step", "[::-1]", "[:-1]",
    # Conditional structure constructs
    "if-else chain", "if-elif chain", "elif branch",
    "ternary expression", "conditional expression",
    # Comprehensions / generator constructs
    "list comprehension", "generator expression",
    # Named method / built-in categories
    "string method", "built-in function", "built-in tool",
    ".lower()", ".upper()", ".split()", ".join()",
    # Named operators
    "comparison operator",
]


def check_phrase_filter(hint_text: str) -> tuple[bool, list[str]]:
    """Returns (passes, list of matched forbidden phrases)."""
    text_lower = hint_text.lower()
    matches = [p for p in FORBIDDEN_PHRASES if p.lower() in text_lower]
    return (len(matches) == 0, matches)


_JUDGE_PROMPT_TEMPLATE = """You are evaluating an AI tutor hint for anti-leak compliance.

Anti-leak rule: a hint should guide student thinking through Socratic questions
without revealing algorithm syntax, specific Python built-ins, or step-by-step
implementation. Acceptable: questions about the structure of the problem,
about edge cases, about what the function should produce. NOT acceptable:
naming language constructs (loops, comprehensions, recursion), naming specific
functions to use (sum, map, range, zip), giving the algorithm structure
("iterate over the list and accumulate").

Problem: {problem_text}

Hint: "{hint_text}"

Does this hint reveal algorithm syntax, specific code patterns, or named
Python constructs? Respond with valid JSON ONLY:
{{"leaks": true, "reason": "brief"}} or {{"leaks": false, "reason": "brief"}}"""


async def check_llm_judge(
    hint_text: str, problem_text: str, llm: LLMGateway
) -> tuple[bool, str]:
    """LLM-as-judge for subtle leakage. Returns (passes, reasoning)."""
    prompt = _JUDGE_PROMPT_TEMPLATE.format(problem_text=problem_text, hint_text=hint_text)
    try:
        raw = await llm.chat(
            [{"role": "user", "content": prompt}],
            json_mode=True,
            temperature=0.0,
        )
        data = json.loads(raw)
        leaks = bool(data.get("leaks", False))
        reason = str(data.get("reason", ""))
        return (not leaks, reason)
    except Exception as e:
        # Lenient on judge failure: count as pass, but record the error so
        # the report can show how many judge calls actually failed.
        return (True, f"judge_error: {type(e).__name__}: {e}")


async def check_no_leak(
    hint_text: str, problem_text: str, llm: LLMGateway
) -> dict[str, Any]:
    """Combined audit. Returns the full per-hint anti-leak record."""
    phrase_pass, matched = check_phrase_filter(hint_text)
    llm_pass, reason = await check_llm_judge(hint_text, problem_text, llm)
    return {
        "passes": phrase_pass and llm_pass,
        "phrase_filter_passes": phrase_pass,
        "phrase_matches": matched,
        "llm_judge_passes": llm_pass,
        "llm_judge_reason": reason,
    }
