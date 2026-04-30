# StudyVerify — Step 4.4: Step 4 Closure Spec

## Goal
Close Step 4 by guarding the compose-stack /tmp bind-mount with an 
ops smoke target, refreshing README to reflect Verifier capability, 
and running Step 1-4 full regression. After this, Step 4 is 
shipped.

## Scope
- `make smoke-stack` Makefile target — bash flow that exercises 
  full /solve → /verify path against a running compose stack
- README updates: Status, "What works", Architecture, Roadmap
- `regression-all` Makefile target updated to include verifier 
  test paths
- Step 1-4 full regression sweep
- Manual end-to-end smoke as final gate

## Out of Scope
- ❌ CI workflow → later
- ❌ Sandbox image pre-warming → Step 11 territory
- ❌ Frontend integration → Step 7
- ❌ Production hardening → graduation-level

## Files to Modify
- `Makefile` — add `smoke-stack` target; update `regression-all` 
  to cover verifier tests
- `README.md` — Status, What works, Architecture, Roadmap sections
- `scripts/smoke-stack.sh` (new) — the actual bash flow

## smoke-stack Implementation

`scripts/smoke-stack.sh`:

```bash
#!/usr/bin/env bash
# Exercise the full /solve -> /verify path against a running compose 
# stack. Catches /tmp bind-mount regressions and other compose-stack 
# breakages that the in-process TestClient integration tests don't.
#
# Pre-req: `make compose-up` succeeded; all 3 services healthy.
# Post-condition: stack remains running; data persisted to volume.

set -euo pipefail

API="http://localhost:8000"
PROBLEM_FILE="backend/tests/agents/fixtures/sample_problems.json"

echo "▶ Step 1: POST /solve to seed a solver_session..."
SOLVE_RESPONSE=$(curl -sf -X POST "$API/api/v1/solve" \
    -H "Content-Type: application/json" \
    -d "$(jq '.[0]' "$PROBLEM_FILE")")
SOLVER_ID=$(echo "$SOLVE_RESPONSE" | jq -r .session_id)
SOLVER_VERIFIED=$(echo "$SOLVE_RESPONSE" | jq -r .output.verified)

if [ "$SOLVER_VERIFIED" != "true" ]; then
    echo "❌ Solver did not verify; cannot proceed."
    exit 1
fi
echo "  ✓ solver_session_id=$SOLVER_ID, verified=true"

echo ""
echo "▶ Step 2: POST /verify with correct student code..."
VERIFY_OK=$(curl -sf -X POST "$API/api/v1/verify" \
    -H "Content-Type: application/json" \
    -d "{\"solver_session_id\": \"$SOLVER_ID\", \"student_code\": \"def sum_list(nums):\\n    return sum(nums)\"}")
VERIFY_OK_STATUS=$(echo "$VERIFY_OK" | jq -r .output.status)

if [ "$VERIFY_OK_STATUS" != "all_passed" ]; then
    echo "❌ Verifier did not return all_passed for correct code."
    echo "   Got status: $VERIFY_OK_STATUS"
    echo "   This typically means the Docker sandbox couldn't execute"
    echo "   the student code — check that docker-compose.yml mounts"
    echo "   /tmp:/tmp on the api service."
    exit 1
fi
echo "  ✓ correct code → all_passed"

echo ""
echo "▶ Step 3: POST /verify with buggy student code..."
VERIFY_BUG=$(curl -sf -X POST "$API/api/v1/verify" \
    -H "Content-Type: application/json" \
    -d "{\"solver_session_id\": \"$SOLVER_ID\", \"student_code\": \"def sum_list(nums):\\n    return 0\"}")
VERIFY_BUG_STATUS=$(echo "$VERIFY_BUG" | jq -r .output.status)
DIAGNOSIS=$(echo "$VERIFY_BUG" | jq -r .output.diagnosis)

if [ "$VERIFY_BUG_STATUS" != "some_failed" ]; then
    echo "❌ Verifier did not return some_failed for buggy code."
    echo "   Got status: $VERIFY_BUG_STATUS"
    exit 1
fi
if [ -z "$DIAGNOSIS" ]; then
    echo "❌ Verifier returned empty diagnosis for buggy code."
    echo "   This typically means the LLM call failed."
    exit 1
fi
echo "  ✓ buggy code → some_failed, diagnosis present"
echo "    Diagnosis: $DIAGNOSIS"

echo ""
echo "▶ Step 4: GET /sessions/$SOLVER_ID/verifier-sessions..."
LIST_TOTAL=$(curl -sf "$API/api/v1/sessions/$SOLVER_ID/verifier-sessions" | jq -r .total)
if [ "$LIST_TOTAL" -lt 2 ]; then
    echo "❌ Expected at least 2 verifier sessions; got $LIST_TOTAL."
    exit 1
fi
echo "  ✓ list endpoint returned $LIST_TOTAL sessions"

echo ""
echo "▶ Step 5: psql JSONB redaction check..."
LEAKS=$(docker exec studyverify-postgres sh -c \
    'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -tAc \
     "SELECT COUNT(*) FROM verifier_sessions WHERE jsonb_path_exists(test_results, '"'"'\$[*].expected'"'"');"')
if [ "$LEAKS" != "0" ]; then
    echo "❌ Anti-leak contract violated: $LEAKS rows have 'expected' in test_results JSONB."
    exit 1
fi
echo "  ✓ 0 rows leak 'expected' in JSONB"

echo ""
echo "✅ Stack smoke passed."
```

Make it executable:

```bash
chmod +x scripts/smoke-stack.sh
```

