# Verifier False-Reject Diagnosis

- Source eval: `benchmark/results/2026-05-10_step10_targeted_eval.json`
- Reference checks inspected: 69
- False-rejected references inspected: 56
- Reference checks with `raw_output`: 69/69

## Summary by category

| Category | Count | Description |
|---|---:|---|
| 1 | 56 | sandbox couldn't run code |
| 2 | 0 | tests reported some failures |
| 3 | 0 | tests passed but verifier rejected |
| 4 | 0 | unknown / missing data |

## Data availability check

`raw_output` is present in this eval artifact.

Sample `raw_output` keys: `diagnosis, fail_count, pass_count, problem_id, sandbox_error, status, test_results, verified`

## Targeted rerun sanity

- Targeted original false-reject problem records in this eval: 60
- Targeted references with verifier result: 59
- Targeted references missing/skipped before verify: 1
- Targeted IDs now verifier-correct: 6
- Targeted IDs still false-rejected: 53
- Targeted missing/skipped IDs: `p3-a-014-integer-break`
- Control problem records in this eval: 10
- Control references with verifier result: 10
- Control references missing/skipped before verify: 0
- Control references verifier-correct: 7
- Control references false-rejected: 3
- Control failure IDs: `edu-109-gcd`, `p3-a-011-summary-ranges`, `hr-003-middle-of-linked-list`

## Category 1 - sandbox issues (56 problems)

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

- `sandbox_error`: FATAL: function fib_n not defined or not callable
- Hypothesis: Function detection likely failed: expected entry function was not found or could not be imported.

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

- `sandbox_error`: FATAL: function find_largest not defined or not callable
- Hypothesis: Function detection likely failed: expected entry function was not found or could not be imported.

### `lc-977-squares-sorted-array`

- `verifier_judged_pass`: `False`
- `reference_solution` snippet:

```python
def squares_of_sorted_array(nums):
    return sorted(n * n for n in nums)
```

- `sandbox_error`: FATAL: function sorted_squares not defined or not callable
- Hypothesis: Function detection likely failed: expected entry function was not found or could not be imported.

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

- `sandbox_error`: FATAL: function is_valid not defined or not callable
- Hypothesis: Function detection likely failed: expected entry function was not found or could not be imported.

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

- `sandbox_error`: FATAL: function merge_sorted_lists not defined or not callable
- Hypothesis: Function detection likely failed: expected entry function was not found or could not be imported.

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

- `sandbox_error`: FATAL: function plusOne not defined or not callable
- Hypothesis: Function detection likely failed: expected entry function was not found or could not be imported.

### `lc-067-add-binary`

- `verifier_judged_pass`: `False`
- `reference_solution` snippet:

```python
def add_binary(a, b):
    return bin(int(a, 2) + int(b, 2))[2:]
```

- `sandbox_error`: FATAL: function addBinary not defined or not callable
- Hypothesis: Function detection likely failed: expected entry function was not found or could not be imported.

### `lc-242-valid-anagram`

- `verifier_judged_pass`: `False`
- `reference_solution` snippet:

```python
def valid_anagram(s, t):
    return sorted(s) == sorted(t)
```

- `sandbox_error`: FATAL: function is_anagram not defined or not callable
- Hypothesis: Function detection likely failed: expected entry function was not found or could not be imported.

### `lc-125-valid-palindrome`

- `verifier_judged_pass`: `False`
- `reference_solution` snippet:

```python
def valid_palindrome(s):
    cleaned = ''.join(c.lower() for c in s if c.isalnum())
    return cleaned == cleaned[::-1]
```

- `sandbox_error`: FATAL: function isPalindrome not defined or not callable
- Hypothesis: Function detection likely failed: expected entry function was not found or could not be imported.

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

- `sandbox_error`: FATAL: function firstUniqChar not defined or not callable
- Hypothesis: Function detection likely failed: expected entry function was not found or could not be imported.

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

- `sandbox_error`: FATAL: function shuffle not defined or not callable
- Hypothesis: Function detection likely failed: expected entry function was not found or could not be imported.

### `lc-1672-richest-customer-wealth`

- `verifier_judged_pass`: `False`
- `reference_solution` snippet:

