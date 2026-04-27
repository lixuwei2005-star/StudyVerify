# StudyVerify — Step 2: Solver Agent Spec

## Goal
Implement the **Solver Agent** — the first AI Agent in the system.
Given a Python programming problem, the Solver independently produces a 
"ground truth" solution path that downstream Agents (Verifier, Hint) will 
rely on.

The Solver is NOT shown to the student. It exists to give the rest of the 
system a reliable reference for verification and hint generation.

## Why Solver First (architectural rationale)
- Verifier (Step 4) needs Solver output to compare against student's work
- Hint Agent (Step 5) needs Solver path + student state diff to generate hints
- Without a reliable Solver, downstream Agents have no ground truth

## Scope: Python Beginner Problems Only
- Domain: Python 3.11 syntax, basic data structures, simple algorithms
- Difficulty: LeetCode Easy level or below
- Out of scope (this step): ML problems, math derivations, multi-language

## Tech Stack (additions to existing skeleton)
- LLM Provider: **DeepSeek API** (OpenAI-compatible interface)
- Async HTTP: `httpx` (already in deps from Step 1)
- LLM SDK: use `openai` package (DeepSeek is OpenAI-compatible, just change base_url)
- Structured output: Pydantic models for type-safe Agent I/O
- Logging: structured logging with `logging` (use existing setup)

