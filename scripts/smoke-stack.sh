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
VERIFY_BUG_ID=$(echo "$VERIFY_BUG" | jq -r .session_id)
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
echo "▶ Step 6: POST /hint twice + GET hints list..."

HINT1=$(curl -sf -X POST "$API/api/v1/hint" \
    -H "Content-Type: application/json" \
    -d "{\"verifier_session_id\": \"$VERIFY_BUG_ID\"}")
HINT1_TEXT=$(echo "$HINT1" | jq -r .hint_text)
HINT1_INDEX=$(echo "$HINT1" | jq -r .hint_index)

if [ -z "$HINT1_TEXT" ] || [ "$HINT1_TEXT" == "null" ]; then
    echo "❌ First hint returned empty text."
    exit 1
fi
if [ "$HINT1_INDEX" != "1" ]; then
    echo "❌ First hint hint_index expected 1, got $HINT1_INDEX."
    exit 1
fi
echo "  ✓ hint #1: index=$HINT1_INDEX, text=$HINT1_TEXT"

HINT2=$(curl -sf -X POST "$API/api/v1/hint" \
    -H "Content-Type: application/json" \
    -d "{\"verifier_session_id\": \"$VERIFY_BUG_ID\"}")
HINT2_TEXT=$(echo "$HINT2" | jq -r .hint_text)
HINT2_INDEX=$(echo "$HINT2" | jq -r .hint_index)

if [ -z "$HINT2_TEXT" ] || [ "$HINT2_TEXT" == "null" ]; then
    echo "❌ Second hint returned empty text."
    exit 1
fi
if [ "$HINT2_INDEX" != "2" ]; then
    echo "❌ Second hint hint_index expected 2, got $HINT2_INDEX."
    exit 1
fi
echo "  ✓ hint #2: index=$HINT2_INDEX, text=$HINT2_TEXT"

HINTS_TOTAL=$(curl -sf "$API/api/v1/verifier-sessions/$VERIFY_BUG_ID/hints" | jq -r .total)
if [ "$HINTS_TOTAL" -lt 2 ]; then
    echo "❌ List endpoint returned $HINTS_TOTAL hints, expected ≥ 2."
    exit 1
fi
echo "  ✓ list endpoint returned $HINTS_TOTAL hints"

echo ""
echo "✅ Stack smoke passed."
