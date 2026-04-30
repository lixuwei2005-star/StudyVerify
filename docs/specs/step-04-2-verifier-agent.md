# StudyVerify — Step 4.2: Verifier Agent Spec

## Goal
Implement `VerifierAgent` — a stateless agent that evaluates 
student-submitted code against test cases, runs it in the 
hardened Docker sandbox from 4.1, and generates LLM-based 
diagnostic feedback when tests fail. Mirror the architectural 
pattern of `SolverAgent` (Step 2) so testing, DI, and persistence 
patterns transfer cleanly to 4.3.

## Why This Step
After 4.1, we have a Docker sandbox capable of safely running 
untrusted code. After this step, we have a complete agent that:
- Accepts a problem definition + student code
- Runs the student code in isolation
- Returns student-facing per-test results without leaking expected 
  answers
- On ordinary wrong-answer failures, generates targeted diagnostic 
  feedback without revealing the correct implementation

## Architecture

````
VerifierAgent.verify(input) -> VerifierOutput
   |
   |- 1. Run student code in DockerCodeRunner (4.1)
   |     -> SandboxRunResult
   |
   |- 2. Convert raw sandbox test results to RedactedTestResult
   |     pass_count / fail_count / student-facing per-test details
   |
   `- 3. Branch by sandbox status
         all_passed  -> diagnosis = ""
         some_failed -> call LLM only if failed test results exist
         timeout     -> deterministic timeout diagnosis, no LLM
         error       -> sandbox_error only, no LLM

VerifierAgent has no DB access, no FastAPI knowledge, no 
session/state. It is a pure function from VerifierInput to 
VerifierOutput. Step 4.3 will add VerifierService that wraps 
this agent with DB persistence.
````

## Scope

- Pydantic schemas: `VerifierInput`, `RedactedTestResult`, 
  `VerifierOutput`
- `VerifierAgent` class with constructor injection (sandbox runner 
  + DeepSeek client)
- `build_diagnosis_prompt` strict prompt construction
- DI factory `get_verifier_agent`
- Unit tests (mocked LLM + mocked sandbox)
- Integration test (real LLM + real Docker, gated)

## Out of Scope (this step)
- ❌ Persistence — Step 4.3 (verifier_sessions table + Repository 
  + Service)
- ❌ FastAPI route `/api/v1/verify` — Step 4.3
- ❌ Linkage to solver_session in DB — Step 4.3 Service composes 
  the input
- ❌ Multi-turn dialog with student — Step 5 Hint Agent territory
- ❌ LangGraph orchestration — Step 5
- ❌ Style or quality feedback (e.g., "your code is hard to read") 
  — out of scope; we only check correctness

## Files to Create / Modify

### New
- `backend/app/agents/verifier/__init__.py`
- `backend/app/agents/verifier/schemas.py` — VerifierInput, 
  RedactedTestResult, VerifierOutput
- `backend/app/agents/verifier/prompts.py` — strict diagnostic 
  prompt + examples
- `backend/app/agents/verifier/agent.py` — VerifierAgent class 
  + get_verifier_agent factory
- `backend/tests/agents/test_verifier.py` — unit tests
- `backend/tests/agents/test_verifier_integration.py` — 
  integration tests

### Modified
- `backend/app/dependencies.py` — import/re-export 
  `get_verifier_agent` for future Step 4.3 service consumption

## Pydantic Schemas

````python
# app/agents/verifier/schemas.py

from pydantic import BaseModel, Field

from app.agents.solver.schemas import TestCase
from app.sandbox.schemas import SandboxStatus


class VerifierInput(BaseModel):
    """Stateless input. The 4.3 service composes this from a 
    persisted solver_session + caller-supplied student code.
    """
    problem_id: str
    problem_text: str
    entry_function: str = Field(
        description="The Python function name the student must "
                    "implement; tests will call this function."
    )
    test_cases: list[TestCase] = Field(
        description="Same typed test case shape used by Solver: "
                    "{input: str, expected: str, description: str}."
    )
    student_code: str


class RedactedTestResult(BaseModel):
    """Student-facing per-test result. Deliberately omits 'expected' 
    so API responses cannot leak the answer. Keep input visible 
    (students saw it when running) and actual (their own output).
    """
    input: str
    actual: str | None
    passed: bool
    duration_ms: int | None = None
    error: str | None = None


class VerifierOutput(BaseModel):
    problem_id: str

    # Outcome
    verified: bool = Field(
        description="True iff student code passed ALL test cases"
    )
    status: SandboxStatus  # all_passed / some_failed / error / timeout
    pass_count: int = Field(ge=0)
    fail_count: int = Field(ge=0)
    test_results: list[RedactedTestResult] = Field(default_factory=list)

    # LLM-generated or deterministic feedback
    diagnosis: str = Field(
        default="",
        description="Targeted diagnostic feedback for the student. "
                    "Empty when verified=True or when sandbox status is "
                    "error with no per-test signal."
    )

    # Provenance
    sandbox_error: str | None = Field(
        default=None,
        description="If sandbox failed at infra/status level (timeout, "
                    "OOM, syntax error preventing execution), the error "
                    "string lives here. test_results may be empty."
    )
````

### Why redact?

The raw sandbox result includes `expected`, which is required inside 
the sandbox to determine pass/fail. Returning that raw object through 
the verifier API would undo prompt-level redaction by leaking answers 
directly in `VerifierOutput.test_results`. The verifier must therefore 
convert raw sandbox rows to `RedactedTestResult` before returning them 
to callers.

### Why typed test_cases?

`VerifierInput.test_cases` should use Solver's `TestCase` model so 
the Verifier validates the same `{input, expected, description}` 
shape at its boundary. This also makes Step 4.3 easier: persisted 
JSONB test cases can round-trip through Pydantic cleanly before being 
dumped back to plain dicts for the sandbox.

## VerifierAgent Class

````python
# app/agents/verifier/agent.py

import logging
from functools import lru_cache

from app.agents.verifier.prompts import build_diagnosis_prompt
from app.agents.verifier.schemas import (
    RedactedTestResult,
    VerifierInput,
    VerifierOutput,
)
from app.llm.client import DeepSeekClient, get_llm_client
from app.llm.exceptions import LLMError
from app.sandbox.docker_runner import DockerCodeRunner
from app.sandbox.schemas import SandboxRunRequest, SandboxRunResult

logger = logging.getLogger(__name__)

TIMEOUT_DIAGNOSIS = (
    "Your code did not complete within the time limit. Look for "
    "infinite loops or excessive computation."
)


class VerifierError(Exception):
    """Raised when verification cannot complete due to upstream 
    sandbox infra failure, such as Docker being unavailable.
    """


class VerifierAgent:
    """Stateless verifier. Constructor-injected dependencies.

    A single cached instance can serve concurrent requests because the
    Docker runner creates a fresh container per call and the agent keeps
    no request-local mutable state.
    """

    def __init__(
        self,
        sandbox_runner: DockerCodeRunner,
        llm_client: DeepSeekClient,
    ) -> None:
        self.sandbox = sandbox_runner
        self.llm = llm_client

    async def verify(self, input: VerifierInput) -> VerifierOutput:
        """Run student code and diagnose ordinary wrong-answer failures."""

        try:
            sandbox_result = await self.sandbox.run(
                SandboxRunRequest(
                    code=input.student_code,
                    entry_function=input.entry_function,
                    test_cases=[tc.model_dump() for tc in input.test_cases],
                    timeout_seconds=5,
                    memory_mb=128,
                )
            )
        except Exception as exc:
            # Sandbox infra failure (Docker daemon down, image missing, etc.)
            # is not the student's fault and should surface clearly.
            logger.exception(
                "Sandbox infra failure for problem=%s", input.problem_id
            )
            raise VerifierError(
                f"Sandbox unavailable: {type(exc).__name__}"
            ) from exc

        redacted_results = self._redact_results(sandbox_result)
        diagnosis = ""
        sandbox_error = sandbox_result.error
        verified = sandbox_result.status == "all_passed"

        if sandbox_result.status == "all_passed":
            diagnosis = ""
        elif sandbox_result.status == "error":
            # Syntax/load/wrapper errors have no per-test signal to diagnose.
            diagnosis = ""
        elif sandbox_result.status == "timeout":
            # Timeout is deterministic and should not spend LLM tokens.
            diagnosis = TIMEOUT_DIAGNOSIS
        elif sandbox_result.status == "some_failed":
            failed_tests = [tr for tr in sandbox_result.test_results if not tr.passed]
            if failed_tests:
                try:
                    diagnosis = await self._generate_diagnosis(input, failed_tests)
                except LLMError as exc:
                    # LLM down — degrade gracefully; student still gets
                    # pass/fail counts and redacted per-test details.
                    logger.warning(
                        "Diagnosis generation failed for problem=%s: %s",
                        input.problem_id,
                        exc,
                    )
                    diagnosis = (
                        "Tests failed; detailed feedback unavailable "
                        "right now. Review the failing test inputs above."
                    )

        return VerifierOutput(
            problem_id=input.problem_id,
            verified=verified,
            status=sandbox_result.status,
            pass_count=sandbox_result.pass_count,
            fail_count=sandbox_result.fail_count,
            test_results=redacted_results,
            diagnosis=diagnosis,
            sandbox_error=sandbox_error,
        )

    async def _generate_diagnosis(self, input: VerifierInput, failed_tests: list) -> str:
        """Build prompt, call LLM, return diagnosis text."""
        prompt = build_diagnosis_prompt(
            problem_text=input.problem_text,
            student_code=input.student_code,
            failed_tests=failed_tests,
        )

        response = await self.llm.chat(
            messages=[
                {"role": "system", "content": prompt["system"]},
                {"role": "user", "content": prompt["user"]},
            ],
            temperature=0.3,
            json_mode=False,
        )
        return response.strip()

    @staticmethod
    def _redact_results(result: SandboxRunResult) -> list[RedactedTestResult]:
        return [
            RedactedTestResult(
                input=tr.input,
                actual=tr.actual,
                passed=tr.passed,
                duration_ms=tr.duration_ms,
                error=tr.error,
            )
            for tr in result.test_results
        ]


@lru_cache
def get_verifier_agent() -> VerifierAgent:
    """Cached factory. Verifier is stateless; one instance serves 
    all requests."""
    return VerifierAgent(
        sandbox_runner=DockerCodeRunner(),
        llm_client=get_llm_client(),
    )
````

## Diagnostic Prompt (`prompts.py`)

````python
# app/agents/verifier/prompts.py

DIAGNOSIS_SYSTEM_PROMPT = """You are a coding tutor reviewing a 
student's submission. Some test cases failed. Your job is to give 
targeted, educational feedback.

CRITICAL RULES:
1. DO NOT write any code in your response. Not even a snippet. 
   Not even pseudocode that closely resembles the fix.
2. DO NOT show the correct output for failing tests. Show only 
   the input that failed.
3. DO NOT reveal what the student should literally write.
4. Describe WHAT is wrong (what the symptom is) and HINT at the 
   root cause. Let the student think.
5. Keep responses to 1-3 sentences.
6. No greetings, no "great attempt".
7. If multiple tests fail, identify the common root cause if 
   there is one; otherwise mention the most instructive failure.

Example of GOOD feedback:
"Your function's behavior on empty input differs from what the 
problem requires. Re-read the problem statement and consider what 
should happen when there are no elements."
(GOOD because it describes the symptom without revealing the 
required output.)

Example of BAD feedback (DO NOT do this):
"Change line 3 to `return -1 if not items else max(items)`. The 
issue is your default return value."
(BAD because it gives the literal code.)

Another BAD example:
"For input [], the expected output is -1, not 0."
(BAD because it reveals the expected output.)
"""


def build_diagnosis_prompt(
    problem_text: str,
    student_code: str,
    failed_tests: list,
) -> dict:
    """Returns {'system': ..., 'user': ...} for chat completion."""

    failures_text = "\n\n".join(
        f"FAILED TEST {i + 1}\n"
        f"  Input: {tr.input}\n"
        f"  Student's output: {tr.actual}\n"
        f"  {'Error: ' + tr.error if tr.error else ''}".rstrip()
        for i, tr in enumerate(failed_tests[:3])
    )

    user_message = f"""PROBLEM:
{problem_text}

STUDENT'S CODE:
```python
{student_code}
```

{failures_text}

Provide diagnostic feedback per the rules in the system message."""

    return {
        "system": DIAGNOSIS_SYSTEM_PROMPT,
        "user": user_message,
    }
````

The prompt deliberately omits the raw `expected` field. It also 
omits `test_case.description`: descriptions are authored for problem 
authors and may state the expected behavior literally, such as 
"empty list returns None."

Send up to 3 representative failed tests, preserving the original 
test order. We rely on test authors ordering tests basic-to-edge so 
that the first failure is the most instructive. If the test order 
is randomized or reverse-sorted, diagnosis quality degrades — that's 
a problem-authoring concern, not a runtime concern.

`temperature=0.3` is reasonable for diagnosis because the model needs 
some flexibility to phrase a helpful hint while staying focused and 
repeatable. The current `DeepSeekClient.chat(...)` interface does not 
support a completion length parameter, so brevity is enforced through 
the prompt rule. If a hard length cap becomes necessary, add it as a 
future `DeepSeekClient` enhancement rather than assuming it exists.

## Error Handling Decision Tree

1. Sandbox runner raises an exception, such as Docker daemon down:
   raise `VerifierError("Sandbox unavailable: ...")` with the 
   original exception chained.

2. `sandbox_result.status == "error"`:
   return `VerifierOutput(verified=False, diagnosis="", 
   sandbox_error=sandbox_result.error)`. Do not call the LLM because 
   there is no reliable per-test signal to diagnose.

3. `sandbox_result.status == "timeout"`:
   return `VerifierOutput(verified=False, diagnosis=TIMEOUT_DIAGNOSIS, 
   sandbox_error=sandbox_result.error)`. Do not call the LLM because 
   timeout is deterministic and usually means an infinite loop or 
   excessive computation.

4. `sandbox_result.status == "some_failed"`:
   compute `failed_tests = [tr for tr in test_results if not tr.passed]`.
   If the list is empty, return `diagnosis=""` defensively. Otherwise 
   call the LLM. If the LLM raises `LLMError`, return the fallback 
   diagnosis while preserving pass/fail counts and redacted results.

5. `sandbox_result.status == "all_passed"`:
   return `verified=True`, `diagnosis=""`, and do not call the LLM.

## DI Factory Update

`backend/app/dependencies.py` currently has no explicit `__all__`. Add 
a simple import/re-export:

````python
from app.agents.verifier.agent import get_verifier_agent  # re-exported for 4.3 service consumption
````

No `__all__` manipulation is needed in 4.2. If 4.3 introduces an 
explicit `__all__` pattern, add the entry properly at that point.

## Test Strategy

### Unit tests (`test_verifier.py`, `not integration`)

Mock the sandbox runner with `AsyncMock(spec=DockerCodeRunner)` 
and the LLM client with `AsyncMock(spec=DeepSeekClient)`. Verify 
orchestration logic without needing real Docker or real LLM.

1. **`test_all_pass_returns_verified_true_no_diagnosis`**:
   - Mock sandbox returns status="all_passed", pass=3, fail=0
   - Assert verified=True, diagnosis=""
   - Assert `llm.chat` was NOT called

2. **`test_some_fail_calls_llm_for_diagnosis`**:
   - Mock sandbox returns some_failed, 1 fail
   - Mock LLM returns "your function ignores edge case"
   - Assert verified=False, diagnosis present
   - Assert `llm.chat` was called exactly once

3. **`test_sandbox_infra_error_raises_verifier_error`**:
   - Mock sandbox.run to raise (e.g., Docker daemon down)
   - Assert VerifierError raised; original exception chained

4. **`test_llm_error_degrades_gracefully`**:
   - Mock sandbox returns some_failed
   - Mock `llm.chat` raises LLMError
   - Assert VerifierOutput still returned with verified=False, 
     fallback diagnosis text, no exception propagated

5. **`test_sandbox_returns_status_error`**:
   - Mock sandbox returns status="error" (e.g., student code 
     SyntaxError)
   - Assert verified=False, diagnosis="" (no LLM call), 
     sandbox_error populated

6. **`test_only_failed_tests_in_prompt`**:
   - 3 tests, 2 pass, 1 fail
   - Capture prompt; assert only the failing test's input/output 
     appear

7. **`test_failed_tests_capped_at_three`**:
   - 5 failing tests
   - Capture prompt; assert only first 3 failed inputs appear, 
     preserving test order

8. **`test_typed_test_cases_dumped_for_sandbox`**:
   - Build VerifierInput with `list[TestCase]`
   - Assert SandboxRunRequest receives `[tc.model_dump() for tc in input.test_cases]`
   - Guards the Solver-compatible boundary needed for 4.3 persistence

9. **`test_timeout_status_skips_llm_call`**:
   - Mock sandbox returns status="timeout"
   - Assert verified=False, diagnosis is the deterministic timeout 
     message
   - Assert `llm.chat` was NOT called

10. **`test_some_failed_with_empty_results_skips_llm_call`**:
    - Defensive case: status="some_failed" but test_results=[]
    - Assert no LLM call, diagnosis=""

11. **`test_failed_test_with_error_and_none_actual`**:
    - Failed result has `actual is None`, `error` is 
      "ZeroDivisionError"
    - Assert prompt formats safely
    - Assert LLM called

12. **`test_prompt_omits_expected`**:
    - Capture the prompt string
    - Assert no test case's expected value appears in the prompt
    - Use distinctive expected values such as "EXPECTED_SECRET_42"

13. **`test_prompt_omits_descriptions`**:
    - Test cases include description text that states the answer
    - Assert description text does NOT appear in prompt

14. **`test_redacted_output_excludes_expected`**:
    - VerifierOutput.test_results items are RedactedTestResult
    - Assert no `expected` attribute on the items
    - Guards against future regressions where someone adds expected 
      back to the public schema

15. **`test_uses_chat_method_not_complete`**:
    - Mock `DeepSeekClient.chat`
    - Assert `chat` was called, locking the actual client interface
    - Assert the old completion-style method name is not used

### Integration test (`test_verifier_integration.py`, 
`@pytest.mark.integration`)

Real DeepSeek + real Docker daemon. Skip unless API key set AND 
docker.from_env().ping() succeeds.

1. **`test_correct_solution_verifies_true`**:
   - Use existing fixture problem (e.g., sum_list)
   - student_code = a correct Python function
   - Run real verify(); assert verified=True, diagnosis=""
   - Assert redacted test results do not expose expected outputs

2. **`test_buggy_solution_gets_diagnosis`**:
   - Same problem, student_code with deliberate bug (e.g., 
     `return 0` instead of summing)
   - Run real verify(); assert:
     - verified=False
     - fail_count > 0
     - diagnosis is non-empty
     - diagnosis contains NO Python code (regex check: no 
       `def `, no `return `, no triple backticks)
     - diagnosis contains none of the expected values from 
       input.test_cases
     - response test_results do not include expected values

3. **`test_syntax_error_in_student_code`**:
   - student_code with literal Python syntax error
   - Assert verified=False, status="error", diagnosis="" 
     (we don't diagnose syntax errors — sandbox itself catches)

4. **`test_timeout_solution_gets_deterministic_message`**:
   - student_code with an infinite loop
   - Assert verified=False, status="timeout"
   - Assert diagnosis is TIMEOUT_DIAGNOSIS
   - Assert LLM is not involved when using a mocked integration boundary

## Verification Checklist

1. **Schemas validate**:
   - `python -c "from app.agents.verifier.schemas import VerifierInput, VerifierOutput, RedactedTestResult; print('ok')"`

2. **Unit tests**:
   - `cd backend && uv run pytest tests/agents/test_verifier.py -v`
   - Expected: 15 passed
   - All paths: pass / fail / sandbox-error / timeout / llm-error / 
     prompt-redaction / output-redaction

3. **Integration tests**:
   - `cd backend && uv run pytest tests/agents/test_verifier_integration.py -v -m integration`
   - Expected: 4 passed
   - Real LLM + real Docker

4. **No regression on existing tests**:
   - `cd backend && uv run pytest -v -m "not integration"`
   - Should pass existing suite + verifier unit tests

5. **Lint / type**:
   - `cd backend && uv run ruff check . && uv run mypy app/agents/verifier/`
   - Clean

6. **Residual spec scan**:
   - Search this spec for stale old field names, the old LLM client 
     type, the old LLM method, the old hard token cap, and the old 
     untyped VerifierInput test case annotation.
   - Expected: no matches

7. **End-to-end smoke** (manual, optional):
   - Pick a problem, write a buggy student solution, run:
````python
     from app.agents.verifier.agent import get_verifier_agent
     from app.agents.verifier.schemas import VerifierInput
     agent = get_verifier_agent()
     result = await agent.verify(VerifierInput(...))
     print(result.diagnosis)
````
   - Read the diagnosis manually — does it sound like a tutor? 
     Does it leak code? Does it leak expected output?

## What NOT to do

- DO NOT return raw sandbox test result objects through 
  VerifierOutput. Their `expected` field would leak answers via the 
  API.
- DO NOT pass test_case.description to the LLM. Descriptions are 
  written for problem authors and may state the expected behavior 
  literally.
- DO NOT include raw expected values in the LLM prompt input. The 
  rule "LLM can't leak what it doesn't see" beats any system-prompt 
  guarantee.
- DO NOT call the LLM when verified=True. Wasted tokens.
- DO NOT call the LLM on status="timeout" or status="error". Both 
  are deterministic status failures with no per-test signal to 
  diagnose.
- DO NOT raise on LLM errors; degrade with fallback diagnosis text. 
  The student still needs pass/fail info even if feedback is 
  unavailable.
- DO NOT make the agent thread-mutable; one cached instance serves 
  all requests.
- DO NOT couple agent to DB — that's the 4.3 Service's job.
- DO NOT add hint generation, multi-turn, or "great attempt" 
  filler — those are Step 5 territory.
- DO NOT use `temperature > 0.5` for diagnosis — we want focused 
  feedback, not creative essays.
- DO NOT send more than 3 failed tests to the LLM. The cap keeps 
  feedback focused, and diagnosis quality depends on authors placing 
  basic failures before edge cases.
- DO NOT use `max_tokens`; DeepSeekClient.chat does not support it. 
  Enforce brevity via the prompt rules unless the client is explicitly 
  enhanced.
- DO NOT call `complete()` on the LLM client; the actual method is 
  `chat()`. Test #15 locks this interface.

## Estimated Time
- Schemas + agent skeleton: 30 min
- Prompt design + redaction tests: 30 min
- Unit tests: 45 min
- Integration tests + real LLM verification of no-leakage: 30 min
- Debug + ruff + mypy: 15-30 min
- **Total: ~2.5-3 hours active**
