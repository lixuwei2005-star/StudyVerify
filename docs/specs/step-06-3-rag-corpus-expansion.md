# StudyVerify - Step 6.3: RAG Corpus Expansion + Validation Spec

## Goal

Expand the RAG corpus from 9 rows to 50+ by extending the problem fixture set
from 3 to 10 and seeding 5 curated buggy variants per problem. Verify that
retrieval continues to behave sensibly as the corpus gains cross-problem
diversity.

LangGraph orchestration is deferred. Step 7 frontend UX is still unknown, so
building cross-agent state machines now would likely target a workflow that does
not exist yet. A larger RAG corpus is the useful prerequisite for future Step 9
retrieval quality work.

## Why This Step

After 6.2, RAG retrieval works mechanically but the corpus is tiny and dominated
by one problem family. We cannot yet:

- validate cross-problem retrieval boundaries
- provide diverse past-failure inspiration to the Hint Agent
- establish a baseline for Step 9 evaluation

50+ failed verifier rows across 10 problems gives us:

- cross-problem retrieval validation
- within-problem variation, with 5 buggy patterns per problem
- a real dev corpus for later quality work

## Scope

- Extend `backend/tests/agents/fixtures/sample_problems.json` from 3 to 10
  problems.
- Add `backend/app/scripts/generate_buggy_variants.py`, an LLM-assisted CLI for
  generating candidate buggy code variants.
- Add `backend/app/scripts/seed_failure_corpus.py`, a CLI that drives
  `/api/v1/solve` and `/api/v1/verify` against the local compose stack.
- Extend `RetrievedFailure` with `problem_id` so quality tests can assert by
  source problem instead of diagnosis text.
- Add automated retrieval-quality tests with a deterministic test-corpus fixture.
- Add a manual dev-DB retrieval validation script.
- Update README to mention the seeded corpus size.

## Out of Scope

- LangGraph orchestration. Deferred until Step 7 clarifies the real frontend UX.
- RAG parameter tuning (`RAG_TOP_K`, `RAG_MIN_SIMILARITY`). Step 9 territory.
- RAG quality metrics or LLM-as-judge evaluation. Step 9 territory.
- Embedding model evaluation. Step 9 territory. Current
  `text-embedding-3-small` is the only embedding model used.
- External knowledge corpus such as textbooks or docs. Step 8+.
- Frontend integration. Step 7.

## File Layout

### New

- `backend/app/scripts/generate_buggy_variants.py` - CLI that takes a problem id,
  calls an LLM, validates candidate variants, and outputs reviewed JSON.
- `backend/app/scripts/seed_failure_corpus.py` - CLI that reads curated variants
  and drives `/solve -> /verify` against the running compose stack.
- `backend/tests/agents/fixtures/buggy_variants.json` - hand-curated 50 buggy
  variants, 10 problems x 5 variants.
- `backend/tests/agents/test_sample_problems_fixtures.py` - fixture schema and
  reference-solution validation.
- `backend/tests/scripts/test_generate_buggy_variants.py` - parse, retry, and
  validation coverage for the generator.
- `backend/tests/scripts/test_seed_failure_corpus.py` - idempotency, dry-run,
  failure-continuation, and destructive-reseed safety tests.
- `backend/tests/services/test_retrieval_corpus_quality.py` - PG-marked
  retrieval boundary tests using a deterministic mini-corpus.
- `scripts/validate_retrieval_quality.sh` - manual Tier 2 dev-DB validation
  script for the real seeded corpus.

### Modified

- `backend/tests/agents/fixtures/sample_problems.json` - 3 to 10 problems.
- `backend/app/services/retrieval_service.py` - include `problem_id` on
  `RetrievedFailure`.
- `README.md` - corpus size in Architecture or Status section.
- `docs/specs/step-06-3-rag-corpus-expansion.md` - this v2 spec.

## 10-Problem Fixture Plan

The final problem set must include 10 entries:

| ID | Problem | Pattern |
|---|---|---|
| py-001-sum-list | Sum a list of integers | accumulator / empty list |
| py-002-find-max | Find maximum of list | comparison / empty list |
| py-003-count-vowels | Count vowels in a string | string scan / case-insensitive |
| py-004-reverse-string | Reverse a string | slicing / iteration |
| py-005-factorial | Compute factorial(n) | scalar numeric / iteration |
| py-006-is-palindrome | Check if string is palindrome | string comparison |
| py-007-sort-ascending | Sort list ascending | sorting / ordering |
| py-008-is-prime | Check if n is prime | scalar numeric / divisibility |
| py-009-binary-search | Binary search sorted list | algorithmic / boundaries |
| py-010-flatten-list | Flatten nested list one level | nested list / extend |

The 7 new problems should cover distinct bug surfaces instead of adding more
variants of the same list operation. `py-005-factorial` and `py-008-is-prime`
mitigate list-only embedding skew by adding two scalar numeric problems out of
10. `py-009-binary-search` adds algorithm-specific bugs such as off-by-one
bounds, loop termination, and midpoint calculation. `py-010-flatten-list` keeps
list semantics but makes the one-level nested shape explicit.

Each fixture entry must include:

- `problem_id`
- `problem_text`
- `entry_function`
- `test_cases`, with at least 3 cases using `{input, expected, description}`
- `reference_solution`

Current `/solve` only needs `problem_id`, `problem_text`, and `test_cases`, but
the expanded fixture deliberately includes `entry_function` and
`reference_solution` for generator validation and seed tooling. Script code that
posts to `/solve` must send only the fields accepted by `SolverInput`.

### Required New Test Cases

`py-006-is-palindrome` must use distinctively string-shaped cases:

| input | expected | description |
|---|---|---|
| `"racecar"` | `True` | odd-length palindrome |
| `"hello"` | `False` | non-palindrome |
| `""` | `True` | empty string |

`py-010-flatten-list` must make one-level nesting concrete:

| input | expected | description |
|---|---|---|
| `[[1, 2], [3, 4]]` | `[1, 2, 3, 4]` | two nested lists |
| `[[1], [], [2, 3]]` | `[1, 2, 3]` | includes empty sublist |
| `[]` | `[]` | empty outer list |

Use multi-character strings, booleans, or list reprs where possible. Avoid
over-relying on one-character expected outputs in retrieval tests because they
produce weak text signals.

## `generate_buggy_variants.py` CLI

Purpose:

```text
Generate N candidate buggy implementations for one problem fixture.
The output is for human review before it is saved to buggy_variants.json.
```

Usage:

```bash
cd backend
uv run python -m app.scripts.generate_buggy_variants \
  --problem-id py-001-sum-list \
  --count 5 \
  --provider deepseek \
  --output tests/agents/fixtures/generated_py_001.json
```

Arguments:

- `--problem-id` required.
- `--count` default `5`.
- `--provider {deepseek,openai}` default `deepseek`.
- `--model` optional. For OpenAI fallback, `gpt-4o-mini` is the expected manual
  override.
- `--output` optional. Defaults to stdout.

The generator uses `temperature=0.7` and `json_mode=True` because variety is
wanted here. However, the current provider implementations set
`response_format={"type": "json_object"}`. That means the model must return a
JSON object, not a bare array.

Prompt contract:

````text
Return ONLY this JSON object, no markdown and no preamble:

{
  "variants": [
    { "category": "...", "code": "..." }
  ]
}
````

`GENERATE_BUGGY_PROMPT` should include the problem text, entry function,
reference solution, requested count, and common beginner bug categories:

- off-by-one loops or indexing
- wrong empty-input/base-case handling
- wrong operator or comparison
- missing accumulator update
- wrong return value
- index error
- type confusion
- incorrectly mutating input

### Parse, Validate, Retry

The CLI must not trust JSON mode alone.

1. First call: prompt for the wrapped object shape:
   `{"variants": [...]}`.
2. Parse and validate:
   - `json.loads(raw)` succeeds
   - payload is a dict
   - `payload["variants"]` is a list
   - list length equals requested count
   - each item has string `category` and string `code`
   - each `code` parses with `ast.parse`
   - each `code` defines the fixture's `entry_function`
3. If parsing or validation fails, retry once with a stricter appended message:
   `Previous response was malformed. Return EXACTLY this shape: {"variants": [...]}`