## Makefile Additions

```makefile
smoke-stack:
	@echo "Running full-stack smoke (requires `make compose-up` first)..."
	@bash scripts/smoke-stack.sh

regression-all:
	@echo "Running full test regression (unit + integration)..."
	@echo "Pre-requisite: 'make compose-up-infra' must be running"
	@echo "Pre-requisite: backend/.env must have DEEPSEEK_API_KEY"
	@echo ""
	cd backend && uv run pytest -v
```

(`regression-all` already exists; only update its docstring/echo 
text. The pytest invocation already covers verifier paths because 
verifier test files are in standard locations.)

Help text update:

```makefile
@echo "  make smoke-stack          - Full /solve -> /verify smoke (compose stack must be up)"
```

## README Updates

Surgical updates only — preserve existing structure (137 lines).

### Status section

Replace the current Week 3 status block with:

```markdown
## Status

🚧 **Week 4 / 12 — Verifier Agent + Docker sandbox operational**

### What works
- ✅ FastAPI backend with `/health`, `/health/db`, 
  `/api/v1/solve`, `/api/v1/verify`, `/api/v1/sessions/...`, 
  `/api/v1/verifier-sessions/...`
- ✅ Solver Agent: 3-stage LLM pipeline + sandbox self-verification
- ✅ Verifier Agent: runs student code in hardened Docker sandbox; 
  generates LLM-based diagnostic feedback when tests fail
- ✅ Anti-leak contract: redacted student-facing schemas at three 
  layers (Pydantic, prompt construction, DB write)
- ✅ Postgres + Redis + FastAPI via Docker Compose; all 3 services 
  report (healthy)
- ✅ SQLAlchemy 2.0 async + Alembic migrations (3-stage backfill 
  pattern for required-field additions)
- ✅ 4-layer architecture: Route → Service → Repository + Agent
- ✅ Docker sandbox with 14 hardening flags (network=none, 
  cap_drop=ALL, pids_limit, etc.) verified via baseline 
  isolation smoke tests
- ✅ Every solve and verify invocation persisted; full session 
  history queryable
- ✅ 89+ unit tests + 30+ integration tests across mocked, 
  SQLite, real Postgres, real DeepSeek, and real Docker layers
```

### Architecture section

Append three bullets to the existing list:

```markdown
- **Verifier layer** (`backend/app/agents/verifier/`) — stateless 
  agent runs student code in Docker sandbox; LLM generates 
  diagnostic feedback with strict anti-leak prompt construction
- **Docker sandbox** (`backend/app/sandbox/docker_runner.py`) — 
  14-flag hardened container with bind-mount payload delivery 
  (cross-platform reliable)
- **Anti-leak defense** — RedactedTestResult schema + prompt 
  construction omits expected values + DB JSONB never stores 
  expected key; verified via Pydantic reflection tests + 
  end-to-end LLM behavior tests
```

### Roadmap section

```markdown
### Completed
- ✅ Step 0-2: Environment, FastAPI skeleton, Solver Agent + sandbox
- ✅ Step 3: Persistence layer (Postgres + Alembic + Service/Repo + 
  full Docker Compose stack)
- ✅ Step 4: Verifier Agent (Docker sandbox + diagnostic feedback + 
  persistence + REST endpoints)

### Upcoming
- ⬜ Step 5: Hint Agent + LangGraph orchestration
- ⬜ Step 6: Multi-model gateway (Anthropic fallback) + RAG
- ⬜ Step 7: Frontend (Next.js + Monaco)
- ⬜ Step 8-12: ML problems / evaluation / knowledge graph / 
  blog / MCP
```

### Quick Start

No change — the existing `make compose-up-rebuild` flow now 
covers verifier too.

Add one line to the curl examples:

```markdown
To submit student code against a solved problem:
\`\`\`bash
SOLVER_ID=$(curl -s ...)  # from the /solve example above
curl -X POST http://localhost:8000/api/v1/verify \
  -H "Content-Type: application/json" \
  -d "{\"solver_session_id\": \"$SOLVER_ID\", \"student_code\": \"def sum_list(nums):\\n    return sum(nums)\"}"
\`\`\`

For an automated end-to-end check:
\`\`\`bash
make smoke-stack
\`\`\`
```

## Verification Checklist

1. `make smoke-stack` exits 0 against running stack (5/5 steps green)
2. `make smoke-stack` correctly fails if /tmp bind-mount removed 
   (manually verify by commenting out `- /tmp:/tmp` in 
   compose.yml, expect Step 2 to fail with explicit error message; 
   then restore)
3. README renders cleanly on GitHub after push
4. README line count still ≤ 200 (was 137; updates add ~30 lines)
5. Full unit regression: 89 passed, 1 skipped (Step 4.3 baseline 
   preserved)
6. Full integration regression: 30+ passed (gated by 
   DEEPSEEK_API_KEY + Docker)
7. Final state: `git status` shows only the expected files modified

## What NOT to do
- DO NOT add a Python integration test that spawns compose — the 
  bash smoke is the right tool; pytest-spawning-compose is overkill
- DO NOT bloat README beyond ~200 lines
- DO NOT modify regression-all to skip verifier tests "because they 
  need Docker" — they're properly gated by `@pytest.mark.integration`
- DO NOT remove the existing diagnostic error messages in 
  smoke-stack.sh — they're the value when something breaks

## Estimated Time
- smoke-stack.sh: 20 min
- Makefile updates: 5 min
- README updates: 20 min
- Verification: 15 min
- **Total: ~60 min**