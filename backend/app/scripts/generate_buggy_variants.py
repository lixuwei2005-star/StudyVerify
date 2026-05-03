"""Generate N candidate buggy implementations for one problem fixture (Step 6.3).

The output is for human review before it is saved to buggy_variants.json.
Discard duplicates, syntax-only failures, wrong-function-name variants, and
trivial constant-return variants unless they represent a useful beginner bug.

Run:
    cd backend
    uv run python -m app.scripts.generate_buggy_variants \
      --problem-id py-001-sum-list \
      --count 5 \
      --provider deepseek \
      --output tests/agents/fixtures/generated_py_001.json
"""

from __future__ import annotations

import argparse
import ast
import asyncio
import json
import logging
import sys
from pathlib import Path

from app.core.config import Settings, get_settings
from app.llm.exceptions import LLMError, LLMTimeoutError
from app.llm.gateway import LLMGateway
from app.llm.providers.base import ChatMessage, LLMProvider
from app.llm.providers.deepseek import DeepSeekProvider
from app.llm.providers.openai import OpenAIProvider

logger = logging.getLogger(__name__)

FIXTURE_PATH = (
    Path(__file__).resolve().parent.parent.parent
    / "tests"
    / "agents"
    / "fixtures"
    / "sample_problems.json"
)

BUG_CATEGORIES = (
    "off-by-one loops or indexing",
    "wrong empty-input/base-case handling",
    "wrong operator or comparison",
    "missing accumulator update",
    "wrong return value",
    "index error",
    "type confusion",
    "incorrectly mutating input",
)

SYSTEM_PROMPT = (
    "You are a Python tutor generating diverse beginner-mistake variants of a "
    "programming problem. Return ONLY a JSON object — no markdown, no preamble."
)


class GeneratorError(Exception):
    """Raised when validation fails twice in a row."""


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m app.scripts.generate_buggy_variants",
        description="Generate N candidate buggy implementations for one problem.",
    )
    parser.add_argument("--problem-id", required=True, help="e.g., py-001-sum-list")
    parser.add_argument("--count", type=int, default=5, help="variants to generate")
    parser.add_argument(
        "--provider",
        choices=("deepseek", "openai"),
        default="deepseek",
        help="LLM provider for this run (default: deepseek)",
    )
    parser.add_argument(
        "--model",
        default=None,
        help="optional model override (provider-specific). OpenAI manual override: gpt-4o-mini.",
    )
    parser.add_argument(
        "--output",
        default="-",
        help="output path; default '-' means stdout",
    )
    return parser


def _load_problem(problem_id: str) -> dict:
    problems = json.loads(FIXTURE_PATH.read_text())
    for p in problems:
        if p["problem_id"] == problem_id:
            return p
    raise SystemExit(
        f"problem_id={problem_id!r} not found in {FIXTURE_PATH}; "
        f"available: {[p['problem_id'] for p in problems]}"
    )


def _build_user_prompt(problem: dict, count: int) -> str:
    categories_block = "\n".join(f"- {cat}" for cat in BUG_CATEGORIES)
    return f"""Generate exactly {count} buggy candidate implementations of \
`{problem["entry_function"]}` for the following problem. Each variant must be \
a *plausible beginner mistake* — syntactically valid Python that defines \
`{problem["entry_function"]}` but produces wrong output for at least one test \
case.

PROBLEM:
{problem["problem_text"]}

REFERENCE (correct) SOLUTION:
{problem["reference_solution"]}

COMMON BUG CATEGORIES (use a different category per variant where possible):
{categories_block}

Return EXACTLY this JSON shape — a JSON object with key "variants" mapping to \
a JSON array. Each item has string keys "category" and "code". The list MUST \
have exactly {count} entries. No markdown, no preamble.

{{"variants": [{{"category": "...", "code": "def {problem["entry_function"]}(...):\\n    ..."}}]}}"""  # noqa: E501


def _retry_user_prompt(prior_error: str, count: int, entry_function: str) -> str:
    return (
        f"Previous response was malformed: {prior_error}\n\n"
        f"Return EXACTLY this shape — a JSON object whose top-level key "
        f'"variants" maps to a JSON array of {count} items. Each item has '
        f'string keys "category" and "code". The "code" string MUST define '
        f"the function `{entry_function}`. No markdown, no preamble, no "
        f"trailing text.\n\n"
        f'{{"variants": [{{"category": "...", "code": "..."}}]}}'
    )