4. After two failed parses or validations, log the validation error and exit
   non-zero.

The `--provider` flag lets an operator switch to OpenAI for a troublesome
problem. DeepSeek remains the default because this is low-stakes generation and
the output is manually reviewed. OpenAI `gpt-4o-mini` is an acceptable fallback
when DeepSeek's JSON mode misbehaves. Implement provider selection through the
existing LLM gateway/provider wiring where possible instead of introducing a
second ad hoc chat client abstraction.

Human review is mandatory before saving to `buggy_variants.json`. Discard
duplicates, syntax-only failures, wrong-function-name variants, and trivial
constant-return variants unless they represent a useful beginner bug category.

## `seed_failure_corpus.py` CLI

Purpose:

```text
Drive the full /solve -> /verify path against the local compose stack and
populate failed verifier_sessions with embeddings.
```

Usage:

```bash
cd backend
uv run python -m app.scripts.seed_failure_corpus \
  --variants tests/agents/fixtures/buggy_variants.json \
  --api-base http://localhost:8000
```

For each `(problem_id, buggy_code)` pair:

1. POST `/api/v1/solve` with only the accepted `SolverInput` fields from the
   problem fixture.
2. Capture `solver_session_id`.
3. POST `/api/v1/verify` with `{solver_session_id, student_code}`.
4. `VerifierService` persists the verifier row and embeds failed rows
   synchronously.
5. Log: `problem_id`, variant hash, category, verified status, verifier id,
   and embedding status.
6. Continue on per-row failure. One broken variant must not abort the whole run.
7. Final summary prints attempted, seeded, skipped, failed, accidental_pass,
   and embedding_success counts.

### Cost Estimate

`/solve` is one HTTP request but three LLM calls: analyze, plan, and code. It may
make a fourth `code_retry` call when sandbox verification fails. For 10
problems, the solver path is 30-40 chat completions. The verifier path adds 50
LLM diagnosis calls. The generator adds roughly 10-20 LLM calls depending on
parse retries. Embeddings add 50 calls.

Concrete budget:

- Solver: 30-40 calls x roughly 500 tokens each on DeepSeek V4 Flash is
  negligible, fractions of a cent per call.
- Verifier: 50 calls x roughly 200 tokens on DeepSeek is negligible.
- Embeddings: 50 calls x 200 tokens x `$0.02/M` for `text-embedding-3-small`
  is about `$0.0002`.
- Variant generation: 10 problems x 1-2 LLM calls is also negligible.

Likely under `$0.10` typical. Budget `$0.20` max including retries and any
regeneration during seeding.

### Idempotency

Do not use solver-session counts for idempotency. Solver sessions are created
per `/solve` call and do not map one-to-one to variants.

Default behavior is seed-missing-only:

1. Compute deterministic variant identity for logs:
   `sha256(student_code.strip().encode()).hexdigest()`.
2. Before seeding a `(problem_id, student_code)` pair, query:

```sql
SELECT 1
FROM verifier_sessions v
JOIN solver_sessions s ON v.solver_session_id = s.id
WHERE s.problem_id = :problem_id
  AND v.student_code = :student_code
LIMIT 1;
```

3. If a row exists, skip that variant.
4. If no row exists, run `/solve -> /verify`.

This handles partial resume correctly. If a previous run seeded 3 of 5 variants
for a problem, rerunning the same `buggy_variants.json` seeds only the missing 2.

### Safe Re-Seed Flow

Default, non-destructive seed:

```bash
uv run python -m app.scripts.seed_failure_corpus \
  --variants tests/agents/fixtures/buggy_variants.json
```

Dry run:

```bash
uv run python -m app.scripts.seed_failure_corpus \
  --variants tests/agents/fixtures/buggy_variants.json \
  --dry-run
```

Destructive reseed requires both flags:

```bash
uv run python -m app.scripts.seed_failure_corpus \
  --variants tests/agents/fixtures/buggy_variants.json \
  --delete-existing \
  --yes-dev-db
```

There is no single `--force-reseed` flag. Destructive behavior must be explicit
and safe:

1. Refuse `--delete-existing` if `DATABASE_URL` hostname is not one of
   `localhost`, `127.0.0.1`, or `studyverify-postgres`. Print the URL and exit
   `1`.
2. Build a deletion plan for all problem ids in the variants file.
3. Print the plan before any `DELETE` executes:
   `Will delete: 12 hint_sessions, 50 verifier_sessions, 10 solver_sessions`.
4. Without `--yes-dev-db`, prompt: `Type 'yes' to continue:` and abort on
   anything else.
5. Delete in FK order: `hint_sessions -> verifier_sessions -> solver_sessions`.
6. Delete solver sessions only when no other verifier sessions still reference
   them.
7. After deletion, proceed with normal seed-missing-only flow.

## Retrieval Service Change

Extend `RetrievedFailure` with `problem_id`:

````python
@dataclass(frozen=True)
class RetrievedFailure:
    verifier_session_id: UUID
    similarity: float
    diagnosis: str
    hint_texts: list[str]
    problem_id: str
````

Update `find_similar_failures` to join `solver_sessions`:

````sql
SELECT
    v.id,
    s.problem_id,
    1 - (v.failure_embedding <=> CAST(:query_emb AS vector)) AS similarity,
    v.diagnosis,
    COALESCE(
        array_agg(h.hint_text ORDER BY h.hint_index)
            FILTER (WHERE h.hint_text IS NOT NULL),
        ARRAY[]::text[]
    ) AS hint_texts
FROM verifier_sessions v
JOIN solver_sessions s ON s.id = v.solver_session_id
LEFT JOIN hint_sessions h ON h.verifier_session_id = v.id
WHERE v.failure_embedding IS NOT NULL
  AND v.embedding_status = 'success'
  AND v.verified = false
  AND (CAST(:exclude AS uuid) IS NULL OR v.id <> CAST(:exclude AS uuid))
GROUP BY v.id, s.problem_id, v.failure_embedding, v.diagnosis
HAVING 1 - (v.failure_embedding <=> CAST(:query_emb AS vector)) >= :min_sim
ORDER BY v.failure_embedding <=> CAST(:query_emb AS vector)
LIMIT :top_k
````

This is a non-breaking addition for existing callers. The extra field enables
quality tests to assert by source problem instead of brittle diagnosis
substrings.

## Cross-Problem Retrieval Validation

Do not assert on words inside `diagnosis`. Diagnoses are model-generated text and
are not stable labels. Also do not use dead branches below the configured
`min_similarity`; if retrieval uses `min_similarity=0.7`, a result below `0.65`
will never be returned.

Quality assertions must use `RetrievedFailure.problem_id`.

### Two-Tier Corpus Boundary

Dev DB and test DB have different jobs:

- Dev DB, the local compose stack, gets the real seeded corpus via
  `seed_failure_corpus.py`.
- Test DB, `studyverify_test`, gets a deterministic mini-corpus through the
  `seed_test_corpus(pg_session)` fixture for automated assertions.

This resolves the earlier contradiction between "do not seed the test DB" and
pytest tests that use `pg_session`.

### Tier 1: Automated Regression Test Corpus

`backend/tests/services/test_retrieval_corpus_quality.py` seeds 30 rows inline:

- 10 `py-001-sum-list` rows clustered near synthetic centroid A
- 10 `py-005-factorial` rows clustered near synthetic centroid B
- 10 `py-006-is-palindrome` rows clustered near synthetic centroid C

The fixture may use real `text-embedding-3-small` calls when `OPENAI_API_KEY` is
set, but must fall back to deterministic synthetic 1536-dimensional vectors when
the key is absent. CI must not depend on OpenAI credentials.

Required tests:

````python
@pytest.mark.integration
async def test_sum_list_query_retrieves_majority_sum_list(
    pg_session,
    seed_test_corpus,
):
    """At top_k=5, a sum_list query should return majority sum_list rows.

    Not all 5 must be same-problem. Some cross-problem retrieval is acceptable,
    but most results should match the source problem.
    """
    results = await retrieval_service.find_similar_failures(
        pg_session,
        query_embedding=sum_list_query_embedding,
        top_k=5,
        min_similarity=0.7,
    )
    same_problem_count = sum(
        1 for r in results if r.problem_id == "py-001-sum-list"
    )
    assert same_problem_count >= 3, (
        f"Expected at least 3 of {len(results)} retrievals to be sum_list; "
        f"got {same_problem_count}. Problem IDs: "
        f"{[r.problem_id for r in results]}"
    )
