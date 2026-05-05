"""Generate Python test cases for a user-described problem via the LLM gateway.

User-uploaded custom problems flow: the user types a natural-language problem
description and an entry-function name; we ask the LLM for n test cases the
user then reviews/edits before saving the problem. No persistence here — the
output is returned to the caller and the user owns the next step.

Anti-leak filtering does NOT apply: test cases ARE meant to reveal expected
outputs (their entire purpose). The /verify and /hint endpoints, not this
one, are where the leak guard belongs.
"""

from __future__ import annotations

import json
import logging

from pydantic import TypeAdapter, ValidationError

from app.agents.solver.schemas import TestCase
from app.llm.gateway import LLMGateway
from app.llm.providers.base import ChatMessage

logger = logging.getLogger("app.services.test_case_generator")

_TEST_CASES_ADAPTER = TypeAdapter(list[TestCase])
_SNIPPET_LEN = 200

_SYSTEM_PROMPT = (
    "You are a test case generator for Python programming problems. You return "
    "ONLY a single valid JSON object — no markdown fences, no commentary, no "
    "preamble. Test descriptions name the scenario only (e.g. 'empty list', "
    "'single element', 'large input') and never explain why an answer is correct."
)


class TestCaseGeneratorError(Exception):
    """Raised when the LLM output cannot be parsed into valid test cases after one retry."""

    __test__ = False  # not a pytest collection target despite the name


class TestCaseGeneratorService:
    __test__ = False  # not a pytest collection target despite the name

    def __init__(self, llm: LLMGateway) -> None:
        self._llm = llm

    async def generate(
        self,
        problem_text: str,
        entry_function: str,
        n: int = 5,
    ) -> list[TestCase]:
        prompt = self._build_prompt(problem_text, entry_function, n)
        messages: list[ChatMessage] = [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ]

        # One retry only — same prompt. LLMGateway already retries transient
        # provider failures internally; this retry covers JSON-shape failures
        # (malformed JSON, wrong keys, bad TestCase fields) which a re-prompt
        # of the same call may resolve. Two attempts is the cap.
        last_error: str | None = None
        for attempt in (1, 2):
            raw = await self._llm.chat(messages, temperature=0.4, json_mode=True)
            try:
                return self._parse(raw, n)
            except TestCaseGeneratorError as exc:
                last_error = str(exc)
                logger.warning(
                    "test_case_generator.parse_failed attempt=%d entry_function=%s err=%s",
                    attempt,
                    entry_function,
                    last_error,
                )
        raise TestCaseGeneratorError(
            f"failed to parse test cases after retry: {last_error}"
        )

    @staticmethod
    def _build_prompt(problem_text: str, entry_function: str, n: int) -> str:
        return (
            f"Generate {n} test cases for this Python problem.\n\n"
            f"Problem description: {problem_text}\n"
            f"Function name: {entry_function}\n\n"
            "Return JSON in EXACTLY this format:\n"
            "{\n"
            '  "test_cases": [\n'
            "    {\n"
            '      "input": "<Python literal expression as a string, e.g. \\"[1,2,3]\\" '
            'or \\"5\\" or \\"\'hello\'\\". For multi-arg functions use a tuple: '
            '\\"(arg1, arg2)\\">",\n'
            '      "expected": "<repr() of the function\'s return value as a string>",\n'
            '      "description": "<short scenario name only — e.g. \'empty list\', '
            "'single element', 'normal case', 'boundary value'. Do NOT explain why "
            'the expected value is correct>"\n'
            "    }\n"
            "  ]\n"
            "}\n\n"
            "Rules:\n"
            "- input is what eval() will produce as the function argument\n"
            "- expected is the literal repr() of the function's return\n"
            f"- Cover diverse scenarios: empty input, single element, normal cases, boundary values\n"
            f"- Generate exactly {n} test cases\n"
            "- Return ONLY the JSON object, no markdown fences, no commentary"
        )

    @staticmethod
    def _parse(raw: str, expected_n: int) -> list[TestCase]:
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise TestCaseGeneratorError(
                f"invalid JSON: {exc}; got: {raw[:_SNIPPET_LEN]!r}"
            ) from exc

        if not isinstance(payload, dict):
            raise TestCaseGeneratorError(
                f"expected JSON object, got {type(payload).__name__}"
            )
        cases_raw = payload.get("test_cases")
        if not isinstance(cases_raw, list):
            raise TestCaseGeneratorError(
                f"missing 'test_cases' list; got keys={list(payload)}"
            )

        try:
            cases = _TEST_CASES_ADAPTER.validate_python(cases_raw)
        except ValidationError as exc:
            raise TestCaseGeneratorError(f"test_cases shape invalid: {exc}") from exc

        if len(cases) != expected_n:
            raise TestCaseGeneratorError(
                f"expected {expected_n} test cases, got {len(cases)}"
            )
        return cases
