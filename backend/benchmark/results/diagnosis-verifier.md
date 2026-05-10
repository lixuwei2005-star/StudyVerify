# Verifier False-Reject Diagnosis

- Source eval: `benchmark/results/2026-05-05_14-08-23_eval.json`
- False-rejected references inspected: 60

## Summary by category

| Category | Count | Description |
|---|---:|---|
| 1 | 0 | sandbox couldn't run code |
| 2 | 0 | tests reported some failures |
| 3 | 0 | tests passed but verifier rejected |
| 4 | 60 | unknown / missing data |

## Data availability check

The persisted false-reject records contain only the eval summary fields `success`, `latency_ms`, `verifier_judged_pass`, `expected_pass`, `verifier_correct`, and `error`. They do not include the raw `/verify` payload needed to inspect sandbox errors, per-test outcomes, or LLM diagnosis text.

## Category 1 - sandbox issues (0 problems)

_No problems in this category._

## Category 2 - test failures (0 problems)

_No problems in this category._

## Category 3 - anti-leak over-rejection (0 problems)

_No problems in this category._

## Category 4 - unknown / missing data (60 problems)

These records have `reference_check.verifier_correct=False`, but the eval artifact does not include `sandbox_error`, `test_results`, or `diagnosis`. That means the original rejection reason cannot be recovered from `2026-05-05_14-08-23_eval.json` alone.

### `lc-001-two-sum`

- `verifier_judged_pass`: `False`
- `reference_solution` snippet:

```python
def two_sum(nums, target):
    seen = {}
    for i, n in enumerate(nums):
        if target - n in seen:
            return [seen[target - n], i]
```

- `reference_check` fields present: `error, expected_pass, latency_ms, success, verifier_correct, verifier_judged_pass`
- `sandbox_error`: _not present_
- `test_results`: _not present_
- `diagnosis`: _not present_
- Hypothesis: Missing instrumentation in the eval artifact, not enough evidence to tell whether sandbox, dataset tests, or the LLM judge caused this rejection.

### `lc-009-palindrome-number`

- `verifier_judged_pass`: `False`
- `reference_solution` snippet:

```python
def is_palindrome(x):
    if x < 0:
        return False
    return str(x) == str(x)[::-1]
```

- `reference_check` fields present: `error, expected_pass, latency_ms, success, verifier_correct, verifier_judged_pass`
- `sandbox_error`: _not present_
- `test_results`: _not present_
- `diagnosis`: _not present_
- Hypothesis: Missing instrumentation in the eval artifact, not enough evidence to tell whether sandbox, dataset tests, or the LLM judge caused this rejection.

### `lc-412-fizz-buzz`

- `verifier_judged_pass`: `False`
- `reference_solution` snippet:

```python
def fizzbuzz(n):
    out = []
    for i in range(1, n + 1):
        if i % 15 == 0:
            out.append('FizzBuzz')
```

- `reference_check` fields present: `error, expected_pass, latency_ms, success, verifier_correct, verifier_judged_pass`
- `sandbox_error`: _not present_
- `test_results`: _not present_
- `diagnosis`: _not present_
- Hypothesis: Missing instrumentation in the eval artifact, not enough evidence to tell whether sandbox, dataset tests, or the LLM judge caused this rejection.

### `lc-509-fibonacci`

- `verifier_judged_pass`: `False`
- `reference_solution` snippet:

```python
def fibonacci(n):
    if n <= 0:
        return 0
    if n == 1:
        return 1
```

- `reference_check` fields present: `error, expected_pass, latency_ms, success, verifier_correct, verifier_judged_pass`
- `sandbox_error`: _not present_
- `test_results`: _not present_
- `diagnosis`: _not present_
- Hypothesis: Missing instrumentation in the eval artifact, not enough evidence to tell whether sandbox, dataset tests, or the LLM judge caused this rejection.

### `edu-004-find-max`

- `verifier_judged_pass`: `False`
- `reference_solution` snippet:

```python
def find_max(nums):
    if not nums:
        return None
    m = nums[0]
    for n in nums[1:]:
```

- `reference_check` fields present: `error, expected_pass, latency_ms, success, verifier_correct, verifier_judged_pass`
- `sandbox_error`: _not present_
- `test_results`: _not present_
- `diagnosis`: _not present_
- Hypothesis: Missing instrumentation in the eval artifact, not enough evidence to tell whether sandbox, dataset tests, or the LLM judge caused this rejection.

### `lc-977-squares-sorted-array`

- `verifier_judged_pass`: `False`
- `reference_solution` snippet:

```python
def squares_of_sorted_array(nums):
    return sorted(n * n for n in nums)
```

- `reference_check` fields present: `error, expected_pass, latency_ms, success, verifier_correct, verifier_judged_pass`
- `sandbox_error`: _not present_
- `test_results`: _not present_
- `diagnosis`: _not present_
- Hypothesis: Missing instrumentation in the eval artifact, not enough evidence to tell whether sandbox, dataset tests, or the LLM judge caused this rejection.