```python
def richest_customer_wealth(accounts):
    return max(sum(row) for row in accounts)
```

- `sandbox_error`: FATAL: function maximumWealth not defined or not callable
- Hypothesis: Function detection likely failed: expected entry function was not found or could not be imported.

### `lc-338-counting-bits`

- `verifier_judged_pass`: `False`
- `reference_solution` snippet:

```python
def counting_bits(n):
    return [bin(i).count('1') for i in range(n + 1)]
```

- `sandbox_error`: FATAL: function countBits not defined or not callable
- Hypothesis: Function detection likely failed: expected entry function was not found or could not be imported.

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

- `sandbox_error`: FATAL: function is_happy not defined or not callable
- Hypothesis: Function detection likely failed: expected entry function was not found or could not be imported.

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

- `sandbox_error`: FATAL: function titleToNumber not defined or not callable
- Hypothesis: Function detection likely failed: expected entry function was not found or could not be imported.

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

- `sandbox_error`: FATAL: function romanToInt not defined or not callable
- Hypothesis: Function detection likely failed: expected entry function was not found or could not be imported.

### `hr-002-palindrome-linked-list`

- `verifier_judged_pass`: `False`
- `reference_solution` snippet:

```python
def is_palindrome_list(nums):
    return list(nums) == list(nums)[::-1]
```

- `sandbox_error`: FATAL: function is_palindrome not defined or not callable
- Hypothesis: Function detection likely failed: expected entry function was not found or could not be imported.

### `hr-004-find-kth-largest`

- `verifier_judged_pass`: `False`
- `reference_solution` snippet:

```python
def find_kth_largest(nums, k):
    return sorted(nums, reverse=True)[k - 1]
```

- `sandbox_error`: FATAL: function kth_largest not defined or not callable
- Hypothesis: Function detection likely failed: expected entry function was not found or could not be imported.

### `hr-005-remove-element-by-value`

- `verifier_judged_pass`: `False`
- `reference_solution` snippet:

```python
def remove_element(nums, v):
    return [n for n in nums if n != v]
```

- `sandbox_error`: FATAL: function remove_all_occurrences not defined or not callable
- Hypothesis: Function detection likely failed: expected entry function was not found or could not be imported.

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

- `sandbox_error`: FATAL: function rotate not defined or not callable
- Hypothesis: Function detection likely failed: expected entry function was not found or could not be imported.

### `hr-007-intersection-arrays`

- `verifier_judged_pass`: `False`
- `reference_solution` snippet:

```python
def intersect_arrays(a, b):
    return sorted(set(a) & set(b))
```

- `sandbox_error`: FATAL: function common_elements not defined or not callable
- Hypothesis: Function detection likely failed: expected entry function was not found or could not be imported.

### `hr-008-symmetric-difference`

- `verifier_judged_pass`: `False`
- `reference_solution` snippet:

```python
def sym_diff(a, b):
    return sorted(set(a) ^ set(b))
```

- `sandbox_error`: FATAL: function xor_lists not defined or not callable
- Hypothesis: Function detection likely failed: expected entry function was not found or could not be imported.

### `hr-010-largest-window-sum`

- `verifier_judged_pass`: `False`
- `reference_solution` snippet:

```python
def largest_window_sum(nums, k):
    return max(sum(nums[i:i + k]) for i in range(len(nums) - k + 1))
```

- `sandbox_error`: FATAL: function max_sum_sublist not defined or not callable
- Hypothesis: Function detection likely failed: expected entry function was not found or could not be imported.

### `edu-102-count-distinct-chars`

- `verifier_judged_pass`: `False`
- `reference_solution` snippet:

```python
def count_distinct(s):
    return len(set(s))
```

- `sandbox_error`: FATAL: function count_distinct_characters not defined or not callable
- Hypothesis: Function detection likely failed: expected entry function was not found or could not be imported.

### `edu-104-capitalize-each-word`

- `verifier_judged_pass`: `False`
- `reference_solution` snippet:

```python
def capitalize_each(s):
    return ' '.join(w.capitalize() for w in s.split(' '))
```

- `sandbox_error`: FATAL: function cap_first not defined or not callable
- Hypothesis: Function detection likely failed: expected entry function was not found or could not be imported.

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