DO NOT add:
- LangChain / LangGraph (we'll evaluate adding LangGraph at Step 5)
- Vector DB / embeddings (that's Step 6)
- Sandbox execution (that's Step 2.3, separate sub-step)

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                      SOLVER AGENT                           │
│                                                             │
│  Input: SolverInput {                                       │
│    problem_id: str                                          │
│    problem_text: str                                        │
│    test_cases: list[TestCase]                               │
│  }                                                          │
│                                                             │
│  Pipeline (3 LLM calls, sequential):                        │
│  ┌──────────┐   ┌──────────┐   ┌─────────────┐             │
│  │ Analyze  │──▶│   Plan   │──▶│ Code-gen    │             │
│  │ (what's  │   │ (steps   │   │ (Python     │             │
│  │  asked?) │   │  to take)│   │  function)  │             │
│  └──────────┘   └──────────┘   └─────────────┘             │
│                                                             │
│  Output: SolverOutput {                                     │
│    analysis: str                                            │
│    plan_steps: list[PlanStep]                               │
│    code: str                                                │
│    explanation: str                                         │
│    confidence: float (0.0-1.0)                              │
│  }                                                          │
└─────────────────────────────────────────────────────────────┘
```

NOTE: Step 2.3 will add a 4th step "Self-check via sandbox". 
For Step 2.2, we stop at code-gen and return the output without execution.

## Files to Create / Modify

### New files
- `backend/app/agents/solver/__init__.py`
- `backend/app/agents/solver/agent.py` — main `SolverAgent` class
- `backend/app/agents/solver/prompts.py` — prompt templates (analyze, plan, code)
- `backend/app/agents/solver/schemas.py` — Pydantic models for I/O
- `backend/app/llm/__init__.py`
- `backend/app/llm/client.py` — DeepSeek client wrapper (async)
- `backend/app/llm/exceptions.py` — `LLMError`, `LLMTimeoutError`, `LLMRateLimitError`
- `backend/app/api/routes/solver.py` — `POST /api/v1/solve` endpoint
- `backend/tests/agents/__init__.py`
- `backend/tests/agents/test_solver.py` — unit tests with mocked LLM
- `backend/tests/agents/test_solver_integration.py` — real API test (skip if no key)
- `backend/tests/agents/fixtures/sample_problems.json` — 3 sample Python problems

### Modified files
- `backend/app/core/config.py` — add `DEEPSEEK_API_KEY`, `DEEPSEEK_BASE_URL`, `DEEPSEEK_MODEL`, `LLM_TIMEOUT_SECONDS`, `LLM_MAX_RETRIES`
- `backend/.env.example` — document new env vars
- `backend/app/main.py` — include solver router
- `backend/pyproject.toml` — add `openai` package

## Pydantic Schemas

### `app/agents/solver/schemas.py`

```python
from pydantic import BaseModel, Field

class TestCase(BaseModel):
    input: str          # e.g., "[1,2,3]"
    expected: str       # e.g., "6"
    description: str    # e.g., "Sum of [1,2,3]"

class SolverInput(BaseModel):
    problem_id: str
    problem_text: str
    test_cases: list[TestCase]

class PlanStep(BaseModel):
    step_number: int
    action: str         # high-level action, e.g., "Initialize a counter to 0"
    rationale: str      # why this step

class SolverOutput(BaseModel):
    problem_id: str
    analysis: str = Field(description="Restatement of what's being asked")
    plan_steps: list[PlanStep]
    code: str = Field(description="Final Python code, function signature included")
    explanation: str = Field(description="Plain-language explanation of the solution")
    confidence: float = Field(ge=0.0, le=1.0)
```

## DeepSeek Client Wrapper Requirements

`app/llm/client.py` must:
- Async (`AsyncOpenAI` from `openai` package, with DeepSeek base_url)
- Handle timeouts (default 30s, configurable via Settings)
- Retry on rate limit / transient errors (max 3, exponential backoff)
- Raise typed exceptions: `LLMTimeoutError`, `LLMRateLimitError`, `LLMError`
- Log every call: model, input tokens, output tokens, latency_ms, success/error
- Provide a single `chat(messages, model=None, temperature=0.3) -> str` method

Use this pattern:
```python
from openai import AsyncOpenAI
client = AsyncOpenAI(
    api_key=settings.DEEPSEEK_API_KEY,
    base_url=settings.DEEPSEEK_BASE_URL,  # https://api.deepseek.com/v1
)
```

DeepSeek model name: `deepseek-v4-flash` (V4 Preview, the current cost-efficient model — supports both thinking and non-thinking modes via reasoning_effort param. Default to non-thinking for Solver. The legacy `deepseek-chat` alias still works but will be retired after 2026-07-24.).

## Solver Agent Requirements

`SolverAgent.solve(input: SolverInput) -> SolverOutput` must:

1. **Analyze step**: send `problem_text` + `test_cases` to LLM, ask for restatement and key constraints. Use `prompts.ANALYZE_PROMPT`.

2. **Plan step**: feed analysis back to LLM, ask for step-by-step plan. Output should be parseable into `list[PlanStep]`. Use `prompts.PLAN_PROMPT`.

3. **Code step**: feed plan back to LLM, ask for final Python code + explanation. Use `prompts.CODE_PROMPT`. Request JSON output with structured fields.

4. **Confidence calculation** (simple v1):
   - Start at 1.0
   - Subtract 0.2 if analysis is shorter than 50 chars
   - Subtract 0.2 if plan_steps is empty or only 1 step
   - Subtract 0.3 if code doesn't contain `def ` (no function defined)
   - Floor at 0.0

5. **Logging**: emit structured log per call with `problem_id` for traceability.

6. **Error handling**: if any LLM call fails after retries, raise `SolverError` with context (which step failed, problem_id).

## Prompt Templates (in `prompts.py`)

Define three constants: `ANALYZE_PROMPT`, `PLAN_PROMPT`, `CODE_PROMPT`.

Key requirements:
- **All prompts in English** (DeepSeek handles English best for code tasks)
- **System message**: "You are an expert Python instructor solving beginner-level problems. Be precise, prefer clarity over cleverness."
- **CODE_PROMPT must require JSON output** with fields `code`, `explanation`, matching the SolverOutput partial schema
- Each prompt template should be a function that takes input vars and returns the formatted message list

## API Endpoint

`POST /api/v1/solve`

Request body: `SolverInput` (Pydantic auto-validates)
Response: `SolverOutput`

Errors:
- `400` if input invalid (auto-handled by FastAPI)
- `502` if LLM service errors (catch `LLMError`)
- `504` if LLM times out (catch `LLMTimeoutError`)

## Sample Problems for Testing (`fixtures/sample_problems.json`)

Provide exactly 3 problems:
1. **Sum a list** — easy, deterministic
2. **Find the maximum** — easy, edge case (empty list)
3. **Count vowels in string** — string manipulation

Format:
```json
[
  {
    "problem_id": "py-001-sum-list",
    "problem_text": "Write a Python function `sum_list(nums)` that returns the sum of all integers in the input list. If the list is empty, return 0.",
    "test_cases": [
      {"input": "[1, 2, 3]", "expected": "6", "description": "basic"},
      {"input": "[]", "expected": "0", "description": "empty list"}
    ]
  },
  ...
]
```

## Test Requirements

### Unit tests (`test_solver.py`) — must NOT call real API
- Mock the LLM client to return canned responses
- Test happy path: 3 LLM calls happen in order, output parsed correctly
- Test failure: LLM raises `LLMError` mid-pipeline → `SolverError` propagated
- Test confidence calculation logic with synthetic outputs
- Use `pytest-mock` or `unittest.mock` (add `pytest-mock` to dev deps)

### Integration test (`test_solver_integration.py`) — calls real DeepSeek API
- Decorated with `@pytest.mark.integration`
- Skipped if `DEEPSEEK_API_KEY` env var is not set (use `pytest.mark.skipif`)
- Runs Solver against the 3 sample problems, asserts:
  - Output is valid `SolverOutput`
  - `code` field contains `def `
  - `confidence` >= 0.5
- Mark integration tests as slow (don't run by default)

Add to `pyproject.toml`:
```toml
[tool.pytest.ini_options]
markers = [
    "integration: tests that hit real external services (deselect with -m 'not integration')"
]
```

## Configuration Additions

`app/core/config.py` adds:
```python
DEEPSEEK_API_KEY: str = ""
DEEPSEEK_BASE_URL: str = "https://api.deepseek.com/v1"
DEEPSEEK_MODEL: str = "deepseek-v4-flash"
LLM_TIMEOUT_SECONDS: int = 30
LLM_MAX_RETRIES: int = 3
```
DEEPSEEK_REASONING_EFFORT: str = "none"  # "none" | "low" | "medium" | "high" — Solver default off, Verifier/Hint may enable later
`.env.example` documents all 5.

## Verification Checklist (must all pass)

1. `uv sync` succeeds with new deps (`openai`, `pytest-mock`)
2. `uv run ruff check .` clean
3. `uv run pytest -v -m "not integration"` passes (unit tests only, no API key needed)
4. With `DEEPSEEK_API_KEY` set in `.env`:
   - `uv run pytest -v -m integration` passes (3 sample problems solved)
   - `uv run uvicorn app.main:app --reload` starts
   - `curl -X POST http://localhost:8000/api/v1/solve -H "Content-Type: application/json" -d @backend/tests/agents/fixtures/sample_problems.json | head` returns valid SolverOutput JSON for first problem
5. Logs show 3 LLM calls per `/solve` request with token counts and latencies

## What NOT to do
- DO NOT add sandbox execution — Step 2.3 separate
- DO NOT add database persistence — Step 3
- DO NOT add LangChain/LangGraph — premature
- DO NOT hardcode API key — must be from Settings/env only
- DO NOT commit `.env` file
- DO NOT use synchronous HTTP calls — must be async throughout
- DO NOT use `print()` for logging — use `logging` module

## Out of Scope (explicitly NOT this step)
- Sandbox execution → Step 2.3
- Database persistence of solver outputs → Step 3
- Verifier Agent → Step 4
- Hint Agent → Step 5
- LangGraph orchestration → Step 5+
- Frontend → Step 7
- Multi-model fallback (Anthropic) → Step 6
- ML/math problems → Step 8