### `lc-020-valid-parentheses`

- `verifier_judged_pass`: `False`
- `reference_solution` snippet:

```python
def valid_parentheses(s):
    stack = []
    pairs = {')': '(', ']': '[', '}': '{'}
    for c in s:
        if c in '([{':
```

- `reference_check` fields present: `error, expected_pass, latency_ms, success, verifier_correct, verifier_judged_pass`
- `sandbox_error`: _not present_
- `test_results`: _not present_
- `diagnosis`: _not present_
- Hypothesis: Missing instrumentation in the eval artifact, not enough evidence to tell whether sandbox, dataset tests, or the LLM judge caused this rejection.

### `edu-005-merge-two-sorted-arrays`

- `verifier_judged_pass`: `False`
- `reference_solution` snippet:

```python
def merge_two_sorted_lists(a, b):
    result = []
    i = j = 0
    while i < len(a) and j < len(b):
        if a[i] <= b[j]:
```

- `reference_check` fields present: `error, expected_pass, latency_ms, success, verifier_correct, verifier_judged_pass`
- `sandbox_error`: _not present_
- `test_results`: _not present_
- `diagnosis`: _not present_
- Hypothesis: Missing instrumentation in the eval artifact, not enough evidence to tell whether sandbox, dataset tests, or the LLM judge caused this rejection.

### `lc-066-plus-one`

- `verifier_judged_pass`: `False`
- `reference_solution` snippet:

```python
def plus_one(digits):
    digits = list(digits)
    i = len(digits) - 1
    while i >= 0:
        if digits[i] < 9:
```

- `reference_check` fields present: `error, expected_pass, latency_ms, success, verifier_correct, verifier_judged_pass`
- `sandbox_error`: _not present_
- `test_results`: _not present_
- `diagnosis`: _not present_
- Hypothesis: Missing instrumentation in the eval artifact, not enough evidence to tell whether sandbox, dataset tests, or the LLM judge caused this rejection.

### `lc-067-add-binary`

- `verifier_judged_pass`: `False`
- `reference_solution` snippet:

```python
def add_binary(a, b):
    return bin(int(a, 2) + int(b, 2))[2:]
```

- `reference_check` fields present: `error, expected_pass, latency_ms, success, verifier_correct, verifier_judged_pass`
- `sandbox_error`: _not present_
- `test_results`: _not present_
- `diagnosis`: _not present_
- Hypothesis: Missing instrumentation in the eval artifact, not enough evidence to tell whether sandbox, dataset tests, or the LLM judge caused this rejection.

### `lc-242-valid-anagram`

- `verifier_judged_pass`: `False`
- `reference_solution` snippet:

```python
def valid_anagram(s, t):
    return sorted(s) == sorted(t)
```

- `reference_check` fields present: `error, expected_pass, latency_ms, success, verifier_correct, verifier_judged_pass`
- `sandbox_error`: _not present_
- `test_results`: _not present_
- `diagnosis`: _not present_
- Hypothesis: Missing instrumentation in the eval artifact, not enough evidence to tell whether sandbox, dataset tests, or the LLM judge caused this rejection.

### `lc-125-valid-palindrome`

- `verifier_judged_pass`: `False`
- `reference_solution` snippet:

```python
def valid_palindrome(s):
    cleaned = ''.join(c.lower() for c in s if c.isalnum())
    return cleaned == cleaned[::-1]
```

- `reference_check` fields present: `error, expected_pass, latency_ms, success, verifier_correct, verifier_judged_pass`
- `sandbox_error`: _not present_
- `test_results`: _not present_
- `diagnosis`: _not present_
- Hypothesis: Missing instrumentation in the eval artifact, not enough evidence to tell whether sandbox, dataset tests, or the LLM judge caused this rejection.

### `lc-387-first-unique-character`

- `verifier_judged_pass`: `False`
- `reference_solution` snippet:

```python
def first_unique_character(s):
    counts = {}
    for c in s:
        counts[c] = counts.get(c, 0) + 1
    for i, c in enumerate(s):
```

- `reference_check` fields present: `error, expected_pass, latency_ms, success, verifier_correct, verifier_judged_pass`
- `sandbox_error`: _not present_
- `test_results`: _not present_
- `diagnosis`: _not present_
- Hypothesis: Missing instrumentation in the eval artifact, not enough evidence to tell whether sandbox, dataset tests, or the LLM judge caused this rejection.

### `lc-1470-shuffle-array`

- `verifier_judged_pass`: `False`
- `reference_solution` snippet:

```python
def shuffle_array(nums, n):
    out = []
    for i in range(n):
        out.append(nums[i])
        out.append(nums[i + n])
```

- `reference_check` fields present: `error, expected_pass, latency_ms, success, verifier_correct, verifier_judged_pass`
- `sandbox_error`: _not present_
- `test_results`: _not present_
- `diagnosis`: _not present_
- Hypothesis: Missing instrumentation in the eval artifact, not enough evidence to tell whether sandbox, dataset tests, or the LLM judge caused this rejection.