- `sandbox_error`: FATAL: function remove_duplicates not defined or not callable
- Hypothesis: Function detection likely failed: expected entry function was not found or could not be imported.

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

- `sandbox_error`: FATAL: function longest_substring_distinct not defined or not callable
- Hypothesis: Function detection likely failed: expected entry function was not found or could not be imported.

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

- `sandbox_error`: FATAL: function myAtoi not defined or not callable
- Hypothesis: Function detection likely failed: expected entry function was not found or could not be imported.

### `edu-108-int-to-binary`

- `verifier_judged_pass`: `False`
- `reference_solution` snippet:

```python
def to_binary(n):
    return bin(n)[2:] if n > 0 else '0'
```

- `sandbox_error`: FATAL: function binary_conversion not defined or not callable
- Hypothesis: Function detection likely failed: expected entry function was not found or could not be imported.

### `edu-112-count-set-bits`

- `verifier_judged_pass`: `False`
- `reference_solution` snippet:

```python
def count_set_bits(n):
    return bin(n).count('1')
```

- `sandbox_error`: FATAL: function hamming_weight not defined or not callable
- Hypothesis: Function detection likely failed: expected entry function was not found or could not be imported.

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

- `sandbox_error`: FATAL: function fib not defined or not callable
- Hypothesis: Function detection likely failed: expected entry function was not found or could not be imported.

### `p3-a-002-format-phone`

- `verifier_judged_pass`: `False`
- `reference_solution` snippet:

```python
def format_phone(s):
    return f'({s[:3]}) {s[3:6]}-{s[6:]}'
```

- `sandbox_error`: FATAL: function format_phone_number not defined or not callable
- Hypothesis: Function detection likely failed: expected entry function was not found or could not be imported.

### `p3-a-003-count-substring`

- `verifier_judged_pass`: `False`
- `reference_solution` snippet:

```python
def count_substring(s, sub):
    return s.count(sub)
```

- `sandbox_error`: FATAL: function count_non_overlapping not defined or not callable
- Hypothesis: Function detection likely failed: expected entry function was not found or could not be imported.

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

- `sandbox_error`: FATAL: function spiralOrder not defined or not callable
- Hypothesis: Function detection likely failed: expected entry function was not found or could not be imported.

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

- `sandbox_error`: FATAL: function wordPattern not defined or not callable
- Hypothesis: Function detection likely failed: expected entry function was not found or could not be imported.

### `p3-a-010-detect-capital`

- `verifier_judged_pass`: `False`
- `reference_solution` snippet:

```python
def detect_capital(word):
    return word.isupper() or word.islower() or word.istitle()
```

- `sandbox_error`: FATAL: function detectCapitalUse not defined or not callable
- Hypothesis: Function detection likely failed: expected entry function was not found or could not be imported.

### `p3-a-012-distribute-candies`

- `verifier_judged_pass`: `False`
- `reference_solution` snippet:

```python
def distribute_candies(candies):
    return min(len(set(candies)), len(candies) // 2)
```

- `sandbox_error`: FATAL: function distributeCandies not defined or not callable
- Hypothesis: Function detection likely failed: expected entry function was not found or could not be imported.

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

- `sandbox_error`: FATAL: function convert not defined or not callable
- Hypothesis: Function detection likely failed: expected entry function was not found or could not be imported.

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

- `sandbox_error`: FATAL: function getRow not defined or not callable
- Hypothesis: Function detection likely failed: expected entry function was not found or could not be imported.

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

- `sandbox_error`: FATAL: function reverseVowels not defined or not callable
- Hypothesis: Function detection likely failed: expected entry function was not found or could not be imported.

### `p3-a-018-array-partition`

- `verifier_judged_pass`: `False`
- `reference_solution` snippet:

```python
def array_partition(nums):
    return sum(sorted(nums)[::2])
```

- `sandbox_error`: FATAL: function arrayPairSum not defined or not callable
- Hypothesis: Function detection likely failed: expected entry function was not found or could not be imported.

### `p3-a-019-third-max`

- `verifier_judged_pass`: `False`
- `reference_solution` snippet:

```python
def third_max(nums):
    distinct = sorted(set(nums), reverse=True)
    return distinct[2] if len(distinct) >= 3 else distinct[0]
```

- `sandbox_error`: FATAL: function thirdMax not defined or not callable
- Hypothesis: Function detection likely failed: expected entry function was not found or could not be imported.

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

- `sandbox_error`: FATAL: function addStrings not defined or not callable
- Hypothesis: Function detection likely failed: expected entry function was not found or could not be imported.

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

- `sandbox_error`: FATAL: function k_nn not defined or not callable
- Hypothesis: Function detection likely failed: expected entry function was not found or could not be imported.

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

- `sandbox_error`: FATAL: function gradient_descent_step not defined or not callable
- Hypothesis: Function detection likely failed: expected entry function was not found or could not be imported.

### `p3-b-009-relu`

- `verifier_judged_pass`: `False`
- `reference_solution` snippet:

```python
def relu(xs):
    return [max(0, x) for x in xs]
```

- `sandbox_error`: FATAL: function clamp_nonneg not defined or not callable
- Hypothesis: Function detection likely failed: expected entry function was not found or could not be imported.

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

- `sandbox_error`: FATAL: function flatten not defined or not callable
- Hypothesis: Function detection likely failed: expected entry function was not found or could not be imported.

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

- `sandbox_error`: FATAL: function distinct_counts not defined or not callable
- Hypothesis: Function detection likely failed: expected entry function was not found or could not be imported.

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

- `sandbox_error`: FATAL: function is_prime not defined or not callable
- Hypothesis: Function detection likely failed: expected entry function was not found or could not be imported.

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

- `sandbox_error`: FATAL: function transpose not defined or not callable
- Hypothesis: Function detection likely failed: expected entry function was not found or could not be imported.

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

- `sandbox_error`: FATAL: function is_balanced not defined or not callable
- Hypothesis: Function detection likely failed: expected entry function was not found or could not be imported.

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

- `sandbox_error`: FATAL: function caesar_cipher not defined or not callable
- Hypothesis: Function detection likely failed: expected entry function was not found or could not be imported.

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

- `sandbox_error`: FATAL: function count_words not defined or not callable
- Hypothesis: Function detection likely failed: expected entry function was not found or could not be imported.

### `edu-109-gcd`

- `verifier_judged_pass`: `False`
- `reference_solution` snippet:

```python
def gcd(a, b):
    while b:
        a, b = b, a % b
    return a
```

- `sandbox_error`: FATAL: function gcd_from_string not defined or not callable
- Hypothesis: Function detection likely failed: expected entry function was not found or could not be imported.

### `p3-a-011-summary-ranges`

- `verifier_judged_pass`: `False`
- `reference_solution` snippet:

```python
def summary_ranges(nums):
    if not nums: return []
    out = []
    start = nums[0]
    prev = nums[0]
```

- `sandbox_error`: FATAL: function find_ranges not defined or not callable
- Hypothesis: Function detection likely failed: expected entry function was not found or could not be imported.

### `hr-003-middle-of-linked-list`

- `verifier_judged_pass`: `False`
- `reference_solution` snippet:

```python
def middle_value(nums):
    return nums[len(nums) // 2]
```

- `sandbox_error`: FATAL: function middle_of_linked_list not defined or not callable
- Hypothesis: Function detection likely failed: expected entry function was not found or could not be imported.

## Category 2 - test failures (0 problems)

_No problems in this category._

## Category 3 - anti-leak over-rejection (0 problems)

_No problems in this category._

## Category 4 - unknown / missing data (0 problems)

_No problems in this category._

## Conclusions

Hypothesis ranking:
1. Category 1 (56 problems): sandbox bridge / function detection / import failure
2. Category 2 (0 problems): dataset reference or test-case mismatch
3. Category 3 (0 problems): LLM judge over-rejection after passing tests
4. Category 4 (0 problems): eval artifact omitted or failed to produce raw verify details

Top data-backed hypothesis: sandbox execution/function detection is the dominant false-reject source.

## P0 fix paths

- For category 1: fix sandbox bridge / function detection
- For category 2: re-validate dataset references
- For category 3: tune LLM judge prompt or relax retry conditions
- For category 4: improve eval pipeline error logging
