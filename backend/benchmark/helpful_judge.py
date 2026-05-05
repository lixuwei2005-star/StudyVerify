"""LLM-student-simulator: would this hint help a student fix the bug?

We ask DeepSeek to roleplay as a student looking at the buggy code and the
hint, then output a structured JSON describing whether it understood the
hint and whether it would now produce a correct fix.

Tightened in Phase B: the student must quote at least 5 consecutive words
from the hint text in `proposed_change`. If they cannot, would_fix is
forced to False — this discounts the case where the LLM-student brings
its own training-data knowledge instead of actually using the hint, which
saturated the metric at 100% across all hint levels in the Phase A smoke.
"""

from __future__ import annotations

import json
import re
from typing import Any

from app.llm.gateway import LLMGateway

QUOTE_WORD_THRESHOLD = 5

_PROMPT_TEMPLATE = """You are roleplaying as a student debugging Python code.

You're working on this problem:
{problem_text}

Your current (buggy) code:
```python
{buggy_code}
```

You just received this hint #{hint_index} from an AI tutor:
"{hint_text}"

Based ONLY on this hint (no outside Python knowledge), what would you change
in the code?

IMPORTANT: Your "proposed_change" field MUST quote at least 5 consecutive
words verbatim from the hint above. If you cannot quote 5 consecutive words
from the hint that informed your change, set would_fix_bug to false — the
hint did not give you enough specific guidance to produce a fix on its own.

Respond with valid JSON ONLY:
{{"understood_hint": true, "would_fix_bug": true, "proposed_change": "...quoting at least 5 consecutive words from the hint..."}}
or with false where appropriate.
"""

_TOKEN_RE = re.compile(r"\w+")


def _tokens(s: str) -> list[str]:
    return [m.group(0).lower() for m in _TOKEN_RE.finditer(s)]


def quotes_hint(proposed_change: str, hint_text: str, n: int = QUOTE_WORD_THRESHOLD) -> bool:
    """True iff `proposed_change` contains a verbatim run of n consecutive
    word-tokens from `hint_text`. Comparison is case-insensitive on alphanumeric
    tokens; punctuation and whitespace differences are ignored."""
    hint_words = _tokens(hint_text)
    change_words = _tokens(proposed_change)
    if len(hint_words) < n or len(change_words) < n:
        return False
    change_grams = {tuple(change_words[i : i + n]) for i in range(len(change_words) - n + 1)}
    for i in range(len(hint_words) - n + 1):
        if tuple(hint_words[i : i + n]) in change_grams:
            return True
    return False


async def check_helpful(
    problem_text: str,
    buggy_code: str,
    hint_text: str,
    hint_index: int,
    llm: LLMGateway,
) -> dict[str, Any]:
    prompt = _PROMPT_TEMPLATE.format(
        problem_text=problem_text,
        buggy_code=buggy_code,
        hint_index=hint_index,
        hint_text=hint_text,
    )
    try:
        raw = await llm.chat(
            [{"role": "user", "content": prompt}],
            json_mode=True,
            temperature=0.0,
        )
        data = json.loads(raw)
        proposed = str(data.get("proposed_change", ""))
        sim_would_fix = bool(data.get("would_fix_bug", False))
        # Quote-gate: discount cases where the LLM brought outside knowledge.
        quoted = quotes_hint(proposed, hint_text)
        would_fix = sim_would_fix and quoted
        return {
            "understood": bool(data.get("understood_hint", False)),
            "would_fix": would_fix,
            "sim_said_would_fix": sim_would_fix,
            "quoted_hint": quoted,
            "proposed_change": proposed,
            "judge_error": None,
        }
    except Exception as e:
        return {
            "understood": False,
            "would_fix": False,
            "sim_said_would_fix": False,
            "quoted_hint": False,
            "proposed_change": "",
            "judge_error": f"{type(e).__name__}: {e}",
        }