### `lc-1672-richest-customer-wealth`

- `verifier_judged_pass`: `False`
- `reference_solution` snippet:

```python
def richest_customer_wealth(accounts):
    return max(sum(row) for row in accounts)
```

- `reference_check` fields present: `error, expected_pass, latency_ms, success, verifier_correct, verifier_judged_pass`
- `sandbox_error`: _not present_
- `test_results`: _not present_
- `diagnosis`: _not present_
- Hypothesis: Missing instrumentation in the eval artifact, not enough evidence to tell whether sandbox, dataset tests, or the LLM judge caused this rejection.

### `lc-338-counting-bits`

- `verifier_judged_pass`: `False`
- `reference_solution` snippet:

```python
def counting_bits(n):
    return [bin(i).count('1') for i in range(n + 1)]
```

- `reference_check` fields present: `error, expected_pass, latency_ms, success, verifier_correct, verifier_judged_pass`
- `sandbox_error`: _not present_
- `test_results`: _not present_
- `diagnosis`: _not present_
- Hypothesis: Missing instrumentation in the eval artifact, not enough evidence to tell whether sandbox, dataset tests, or the LLM judge caused this rejection.

### `lc-448-find-disappeared-numbers`

- `verifier_judged_pass`: `False`
- `reference_solution` snippet:

```python
def find_disappeared_numbers(nums):
    s = set(nums)
    return [i for i in range(1, len(nums) + 1) if i not in s]
```

- `reference_check` fields present: `error, expected_pass, latency_ms, success, verifier_correct, verifier_judged_pass`
- `sandbox_error`: _not present_
- `test_results`: _not present_
- `diagnosis`: _not present_
- Hypothesis: Missing instrumentation in the eval artifact, not enough evidence to tell whether sandbox, dataset tests, or the LLM judge caused this rejection.

### `lc-136-single-number`

- `verifier_judged_pass`: `False`
- `reference_solution` snippet:

```python
def single_number(nums):
    result = 0
    for n in nums:
        result ^= n
    return result
```

- `reference_check` fields present: `error, expected_pass, latency_ms, success, verifier_correct, verifier_judged_pass`
- `sandbox_error`: _not present_
- `test_results`: _not present_
- `diagnosis`: _not present_
- Hypothesis: Missing instrumentation in the eval artifact, not enough evidence to tell whether sandbox, dataset tests, or the LLM judge caused this rejection.

### `lc-202-happy-number`

- `verifier_judged_pass`: `False`
- `reference_solution` snippet:

```python
def happy_number(n):
    seen = set()
    while n != 1 and n not in seen:
        seen.add(n)
        n = sum(int(d) ** 2 for d in str(n))
```

- `reference_check` fields present: `error, expected_pass, latency_ms, success, verifier_correct, verifier_judged_pass`
- `sandbox_error`: _not present_
- `test_results`: _not present_
- `diagnosis`: _not present_
- Hypothesis: Missing instrumentation in the eval artifact, not enough evidence to tell whether sandbox, dataset tests, or the LLM judge caused this rejection.

### `lc-171-excel-column-number`

- `verifier_judged_pass`: `False`
- `reference_solution` snippet:

```python
def excel_sheet_column_number(s):
    result = 0
    for c in s:
        result = result * 26 + (ord(c) - ord('A') + 1)
    return result
```

- `reference_check` fields present: `error, expected_pass, latency_ms, success, verifier_correct, verifier_judged_pass`
- `sandbox_error`: _not present_
- `test_results`: _not present_
- `diagnosis`: _not present_
- Hypothesis: Missing instrumentation in the eval artifact, not enough evidence to tell whether sandbox, dataset tests, or the LLM judge caused this rejection.

### `lc-013-roman-to-integer`

- `verifier_judged_pass`: `False`
- `reference_solution` snippet:

```python
def roman_to_integer(s):
    vals = {'I': 1, 'V': 5, 'X': 10, 'L': 50, 'C': 100, 'D': 500, 'M': 1000}
    result = 0
    for i, c in enumerate(s):
        if i + 1 < len(s) and vals[c] < vals[s[i + 1]]:
```

- `reference_check` fields present: `error, expected_pass, latency_ms, success, verifier_correct, verifier_judged_pass`
- `sandbox_error`: _not present_
- `test_results`: _not present_
- `diagnosis`: _not present_
- Hypothesis: Missing instrumentation in the eval artifact, not enough evidence to tell whether sandbox, dataset tests, or the LLM judge caused this rejection.

### `hr-002-palindrome-linked-list`

- `verifier_judged_pass`: `False`
- `reference_solution` snippet:

```python
def is_palindrome_list(nums):
    return list(nums) == list(nums)[::-1]
```

- `reference_check` fields present: `error, expected_pass, latency_ms, success, verifier_correct, verifier_judged_pass`
- `sandbox_error`: _not present_
- `test_results`: _not present_
- `diagnosis`: _not present_
- Hypothesis: Missing instrumentation in the eval artifact, not enough evidence to tell whether sandbox, dataset tests, or the LLM judge caused this rejection.

