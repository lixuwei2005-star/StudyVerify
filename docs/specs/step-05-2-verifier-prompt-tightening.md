# StudyVerify — Step 5.2: Verifier Prompt Tightening + Step 5 Closure

## Goal
Apply the algorithm-dictation guard from Step 5.1 (Hint Agent) 
to the Verifier diagnostic prompt at parity. Update README to 
reflect Week 5 progress. Close Step 5.

## Why This Step
Step 5.1 Phase 6 surfaced a leaky Verifier diagnosis on the 
sum-list `return 0` test:

> "Consider using a loop or a built-in function to add up the 
>  values."

This crosses the same line Hint's algorithm-dictation guard now 
prevents — naming the implementation mechanism (loop / built-in 
function). At the time this was deferred to 5.2 to avoid scope 
creep on 5.1.

The Verifier and Hint must enforce the same anti-leak contract 
because:
- Both produce student-facing feedback for the same problem
- Diagnosis seeds the first hint's prior_hints context — a leaky 
  diagnosis pollutes hint quality even if the hint itself is clean
- Production credibility: the contract is "no answers, no 
  algorithms" or it isn't

## Scope
- Update `backend/app/agents/verifier/prompts.py` 
  DIAGNOSIS_SYSTEM_PROMPT to forbid algorithm step descriptions