def _build_gateway(provider: str, settings: Settings) -> LLMGateway:
    """Construct an ad-hoc one-provider gateway. Doesn't touch the cached singleton.

    Reuses LLMGateway's retry/backoff and the existing provider implementations,
    but disables fallback (the operator picked the provider explicitly).
    """
    primary: LLMProvider
    if provider == "openai":
        if not settings.OPENAI_API_KEY:
            raise SystemExit("--provider openai requires OPENAI_API_KEY in env")
        primary = OpenAIProvider(settings)
    else:
        primary = DeepSeekProvider(settings)
    return LLMGateway(primary=primary, fallback=None, fallback_enabled=False)


def _validate_payload(
    raw: str,
    *,
    count: int,
    entry_function: str,
) -> list[dict]:
    """Parse + validate the LLM response. Raises ValueError with a clear reason.

    On success returns the list of {category, code} dicts.
    """
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid JSON: {exc}") from exc

    if not isinstance(payload, dict):
        raise ValueError(f"expected top-level JSON object, got {type(payload).__name__}")

    variants = payload.get("variants")
    if not isinstance(variants, list):
        raise ValueError(f"missing 'variants' list; top-level keys: {sorted(payload.keys())}")

    if len(variants) != count:
        raise ValueError(f"expected {count} variants, got {len(variants)}")

    for i, v in enumerate(variants):
        if not isinstance(v, dict):
            raise ValueError(f"variant[{i}] is not an object: {type(v).__name__}")
        cat = v.get("category")
        code = v.get("code")
        if not isinstance(cat, str) or not cat.strip():
            raise ValueError(f"variant[{i}] missing/empty 'category' string")
        if not isinstance(code, str) or not code.strip():
            raise ValueError(f"variant[{i}] missing/empty 'code' string")
        try:
            tree = ast.parse(code)
        except SyntaxError as exc:
            raise ValueError(f"variant[{i}] code has SyntaxError: {exc}") from exc
        defined = {n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}
        if entry_function not in defined:
            raise ValueError(
                f"variant[{i}] code does not define {entry_function!r}; "
                f"defines {sorted(defined) or '[none]'}"
            )

    return variants


async def _generate(
    gateway: LLMGateway,
    *,
    problem: dict,
    count: int,
    model: str | None,
) -> list[dict]:
    """Two-attempt generate-and-validate. Raises GeneratorError on second failure."""

    user_prompt = _build_user_prompt(problem, count)
    messages: list[ChatMessage] = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ]

    last_error: str | None = None
    for attempt in (1, 2):
        try:
            raw = await gateway.chat(
                messages,
                model=model,
                temperature=0.7,
                json_mode=True,
            )
        except (LLMError, LLMTimeoutError) as exc:
            last_error = f"LLM call failed: {exc}"
            logger.warning("attempt %d: %s", attempt, last_error)
            if attempt == 2:
                raise GeneratorError(last_error) from exc
            continue

        try:
            return _validate_payload(
                raw,
                count=count,
                entry_function=problem["entry_function"],
            )
        except ValueError as exc:
            last_error = str(exc)
            logger.warning("attempt %d validation failed: %s", attempt, last_error)
            if attempt == 2:
                snippet = raw[:300].replace("\n", " ")
                raise GeneratorError(
                    f"validation failed twice; last error: {last_error}; raw[:300]={snippet!r}"
                )
            messages.append({"role": "assistant", "content": raw})
            messages.append(
                {
                    "role": "user",
                    "content": _retry_user_prompt(last_error, count, problem["entry_function"]),
                }
            )

    raise GeneratorError("exhausted retries without producing a result")  # unreachable


def _emit(variants: list[dict], output: str, problem_id: str) -> None:
    payload = {"problem_id": problem_id, "variants": variants}
    text = json.dumps(payload, indent=2) + "\n"
    if output == "-":
        sys.stdout.write(text)
        sys.stdout.flush()
    else:
        Path(output).write_text(text)


async def _run(args: argparse.Namespace) -> int:
    settings = get_settings()
    problem = _load_problem(args.problem_id)
    gateway = _build_gateway(args.provider, settings)
    try:
        variants = await _generate(
            gateway,
            problem=problem,
            count=args.count,
            model=args.model,
        )
    except GeneratorError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    _emit(variants, args.output, args.problem_id)
    return 0


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    args = _build_parser().parse_args(argv)
    return asyncio.run(_run(args))


if __name__ == "__main__":
    raise SystemExit(main())