### `hr-004-find-kth-largest`

- `verifier_judged_pass`: `False`
- `reference_solution` snippet:

```python
def find_kth_largest(nums, k):
    return sorted(nums, reverse=True)[k - 1]
```

- `reference_check` fields present: `error, expected_pass, latency_ms, success, verifier_correct, verifier_judged_pass`
- `sandbox_error`: _not present_
- `test_results`: _not present_
- `diagnosis`: _not present_
- Hypothesis: Missing instrumentation in the eval artifact, not enough evidence to tell whether sandbox, dataset tests, or the LLM judge caused this rejection.

### `hr-005-remove-element-by-value`

- `verifier_judged_pass`: `False`
- `reference_solution` snippet:

```python
def remove_element(nums, v):
    return [n for n in nums if n != v]
```

- `reference_check` fields present: `error, expected_pass, latency_ms, success, verifier_correct, verifier_judged_pass`
- `sandbox_error`: _not present_
- `test_results`: _not present_
- `diagnosis`: _not present_
- Hypothesis: Missing instrumentation in the eval artifact, not enough evidence to tell whether sandbox, dataset tests, or the LLM judge caused this rejection.

### `hr-006-rotate-array-by-k`

- `verifier_judged_pass`: `False`
- `reference_solution` snippet:

```python
def rotate_array(nums, k):
    if not nums:
        return []
    k = k % len(nums)
    return list(nums[-k:]) + list(nums[:-k]) if k else list(nums)
```

- `reference_check` fields present: `error, expected_pass, latency_ms, success, verifier_correct, verifier_judged_pass`
- `sandbox_error`: _not present_
- `test_results`: _not present_
- `diagnosis`: _not present_
- Hypothesis: Missing instrumentation in the eval artifact, not enough evidence to tell whether sandbox, dataset tests, or the LLM judge caused this rejection.

### `hr-007-intersection-arrays`

- `verifier_judged_pass`: `False`
- `reference_solution` snippet:

```python
def intersect_arrays(a, b):
    return sorted(set(a) & set(b))
```

- `reference_check` fields present: `error, expected_pass, latency_ms, success, verifier_correct, verifier_judged_pass`
- `sandbox_error`: _not present_
- `test_results`: _not present_
- `diagnosis`: _not present_
- Hypothesis: Missing instrumentation in the eval artifact, not enough evidence to tell whether sandbox, dataset tests, or the LLM judge caused this rejection.

### `hr-008-symmetric-difference`

- `verifier_judged_pass`: `False`
- `reference_solution` snippet:

```python
def sym_diff(a, b):
    return sorted(set(a) ^ set(b))
```

- `reference_check` fields present: `error, expected_pass, latency_ms, success, verifier_correct, verifier_judged_pass`
- `sandbox_error`: _not present_
- `test_results`: _not present_
- `diagnosis`: _not present_
- Hypothesis: Missing instrumentation in the eval artifact, not enough evidence to tell whether sandbox, dataset tests, or the LLM judge caused this rejection.

### `hr-010-largest-window-sum`

- `verifier_judged_pass`: `False`
- `reference_solution` snippet:

```python
def largest_window_sum(nums, k):
    return max(sum(nums[i:i + k]) for i in range(len(nums) - k + 1))
```

- `reference_check` fields present: `error, expected_pass, latency_ms, success, verifier_correct, verifier_judged_pass`
- `sandbox_error`: _not present_
- `test_results`: _not present_
- `diagnosis`: _not present_
- Hypothesis: Missing instrumentation in the eval artifact, not enough evidence to tell whether sandbox, dataset tests, or the LLM judge caused this rejection.

### `hr-012-tree-is-balanced`

- `verifier_judged_pass`: `False`
- `reference_solution` snippet:

```python
class _N:
    def __init__(self, v):
        self.v, self.l, self.r = v, None, None

def _build(lst):
```

- `reference_check` fields present: `error, expected_pass, latency_ms, success, verifier_correct, verifier_judged_pass`
- `sandbox_error`: _not present_
- `test_results`: _not present_
- `diagnosis`: _not present_
- Hypothesis: Missing instrumentation in the eval artifact, not enough evidence to tell whether sandbox, dataset tests, or the LLM judge caused this rejection.

### `edu-102-count-distinct-chars`

- `verifier_judged_pass`: `False`
- `reference_solution` snippet:

```python
def count_distinct(s):
    return len(set(s))
```

- `reference_check` fields present: `error, expected_pass, latency_ms, success, verifier_correct, verifier_judged_pass`
- `sandbox_error`: _not present_
- `test_results`: _not present_
- `diagnosis`: _not present_
- Hypothesis: Missing instrumentation in the eval artifact, not enough evidence to tell whether sandbox, dataset tests, or the LLM judge caused this rejection.

### `edu-104-capitalize-each-word`

- `verifier_judged_pass`: `False`
- `reference_solution` snippet:

```python
def capitalize_each(s):
    return ' '.join(w.capitalize() for w in s.split(' '))
```

- `reference_check` fields present: `error, expected_pass, latency_ms, success, verifier_correct, verifier_judged_pass`
- `sandbox_error`: _not present_
- `test_results`: _not present_
- `diagnosis`: _not present_
- Hypothesis: Missing instrumentation in the eval artifact, not enough evidence to tell whether sandbox, dataset tests, or the LLM judge caused this rejection.

### `edu-105-remove-duplicate-chars`

- `verifier_judged_pass`: `False`
- `reference_solution` snippet:

```python
def remove_duplicates_str(s):
    seen = set()
    out = []
    for c in s:
        if c not in seen:
```

- `reference_check` fields present: `error, expected_pass, latency_ms, success, verifier_correct, verifier_judged_pass`
- `sandbox_error`: _not present_
- `test_results`: _not present_
- `diagnosis`: _not present_
- Hypothesis: Missing instrumentation in the eval artifact, not enough evidence to tell whether sandbox, dataset tests, or the LLM judge caused this rejection.

### `edu-106-longest-substring-no-repeat`

- `verifier_judged_pass`: `False`
- `reference_solution` snippet:

```python
def longest_no_repeat(s):
    seen = {}
    best = 0
    start = 0
    for i, c in enumerate(s):
```

- `reference_check` fields present: `error, expected_pass, latency_ms, success, verifier_correct, verifier_judged_pass`
- `sandbox_error`: _not present_
- `test_results`: _not present_
- `diagnosis`: _not present_
- Hypothesis: Missing instrumentation in the eval artifact, not enough evidence to tell whether sandbox, dataset tests, or the LLM judge caused this rejection.

### `edu-107-string-to-int`

- `verifier_judged_pass`: `False`
- `reference_solution` snippet:

```python
def atoi(s):
    s = s.lstrip()
    if not s:
        return 0
    sign = 1
```

- `reference_check` fields present: `error, expected_pass, latency_ms, success, verifier_correct, verifier_judged_pass`
- `sandbox_error`: _not present_
- `test_results`: _not present_
- `diagnosis`: _not present_
- Hypothesis: Missing instrumentation in the eval artifact, not enough evidence to tell whether sandbox, dataset tests, or the LLM judge caused this rejection.

### `edu-108-int-to-binary`

- `verifier_judged_pass`: `False`
- `reference_solution` snippet:

```python
def to_binary(n):
    return bin(n)[2:] if n > 0 else '0'
```

- `reference_check` fields present: `error, expected_pass, latency_ms, success, verifier_correct, verifier_judged_pass`
- `sandbox_error`: _not present_
- `test_results`: _not present_
- `diagnosis`: _not present_
- Hypothesis: Missing instrumentation in the eval artifact, not enough evidence to tell whether sandbox, dataset tests, or the LLM judge caused this rejection.

### `edu-112-count-set-bits`

- `verifier_judged_pass`: `False`
- `reference_solution` snippet:

```python
def count_set_bits(n):
    return bin(n).count('1')
```

- `reference_check` fields present: `error, expected_pass, latency_ms, success, verifier_correct, verifier_judged_pass`
- `sandbox_error`: _not present_
- `test_results`: _not present_
- `diagnosis`: _not present_
- Hypothesis: Missing instrumentation in the eval artifact, not enough evidence to tell whether sandbox, dataset tests, or the LLM judge caused this rejection.

### `edu-113-fibonacci-recursive`

- `verifier_judged_pass`: `False`
- `reference_solution` snippet:

```python
def fib_rec(n):
    if n <= 0:
        return 0
    if n == 1:
        return 1
```

- `reference_check` fields present: `error, expected_pass, latency_ms, success, verifier_correct, verifier_judged_pass`
- `sandbox_error`: _not present_
- `test_results`: _not present_
- `diagnosis`: _not present_
- Hypothesis: Missing instrumentation in the eval artifact, not enough evidence to tell whether sandbox, dataset tests, or the LLM judge caused this rejection.

### `p3-a-002-format-phone`

- `verifier_judged_pass`: `False`
- `reference_solution` snippet:

```python
def format_phone(s):
    return f'({s[:3]}) {s[3:6]}-{s[6:]}'
```

- `reference_check` fields present: `error, expected_pass, latency_ms, success, verifier_correct, verifier_judged_pass`
- `sandbox_error`: _not present_
- `test_results`: _not present_
- `diagnosis`: _not present_
- Hypothesis: Missing instrumentation in the eval artifact, not enough evidence to tell whether sandbox, dataset tests, or the LLM judge caused this rejection.

### `p3-a-003-count-substring`

- `verifier_judged_pass`: `False`
- `reference_solution` snippet:

```python
def count_substring(s, sub):
    return s.count(sub)
```

- `reference_check` fields present: `error, expected_pass, latency_ms, success, verifier_correct, verifier_judged_pass`
- `sandbox_error`: _not present_
- `test_results`: _not present_
- `diagnosis`: _not present_
- Hypothesis: Missing instrumentation in the eval artifact, not enough evidence to tell whether sandbox, dataset tests, or the LLM judge caused this rejection.