- Add new integration test 
  `test_minimal_code_diagnosis_no_algorithm_dictation` 
  (parity with hint's test)
- Update README.md to Week 5 with Hint Agent capability
- Run full regression + end-to-end smoke

## Out of Scope
- ❌ TutoringService — deferred (decision: not needed; 3 
  endpoints already compose flexibly; Step 7 frontend will 
  drive any orchestration if needed)
- ❌ LangGraph — deferred to Step 6+ when complexity justifies
- ❌ Step 6 multi-model gateway / RAG
- ❌ Frontend
- ❌ New schema or migration changes (this step is prompt + 
  docs only)

## Files to Modify
- `backend/app/agents/verifier/prompts.py` — strengthen 
  DIAGNOSIS_SYSTEM_PROMPT
- `backend/tests/agents/test_verifier_integration.py` — add 
  one new integration test
- `README.md` — Status, What works, Roadmap

## Prompt Changes (verifier/prompts.py)

The existing DIAGNOSIS_SYSTEM_PROMPT has 6 critical rules. Insert 
a new rule after rule 1 (the "no code" rule), renumbering the 
others:

NEW RULE 2:
```
2. DO NOT name implementation mechanisms or describe the 
   algorithm step-by-step in any form. This includes:
   - Naming control structures: "use a loop", "iterate", "with 
     a for loop", "while loop"
   - Naming built-in functions or operations: "use sum()", "use 
     a built-in function", "with reduce", "use list 
     comprehension"
   - Stepwise verbalization: "create a variable, add each 
     element, then return"
   - Sequence of actions: "first do X, then do Y"
   Instead, describe what the OUTPUT should logically be, or 
   what relationship the output has to the input. Let the 
   student decide HOW to compute it.
```

Also extend the "Example of GOOD feedback" section with a new 
example specifically for structurally-empty student code:

```
Another GOOD example, for student code "def sum_list(nums): return 0":
  "Your function returns 0 for every input, regardless of the 
   list contents. The expected behavior depends on the elements 
   of the input list."

BAD examples (DO NOT do this):
  - "Your function returns 0; consider using a loop or built-in 
     function to add up the values." (BAD: names the mechanism)
  - "You need to iterate through the list and accumulate." 
     (BAD: stepwise dictation)
  - "Try using sum() instead." (BAD: names the builtin answer)
```

The redaction discipline (omit expected_output, no test 
descriptions) carries over unchanged.

## New Integration Test

Append to `backend/tests/agents/test_verifier_integration.py`:

```python
@pytest.mark.integration
async def test_minimal_code_diagnosis_no_algorithm_dictation():
    """When student code is structurally empty (e.g., return 0 
    for sum), the Verifier diagnosis must not fall back to 
    naming the algorithm. Mirrors Step 5.1 hint anti-dictation 
    guard.
    
    Added after Step 5.1 Phase 6 surfaced this gap: the Verifier 
    prompt allowed "Consider using a loop or a built-in function 
    to add up the values" — naming the mechanism is the same 
    class of leak as algorithm dictation.
    """
    agent = VerifierAgent(
        sandbox_runner=DockerCodeRunner(),
        llm_client=get_llm_client(),
    )
    
    # Use the doubling-problem fixture pattern from existing 
    # test_buggy_solution_gets_diagnosis (multi-char expecteds 
    # avoid substring false-positives)
    problem_text = (
        "Write a function sum_list(nums) that returns the sum "
        "of all elements in nums."
    )
    student_code = "def sum_list(nums):\n    return 0\n"
    test_cases = [
        TestCase(input="[1, 2, 3]", expected="6", description=""),
        TestCase(input="[5, 5, 5]", expected="15", description=""),
        TestCase(input="[]", expected="0", description=""),
    ]
    
    result = await agent.verify(VerifierInput(
        problem_id="test-sum-empty",
        problem_text=problem_text,
        entry_function="sum_list",
        test_cases=test_cases,
        student_code=student_code,
    ))
    
    diagnosis = result.diagnosis
    assert diagnosis, "Diagnosis must be non-empty for failing code"
    
    # Anti-code regex (same as existing test #2)
    assert re.search(r"\bdef\s+\w+\s*\(", diagnosis) is None, \
        f"Diagnosis contains function definition: {diagnosis}"
    assert re.search(r"\breturn\s+\S", diagnosis) is None, \
        f"Diagnosis contains return statement: {diagnosis}"
    assert "```" not in diagnosis, \
        f"Diagnosis contains code fence: {diagnosis}"
    
    # Anti-algorithm-dictation phrase contract (parity with 
    # hint test_minimal_code_hint_no_algorithm_dictation)
    forbidden_phrases = [
        "use a loop",
        "using a loop",
        "with a loop",
        "for loop",
        "while loop",
        "iterate through",
        "iterate over",
        "loop through",
        "loop over",
        "create a variable",
        "running total",
        "accumulate",
        "use sum(",
        "use a built-in",
        "built-in function",
        "list comprehension",
    ]
    diagnosis_lower = diagnosis.lower()
    for phrase in forbidden_phrases:
        assert phrase not in diagnosis_lower, (
            f"Diagnosis dictated algorithm/mechanism: "
            f"contained '{phrase}'\nFull diagnosis: {diagnosis}"
        )
    
    # Expected-output substring check (existing pattern)
    for tc in test_cases:
        if tc.expected and len(tc.expected) > 2:
            assert tc.expected not in diagnosis, \
                f"Diagnosis leaks expected output {tc.expected!r}"
```

## README Updates

Status section, replace "Week 4" block with:

```markdown
## Status

🚧 **Week 5 / 12 — Hint Agent operational; Step 5.1 shipped**

### What works
- ✅ FastAPI backend with `/health`, `/health/db`, `/api/v1/solve`, 
  `/api/v1/verify`, `/api/v1/hint`, plus session-history GET 
  endpoints
- ✅ Solver Agent: 3-stage LLM pipeline + sandbox self-verification
- ✅ Verifier Agent: runs student code in hardened Docker sandbox; 
  generates diagnostic feedback that names neither code nor 
  algorithm
- ✅ Hint Agent: progressive hints with diagnosis-as-seed for 
  first call; concurrent retry on hint_index race; hard cap of 
  5 hints per verifier_session
- ✅ Anti-leak defense in depth across both Verifier and Hint:
  - Schema-level redaction (no expected field in any 
    student-facing model)
  - Prompt construction never sees expected values
  - Algorithm-dictation guard with substring contract (no 
    "use a loop", "iterate", "create a variable", etc.)
- ✅ Postgres + Redis + FastAPI via Docker Compose; 
  `make compose-up-rebuild` is clone-and-run
- ✅ SQLAlchemy 2.0 async + Alembic 3-stage backfill migrations
- ✅ 4-layer architecture: Route → Service → Repository → Agent
- ✅ Every solve/verify/hint persisted; full session history 
  queryable
- ✅ 120+ unit tests + 65+ integration tests across mocked, 
  SQLite, real Postgres, real DeepSeek, and real Docker layers
- ✅ End-to-end smoke (`make smoke-stack`) covers full 
  /solve → /verify → /hint chain
```

Architecture section, append two bullets:

```markdown
- **Hint layer** (`backend/app/agents/hint/`) — stateless 
  progressive-hint agent with concurrent-insert handling and 
  diagnosis seeding
- **Algorithm-dictation guard** — Verifier and Hint prompts 
  share a substring contract preventing the LLM from naming 
  control structures, built-ins, or stepwise algorithms; 
  enforced by integration tests
```

Roadmap → Completed:

```markdown
- ✅ Step 5: Hint Agent + verifier prompt tightening 
  (orchestration deferred to Step 6+ when complexity warrants)
```

Roadmap → Upcoming, drop the now-completed Step 5 line:

```markdown
- ⬜ Step 6: Multi-model gateway (Anthropic fallback) + RAG + 
  LangGraph orchestration
- ⬜ Step 7: Frontend (Next.js + Monaco)
- ⬜ Step 8-12: ML problems / evaluation / knowledge graph / 
  blog / MCP
```

Quick Start section, add hint example after the existing /verify 
curl block:

```markdown
To request a progressive hint when verification fails:
\`\`\`bash
VERIFIER_ID=$(curl -s ... | jq -r .session_id)  # from /verify response
curl -X POST http://localhost:8000/api/v1/hint \
  -H "Content-Type: application/json" \
  -d "{\"verifier_session_id\": \"$VERIFIER_ID\"}"
\`\`\`

Each call returns the next hint, more specific than the last, 
without naming code or algorithm steps.
```

## Verification

1. New verifier integration test passes:
```
   cd backend && uv run pytest \
     tests/agents/test_verifier_integration.py::test_minimal_code_diagnosis_no_algorithm_dictation \
     -v -m integration
```
   May fail on first prompt iteration if rules aren't strict 
   enough. If it fails, show the LLM output, iterate the prompt, 
   do NOT weaken the test.

2. Full verifier integration suite passes (no regression):
```
   uv run pytest tests/agents/test_verifier_integration.py \
     -v -m integration
```
   Expected: 4 passed (3 existing + 1 new).

3. Full hint integration suite passes (no contamination from 
   prompt change — hint and verifier prompts are separate files, 
   but seeded diagnosis flows through):
```
   uv run pytest tests/agents/test_hint_integration.py \
     -v -m integration
```
   Expected: 4 passed.

4. Full regression sweep:
```
   uv run pytest -v -m "not integration"
```
   Expected: 120 passed, 1 skipped (no change — only 
   integration test added).

5. End-to-end smoke:
```
   make smoke-stack
```
   Expected: 6/6 green. Capture verbatim diagnosis from Step 3 
   (buggy code) — should NOT contain "loop", "built-in", etc. 
   Paste it for review.

6. README renders cleanly on GitHub (visual check after push).

## What NOT to do
- DO NOT weaken the forbidden_phrases list to make a flaky LLM 
  output pass — iterate the prompt instead
- DO NOT add the dictation guard to Solver agent prompts — 
  Solver writes code, that's its job; the guard is for 
  student-facing feedback (Verifier + Hint)
- DO NOT introduce a shared prompts module yet — Verifier and 
  Hint prompts have different jobs; sharing premature
- DO NOT remove "Consider..." entirely from the prompt — 
  Verifier still needs to give a diagnosis, just not one that 
  names mechanisms

## Estimated Time
- Prompt rewrite + iteration: 20 min
- New integration test: 15 min
- README updates: 15 min
- Verification + smoke: 15 min
- **Total: ~60 min**