````

Add:

1. `test_sum_list_query_retrieves_majority_sum_list`
2. `test_factorial_query_isolates_to_scalar_problems`
   - factorial query should not surface mostly `py-001-sum-list` rows
   - at most 1 of top 5 should be `py-001-sum-list`
   - at least 3 of top 5 should be `py-005-factorial` or `py-008-is-prime` if
     the fixture includes both scalar families; otherwise at least 3 should be
     `py-005-factorial`
3. `test_palindrome_query_isolates_to_string_problems`
   - at least 3 of top 5 should be `py-006-is-palindrome` or
     `py-003-count-vowels`
   - no more than 1 should be `py-001-sum-list`

### Tier 2: Manual Dev-DB Validation

Add `scripts/validate_retrieval_quality.sh`. It runs against the dev DB seeded
by `seed_failure_corpus.py` and prints retrieval results for human review. This
is not a pytest test and is not run in CI.

The script should:

- confirm at least 50 failed verifier rows with `embedding_status='success'`
- run representative sum-list, factorial, and palindrome queries
- print top 5 rows with similarity, problem id, verifier id, and diagnosis
  snippet
- exit non-zero if the corpus is missing or embeddings are absent

## Test Plan

### Fixture Schema Validation

`backend/tests/agents/test_sample_problems_fixtures.py`:

- `test_all_10_problems_have_unique_ids`
- `test_all_problems_have_required_fields`
- `test_all_test_cases_have_distinguishable_expected_values`
- `test_all_reference_solutions_define_correct_entry_function`

Required fields are `problem_text`, `entry_function`, at least 3 `test_cases`,
and `reference_solution`. Distinguishable expected values means expected length
is more than 1 character or the value is a list/dict repr, boolean, `None`, or
otherwise semantically distinctive.

### Generator Unit Tests

`backend/tests/scripts/test_generate_buggy_variants.py`:

- valid wrapped JSON object parses
- bare legacy JSON array is rejected and triggers retry
- malformed JSON triggers retry once
- after 2 failures, exits with code `1` and a clear message
- variant missing `category` or `code` is rejected
- variant code that does not define `entry_function` is rejected
- syntactically invalid Python code is rejected

### Seed CLI Tests

`backend/tests/scripts/test_seed_failure_corpus.py`:

- partial resume seeds only missing variants using deterministic identity checks
- exact duplicate variant is skipped
- `--problem-filter` limits to one problem
- per-row API failure is logged and the run continues
- accidental passing variant logs a warning when `verified=true`
- `--dry-run` returns counts and makes no API calls or DB writes
- `--delete-existing` without `--yes-dev-db` prompts for confirmation
- `--delete-existing --yes-dev-db` deletes hints before verifier sessions
- non-localhost `DATABASE_URL` exits `1` before destructive deletion, even with
  `--yes-dev-db`
- deletion plan is printed before any `DELETE` executes

### Retrieval Quality Tests

`backend/tests/services/test_retrieval_corpus_quality.py`:

- `test_sum_list_query_retrieves_majority_sum_list`
- `test_factorial_query_isolates_to_scalar_problems`
- `test_palindrome_query_isolates_to_string_problems`

These are automated Tier 1 tests and use the deterministic 30-row fixture, not
the dev DB corpus.

## Execution Order

1. **Phase 1**: Hand-write 7 new problem fixtures in
   `sample_problems.json`. Include `entry_function` and `reference_solution`.
   Sanity-check all 10 problems.
2. **Phase 2**: Write `generate_buggy_variants.py` with wrapped-object JSON,
   parse-validate-retry, `--provider`, and validation tests. Generate candidates
   for all 10 problems and human-review the best 5 per problem.
3. **Phase 3**: Write `seed_failure_corpus.py` with sha256 identity checks,
   `--dry-run`, destructive reseed safety, and mocked tests. Run against the
   compose stack.