### `p3-a-004-spiral-matrix`

- `verifier_judged_pass`: `False`
- `reference_solution` snippet:

```python
def spiral_order(matrix):
    if not matrix or not matrix[0]:
        return []
    out = []
    top, bottom = 0, len(matrix) - 1
```

- `reference_check` fields present: `error, expected_pass, latency_ms, success, verifier_correct, verifier_judged_pass`
- `sandbox_error`: _not present_
- `test_results`: _not present_
- `diagnosis`: _not present_
- Hypothesis: Missing instrumentation in the eval artifact, not enough evidence to tell whether sandbox, dataset tests, or the LLM judge caused this rejection.

### `p3-a-008-word-pattern`

- `verifier_judged_pass`: `False`
- `reference_solution` snippet:

```python
def word_pattern(pattern, sentence):
    words = sentence.split(' ')
    if len(pattern) != len(words):
        return False
    p2w, w2p = {}, {}
```

- `reference_check` fields present: `error, expected_pass, latency_ms, success, verifier_correct, verifier_judged_pass`
- `sandbox_error`: _not present_
- `test_results`: _not present_
- `diagnosis`: _not present_
- Hypothesis: Missing instrumentation in the eval artifact, not enough evidence to tell whether sandbox, dataset tests, or the LLM judge caused this rejection.

### `p3-a-010-detect-capital`

- `verifier_judged_pass`: `False`
- `reference_solution` snippet:

```python
def detect_capital(word):
    return word.isupper() or word.islower() or word.istitle()
```

- `reference_check` fields present: `error, expected_pass, latency_ms, success, verifier_correct, verifier_judged_pass`
- `sandbox_error`: _not present_
- `test_results`: _not present_
- `diagnosis`: _not present_
- Hypothesis: Missing instrumentation in the eval artifact, not enough evidence to tell whether sandbox, dataset tests, or the LLM judge caused this rejection.

### `p3-a-012-distribute-candies`

- `verifier_judged_pass`: `False`
- `reference_solution` snippet:

```python
def distribute_candies(candies):
    return min(len(set(candies)), len(candies) // 2)
```

- `reference_check` fields present: `error, expected_pass, latency_ms, success, verifier_correct, verifier_judged_pass`
- `sandbox_error`: _not present_
- `test_results`: _not present_
- `diagnosis`: _not present_
- Hypothesis: Missing instrumentation in the eval artifact, not enough evidence to tell whether sandbox, dataset tests, or the LLM judge caused this rejection.

### `p3-a-014-integer-break`

- `verifier_judged_pass`: `False`
- `reference_solution` snippet:

```python
def integer_break(n):
    dp = [0] * (n + 1)
    dp[1] = 1
    for i in range(2, n + 1):
        best = 0
```

- `reference_check` fields present: `error, expected_pass, latency_ms, success, verifier_correct, verifier_judged_pass`
- `sandbox_error`: _not present_
- `test_results`: _not present_
- `diagnosis`: _not present_
- Hypothesis: Missing instrumentation in the eval artifact, not enough evidence to tell whether sandbox, dataset tests, or the LLM judge caused this rejection.

### `p3-a-015-zigzag-string`

- `verifier_judged_pass`: `False`
- `reference_solution` snippet:

```python
def zigzag_convert(s, numRows):
    if numRows == 1 or numRows >= len(s):
        return s
    rows = [''] * numRows
    cur = 0
```

- `reference_check` fields present: `error, expected_pass, latency_ms, success, verifier_correct, verifier_judged_pass`
- `sandbox_error`: _not present_
- `test_results`: _not present_
- `diagnosis`: _not present_
- Hypothesis: Missing instrumentation in the eval artifact, not enough evidence to tell whether sandbox, dataset tests, or the LLM judge caused this rejection.

### `p3-a-016-pascals-triangle-row`

- `verifier_judged_pass`: `False`
- `reference_solution` snippet:

```python
def pascals_row(rowIndex):
    row = [1]
    for _ in range(rowIndex):
        row = [a + b for a, b in zip([0] + row, row + [0])]
    return row
```

- `reference_check` fields present: `error, expected_pass, latency_ms, success, verifier_correct, verifier_judged_pass`
- `sandbox_error`: _not present_
- `test_results`: _not present_
- `diagnosis`: _not present_
- Hypothesis: Missing instrumentation in the eval artifact, not enough evidence to tell whether sandbox, dataset tests, or the LLM judge caused this rejection.

### `p3-a-017-reverse-vowels`

- `verifier_judged_pass`: `False`
- `reference_solution` snippet:

```python
def reverse_vowels(s):
    chars = list(s)
    vowels = set('aeiouAEIOU')
    i, j = 0, len(chars) - 1
    while i < j:
```

