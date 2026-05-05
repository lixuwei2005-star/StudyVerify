"""LLM-student-simulator: would this hint help a student fix the bug?

We ask DeepSeek to roleplay as a student looking at the buggy code and the
hint, then output a structured JSON describing whether it understood the
hint and whether it would now produce a correct fix.

This is a measurement of hint *helpfulness at the right Bloom level*. Hint 1
should not give the answer (low would_fix is fine); hint 5 should escalate
toward a fix (higher would_fix is good). The progression curve across hint
indices is the resume-grade signal — not absolute would_fix at any one level.
"""

from __future__ import annotations

import json
from typing import Any

from app.llm.gateway import LLMGateway

_PROMPT_TEMPLATE = """You are roleplaying as a student debugging Python code.

You're working on this problem:
{problem_text}

Your current (buggy) code:
```python
{buggy_code}
```

You just received this hint #{hint_index} from an AI tutor:
"{hint_text}"

Based ONLY on this hint (no other knowledge), what would you change in the code?
Respond with valid JSON ONLY:
{{"understood_hint": true, "would_fix_bug": true, "proposed_change": "brief description"}}
or with false where appropriate.
"""


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
        return {
            "understood": bool(data.get("understood_hint", False)),
            "would_fix": bool(data.get("would_fix_bug", False)),
            "proposed_change": str(data.get("proposed_change", "")),
            "judge_error": None,
        }
    except Exception as e:
        return {
            "understood": False,
            "would_fix": False,
            "proposed_change": "",
            "judge_error": f"{type(e).__name__}: {e}",
        }