4. **Phase 4**: Thread `problem_id` through `RetrievedFailure`, add the
   deterministic Tier 1 corpus fixture, add 3 retrieval quality tests, and add
   the Tier 2 manual script.
5. **Phase 5**: Update README, run smoke, and run regression.

## Verification Checklist

1. `sample_problems.json` has 10 entries with the final problem set:
   `sum-list`, `find-max`, `count-vowels`, `reverse-string`, `factorial`,
   `is-palindrome`, `sort-ascending`, `is-prime`, `binary-search`,
   `flatten-list`.
2. The problem set includes exactly two scalar numeric problems:
   `py-005-factorial` and `py-008-is-prime`.
3. `py-006-is-palindrome` uses `"racecar"`, `"hello"`, and `""`.
4. `py-010-flatten-list` uses the required one-level nested list cases.
5. Generator output contract is a wrapped object with `variants`, not a bare
   array.
6. Generator parse validation rejects malformed JSON, missing keys, syntax
   errors, and wrong function names; it retries once and exits non-zero after
   two failures.
7. Cost estimate says likely under `$0.10` typical and `$0.20` max budget.
8. Seed idempotency uses `sha256(student_code.strip().encode())` for identity
   logging and the `(problem_id, student_code)` DB existence query for skip
   behavior.
9. `--dry-run` makes no API calls and no DB writes.
10. Destructive reseed requires `--delete-existing --yes-dev-db`, refuses
    non-localhost DB URLs, prints a deletion plan first, and deletes in FK
    order.
11. `RetrievedFailure` includes `problem_id`.
12. Retrieval SQL joins `solver_sessions` and maps `s.problem_id`.
13. Cross-problem tests assert by `problem_id`, not diagnosis substrings.
14. Test corpus boundary is two-tier: dev DB gets real seeded corpus; test DB
    gets deterministic 30-row mini-corpus.
15. Tier 2 manual script prints dev-DB retrieval results for human review.
16. Existing `make smoke-stack` still passes.
17. README mentions:
    `RAG corpus seeded from 50 LLM-generated buggy variants across 10 problems.`

## What Not To Do

- Do not add LangGraph in this step.
- Do not tune `RAG_TOP_K` or `RAG_MIN_SIMILARITY`.
- Do not switch embedding models or evaluate embedding models in this step.
- Do not skip human review of LLM-generated variants.
- Do not seed against production.
- Do not make destructive reseed a casual one-flag operation.
- Do not batch-fail the seed run if one variant crashes sandbox or the API.
- Do not assert retrieval quality by matching words in LLM-generated diagnoses.
- Do not expect pytest to read the dev compose corpus. Dev DB and test DB use
  the two-tier approach described above.

## Estimated Time

- Phase 1, 7 new fixtures plus sanity: 75 min
- Phase 2, generator plus retry plus run plus review: 75 min
- Phase 3, seed CLI plus identity check plus destructive reseed safety plus run:
  90 min
- Phase 4, `problem_id` threading plus 3 quality tests plus Tier 1 fixture:
  75 min
- Phase 5, README plus smoke plus regression: 30 min
- **Total: about 5.5 hours**

## Critical Pre-implementation Reads

1. `backend/tests/agents/fixtures/sample_problems.json` - confirm the current
   JSON shape and update it deliberately.
2. `backend/app/agents/solver/schemas.py` - confirm the `/solve` request shape;
   scripts must strip fixture-only fields before POSTing.
3. `backend/app/agents/solver/agent.py` - confirm the analyze, plan, code, and
   optional retry call sequence.
4. `backend/app/scripts/backfill_embeddings.py` - reuse CLI style, settings
   loading, async DB session pattern, and per-row error handling.
5. `backend/app/services/retrieval_service.py` - confirm `RetrievedFailure`
   dataclass shape; `problem_id` addition is a new field.
6. `backend/app/db/models.py` - confirm FK ordering for destructive cleanup:
   hints reference verifiers, verifiers reference solvers.
7. `backend/app/schemas/verifier_session.py` - confirm `/verify` accepts only
   `solver_session_id` and `student_code`.