- `reference_check` fields present: `error, expected_pass, latency_ms, success, verifier_correct, verifier_judged_pass`
- `sandbox_error`: _not present_
- `test_results`: _not present_
- `diagnosis`: _not present_
- Hypothesis: Missing instrumentation in the eval artifact, not enough evidence to tell whether sandbox, dataset tests, or the LLM judge caused this rejection.

### `p3-a-018-array-partition`

- `verifier_judged_pass`: `False`
- `reference_solution` snippet:

```python
def array_partition(nums):
    return sum(sorted(nums)[::2])
```

- `reference_check` fields present: `error, expected_pass, latency_ms, success, verifier_correct, verifier_judged_pass`
- `sandbox_error`: _not present_
- `test_results`: _not present_
- `diagnosis`: _not present_
- Hypothesis: Missing instrumentation in the eval artifact, not enough evidence to tell whether sandbox, dataset tests, or the LLM judge caused this rejection.

### `p3-a-019-third-max`

- `verifier_judged_pass`: `False`
- `reference_solution` snippet:

```python
def third_max(nums):
    distinct = sorted(set(nums), reverse=True)
    return distinct[2] if len(distinct) >= 3 else distinct[0]
```

- `reference_check` fields present: `error, expected_pass, latency_ms, success, verifier_correct, verifier_judged_pass`
- `sandbox_error`: _not present_
- `test_results`: _not present_
- `diagnosis`: _not present_
- Hypothesis: Missing instrumentation in the eval artifact, not enough evidence to tell whether sandbox, dataset tests, or the LLM judge caused this rejection.

### `p3-a-020-add-strings`

- `verifier_judged_pass`: `False`
- `reference_solution` snippet:

```python
def add_strings(num1, num2):
    i, j = len(num1) - 1, len(num2) - 1
    carry = 0
    out = []
    while i >= 0 or j >= 0 or carry:
```

- `reference_check` fields present: `error, expected_pass, latency_ms, success, verifier_correct, verifier_judged_pass`
- `sandbox_error`: _not present_
- `test_results`: _not present_
- `diagnosis`: _not present_
- Hypothesis: Missing instrumentation in the eval artifact, not enough evidence to tell whether sandbox, dataset tests, or the LLM judge caused this rejection.

### `p3-b-006-knn-majority-vote`

- `verifier_judged_pass`: `False`
- `reference_solution` snippet:

```python
def knn_vote(training, query, k):
    def dist(a, b):
        return sum((x - y) ** 2 for x, y in zip(a, b)) ** 0.5
    nearest = sorted(training, key=lambda t: dist(t[0], query))[:k]
    counts = {}
```

- `reference_check` fields present: `error, expected_pass, latency_ms, success, verifier_correct, verifier_judged_pass`
- `sandbox_error`: _not present_
- `test_results`: _not present_
- `diagnosis`: _not present_
- Hypothesis: Missing instrumentation in the eval artifact, not enough evidence to tell whether sandbox, dataset tests, or the LLM judge caused this rejection.

### `p3-b-008-logistic-regression-step`

- `verifier_judged_pass`: `False`
- `reference_solution` snippet:

```python
def lr_step(x, y, weights, bias, lr):
    import math
    z = sum(w * xi for w, xi in zip(weights, x)) + bias
    if z >= 0:
        p = 1 / (1 + math.exp(-z))
```

- `reference_check` fields present: `error, expected_pass, latency_ms, success, verifier_correct, verifier_judged_pass`
- `sandbox_error`: _not present_
- `test_results`: _not present_
- `diagnosis`: _not present_
- Hypothesis: Missing instrumentation in the eval artifact, not enough evidence to tell whether sandbox, dataset tests, or the LLM judge caused this rejection.

### `p3-b-009-relu`

- `verifier_judged_pass`: `False`
- `reference_solution` snippet:

```python
def relu(xs):
    return [max(0, x) for x in xs]
```

- `reference_check` fields present: `error, expected_pass, latency_ms, success, verifier_correct, verifier_judged_pass`
- `sandbox_error`: _not present_
- `test_results`: _not present_
- `diagnosis`: _not present_
- Hypothesis: Missing instrumentation in the eval artifact, not enough evidence to tell whether sandbox, dataset tests, or the LLM judge caused this rejection.

### `p3-c-001-recursive-flatten`

- `verifier_judged_pass`: `False`
- `reference_solution` snippet:

```python
def deep_flatten(nested):
    out = []
    for item in nested:
        if isinstance(item, list):
            out.extend(deep_flatten(item))
```

- `reference_check` fields present: `error, expected_pass, latency_ms, success, verifier_correct, verifier_judged_pass`
- `sandbox_error`: _not present_
- `test_results`: _not present_
- `diagnosis`: _not present_
- Hypothesis: Missing instrumentation in the eval artifact, not enough evidence to tell whether sandbox, dataset tests, or the LLM judge caused this rejection.

### `p3-c-002-cumulative-distinct`

- `verifier_judged_pass`: `False`
- `reference_solution` snippet:

```python
def cumulative_distinct(nums):
    seen = set()
    out = []
    for n in nums:
        seen.add(n)
```

