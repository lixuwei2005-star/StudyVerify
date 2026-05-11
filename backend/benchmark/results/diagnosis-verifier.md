# Verifier False-Reject Diagnosis

- Source eval: `benchmark/results/2026-05-11_step10_prod_targeted_eval.json`
- Reference checks inspected: 70
- False-rejected references inspected: 0
- Reference checks with `raw_output`: 70/70

## Summary by category

| Category | Count | Description |
|---|---:|---|
| 1 | 0 | sandbox couldn't run code |
| 2 | 0 | tests reported some failures |
| 3 | 0 | tests passed but verifier rejected |
| 4 | 0 | unknown / missing data |

## Data availability check

`raw_output` is present in this eval artifact.

Sample `raw_output` keys: `diagnosis, fail_count, pass_count, problem_id, sandbox_error, status, test_results, verified`

## Targeted rerun sanity

- Targeted original false-reject problem records in this eval: 60
- Targeted references with verifier result: 60
- Targeted references missing/skipped before verify: 0
- Targeted IDs now verifier-correct: 60
- Targeted IDs still false-rejected: 0
- Control problem records in this eval: 10
- Control references with verifier result: 10
- Control references missing/skipped before verify: 0
- Control references verifier-correct: 10
- Control references false-rejected: 0

## Category 1 - sandbox issues (0 problems)

_No problems in this category._

## Category 2 - test failures (0 problems)

_No problems in this category._

## Category 3 - anti-leak over-rejection (0 problems)

_No problems in this category._

## Category 4 - unknown / missing data (0 problems)

_No problems in this category._

## Conclusions

Hypothesis ranking:
1. Category 1 (0 problems): sandbox bridge / function detection / import failure
2. Category 2 (0 problems): dataset reference or test-case mismatch
3. Category 3 (0 problems): LLM judge over-rejection after passing tests
4. Category 4 (0 problems): eval artifact omitted or failed to produce raw verify details

Top data-backed hypothesis: no false rejects were present in this eval artifact.

## P0 fix paths

- For category 1: fix sandbox bridge / function detection
- For category 2: re-validate dataset references
- For category 3: tune LLM judge prompt or relax retry conditions
- For category 4: improve eval pipeline error logging
