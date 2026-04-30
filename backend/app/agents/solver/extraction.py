from __future__ import annotations

import re

_DEF_PATTERN = re.compile(r"^(?:async\s+)?def\s+([A-Za-z_]\w*)\s*\(", re.MULTILINE)


class EntryFunctionExtractionError(ValueError):
    pass


def extract_entry_function(code: str, problem_id: str) -> str:
    match = _DEF_PATTERN.search(code.lstrip("﻿"))
    if not match:
        raise EntryFunctionExtractionError(
            f"problem_id={problem_id}: no top-level function definition found"
        )
    return match.group(1)