- `reference_check` fields present: `error, expected_pass, latency_ms, success, verifier_correct, verifier_judged_pass`
- `sandbox_error`: _not present_
- `test_results`: _not present_
- `diagnosis`: _not present_
- Hypothesis: Missing instrumentation in the eval artifact, not enough evidence to tell whether sandbox, dataset tests, or the LLM judge caused this rejection.

### `p3-c-003-is-prime-naive`

- `verifier_judged_pass`: `False`
- `reference_solution` snippet:

```python
def is_prime_naive(n):
    if n < 2:
        return False
    for i in range(2, int(n ** 0.5) + 1):
        if n % i == 0:
```

- `reference_check` fields present: `error, expected_pass, latency_ms, success, verifier_correct, verifier_judged_pass`
- `sandbox_error`: _not present_
- `test_results`: _not present_
- `diagnosis`: _not present_
- Hypothesis: Missing instrumentation in the eval artifact, not enough evidence to tell whether sandbox, dataset tests, or the LLM judge caused this rejection.

### `p3-c-005-transpose-no-zip`

- `verifier_judged_pass`: `False`
- `reference_solution` snippet:

```python
def transpose_no_zip(m):
    rows = len(m)
    cols = len(m[0])
    out = [[0] * rows for _ in range(cols)]
    for i in range(rows):
```

- `reference_check` fields present: `error, expected_pass, latency_ms, success, verifier_correct, verifier_judged_pass`
- `sandbox_error`: _not present_
- `test_results`: _not present_
- `diagnosis`: _not present_
- Hypothesis: Missing instrumentation in the eval artifact, not enough evidence to tell whether sandbox, dataset tests, or the LLM judge caused this rejection.

### `p3-c-007-balanced-parens-simple`

- `verifier_judged_pass`: `False`
- `reference_solution` snippet:

```python
def balanced_parens(s):
    depth = 0
    for c in s:
        if c == '(':
            depth += 1
```

- `reference_check` fields present: `error, expected_pass, latency_ms, success, verifier_correct, verifier_judged_pass`
- `sandbox_error`: _not present_
- `test_results`: _not present_
- `diagnosis`: _not present_
- Hypothesis: Missing instrumentation in the eval artifact, not enough evidence to tell whether sandbox, dataset tests, or the LLM judge caused this rejection.

### `p3-c-009-caesar-cipher`

- `verifier_judged_pass`: `False`
- `reference_solution` snippet:

```python
def caesar_encrypt(s, shift):
    out = []
    for c in s:
        if 'a' <= c <= 'z':
            out.append(chr((ord(c) - ord('a') + shift) % 26 + ord('a')))
```

- `reference_check` fields present: `error, expected_pass, latency_ms, success, verifier_correct, verifier_judged_pass`
- `sandbox_error`: _not present_
- `test_results`: _not present_
- `diagnosis`: _not present_
- Hypothesis: Missing instrumentation in the eval artifact, not enough evidence to tell whether sandbox, dataset tests, or the LLM judge caused this rejection.

### `p3-c-010-word-frequency-no-counter`

- `verifier_judged_pass`: `False`
- `reference_solution` snippet:

```python
def word_freq(text):
    counts = {}
    for w in text.split(' '):
        w = w.lower()
        counts[w] = counts.get(w, 0) + 1
```

- `reference_check` fields present: `error, expected_pass, latency_ms, success, verifier_correct, verifier_judged_pass`
- `sandbox_error`: _not present_
- `test_results`: _not present_
- `diagnosis`: _not present_
- Hypothesis: Missing instrumentation in the eval artifact, not enough evidence to tell whether sandbox, dataset tests, or the LLM judge caused this rejection.

## Conclusions

Hypothesis ranking:
1. Category 4 (60 problems): eval artifact omitted raw verify details
2. Category 1 (0 problems): sandbox bridge / function detection / import failure
3. Category 2 (0 problems): dataset reference or test-case mismatch
4. Category 3 (0 problems): LLM judge over-rejection after passing tests

Top data-backed hypothesis: the Step 9 eval pipeline discarded the raw `/verify` output for reference checks. Every false reject in this artifact has only the summary fields, so the immediate root cause is not identifiable from the saved JSON. A follow-up diagnostic run must persist `output.test_results`, `output.diagnosis`, and any `sandbox_error` before deciding between sandbox, dataset, or LLM-judge fixes.

## P0 fix paths

- For category 1: fix sandbox bridge / function detection
- For category 2: re-validate dataset references
- For category 3: tune LLM judge prompt or relax retry conditions
- For category 4: improve eval pipeline error logging

## Instrumentation gap to close before fixing

Because this artifact places all 60 failures in Category 4, the safest next step is not a verifier behavior change. First, run or patch a diagnostic capture that persists the full reference `/verify` output for these same problem IDs, including `output.verified`, `output.test_results`, `output.diagnosis`, and any sandbox error. Only then can Step 10 choose between sandbox, dataset, and LLM-judge fixes without guessing.
