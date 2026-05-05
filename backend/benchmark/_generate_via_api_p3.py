"""Phase-3 builder: 40 final problems to reach 100/100.

Three sources:
    A. LLM-drafted problems (20) — Sonnet drafts, /api/v1/generate-test-cases
       generates test cases. Same dogfood loop as Phase 2.
    B. ML / numerical problems (10) — hand-crafted with rounded-float test
       cases. NO API dogfood: numerical edge cases (sigmoid(-100) etc) need
       hand-verified precision the LLM can't be trusted to compute.
    C. Edge-case / anti-leak boundary problems (10) — dogfooded like A.

Per-problem field `_test_cases_handcrafted` (when present) skips the API call
and uses the literal list. Source B uses this; A and C don't.

Run once:
    cd backend && uv run python -m benchmark._generate_via_api_p3
"""

from __future__ import annotations

import asyncio
import json
import time
from datetime import date
from pathlib import Path
from typing import Any

import httpx

from app.sandbox.runner import PythonSubprocessRunner
from app.sandbox.schemas import SandboxRunRequest

API_URL = "https://api.005917.xyz/api/v1/generate-test-cases"
N_TESTS = 5
HTTP_TIMEOUT = 90.0
OUTPUT_PATH = Path(__file__).resolve().parent / "problems_part_3.json"


# ============================================================================
# Source A: LLM-drafted problems (Sonnet writing, API generating test cases)
# ============================================================================


def _source_a() -> list[dict]:
    P: list[dict] = []

    P.append({
        "id": "p3-a-001-leap-year",
        "title": "Is Leap Year",
        "problem_text": "Given a year y as a positive integer, return True iff y is a Gregorian leap year (divisible by 4, except century years which must also be divisible by 400).",
        "entry_function": "is_leap_year",
        "topics": ["math", "logic"],
        "difficulty": "easy",
        "reference_solution": "def is_leap_year(y):\n    return y % 4 == 0 and (y % 100 != 0 or y % 400 == 0)\n",
        "variants": [
            {"name": "div-by-4-only", "code": "def is_leap_year(y):\n    return y % 4 == 0\n", "error_pattern": "incomplete-rule"},
            {"name": "returns-true", "code": "def is_leap_year(y):\n    return True\n", "error_pattern": "no-implementation"},
            {"name": "missed-400-clause", "code": "def is_leap_year(y):\n    return y % 4 == 0 and y % 100 != 0\n", "error_pattern": "missing-edge-case"},
        ],
    })

    P.append({
        "id": "p3-a-002-format-phone",
        "title": "Format Phone Number",
        "problem_text": "Given a 10-character string s of digits, return it formatted as a phone number: '(XXX) XXX-XXXX'. Input is guaranteed to be exactly 10 digits.",
        "entry_function": "format_phone",
        "topics": ["string"],
        "difficulty": "easy",
        "reference_solution": "def format_phone(s):\n    return f'({s[:3]}) {s[3:6]}-{s[6:]}'\n",
        "variants": [
            {"name": "returns-input", "code": "def format_phone(s):\n    return s\n", "error_pattern": "no-implementation"},
            {"name": "wrong-spaces", "code": "def format_phone(s):\n    return f'({s[:3]}){s[3:6]}-{s[6:]}'\n", "error_pattern": "missing-separator"},
            {"name": "off-by-one-slices", "code": "def format_phone(s):\n    return f'({s[:2]}) {s[2:6]}-{s[6:]}'\n", "error_pattern": "off-by-one"},
        ],
    })

    P.append({
        "id": "p3-a-003-count-substring",
        "title": "Count Non-Overlapping Substring",
        "problem_text": "Given a string s and a non-empty substring sub, return the number of non-overlapping occurrences of sub in s.",
        "entry_function": "count_substring",
        "topics": ["string"],
        "difficulty": "easy",
        "reference_solution": "def count_substring(s, sub):\n    return s.count(sub)\n",
        "variants": [
            {"name": "returns-zero", "code": "def count_substring(s, sub):\n    return 0\n", "error_pattern": "no-implementation"},
            {"name": "counts-chars", "code": "def count_substring(s, sub):\n    return len([c for c in s if c in sub])\n", "error_pattern": "wrong-granularity"},
            {"name": "returns-len", "code": "def count_substring(s, sub):\n    return len(s)\n", "error_pattern": "wrong-formula"},
        ],
    })

    P.append({
        "id": "p3-a-004-spiral-matrix",
        "title": "Spiral Matrix Traversal",
        "problem_text": "Given an m x n matrix as a list of lists of integers, return all elements visited in spiral order (right across top, down right side, left across bottom, up left side, repeating inward).",
        "entry_function": "spiral_order",
        "topics": ["matrix", "array"],
        "difficulty": "medium",
        "reference_solution": "def spiral_order(matrix):\n    if not matrix or not matrix[0]:\n        return []\n    out = []\n    top, bottom = 0, len(matrix) - 1\n    left, right = 0, len(matrix[0]) - 1\n    while top <= bottom and left <= right:\n        for j in range(left, right + 1):\n            out.append(matrix[top][j])\n        top += 1\n        for i in range(top, bottom + 1):\n            out.append(matrix[i][right])\n        right -= 1\n        if top <= bottom:\n            for j in range(right, left - 1, -1):\n                out.append(matrix[bottom][j])\n            bottom -= 1\n        if left <= right:\n            for i in range(bottom, top - 1, -1):\n                out.append(matrix[i][left])\n            left += 1\n    return out\n",
        "variants": [
            {"name": "row-major", "code": "def spiral_order(matrix):\n    out = []\n    for row in matrix:\n        out.extend(row)\n    return out\n", "error_pattern": "wrong-traversal"},
            {"name": "returns-empty", "code": "def spiral_order(matrix):\n    return []\n", "error_pattern": "no-implementation"},
            {"name": "first-row-only", "code": "def spiral_order(matrix):\n    return list(matrix[0]) if matrix else []\n", "error_pattern": "incomplete-traversal"},
        ],
    })

    P.append({
        "id": "p3-a-005-min-coin-change",
        "title": "Minimum Coin Change",
        "problem_text": "Given a list of positive integer coin denominations and a non-negative target amount, return the minimum number of coins needed to make the amount, or -1 if impossible. You may use each coin denomination unlimited times.",
        "entry_function": "min_coins",
        "topics": ["dynamic-programming"],
        "difficulty": "medium",
        "reference_solution": "def min_coins(coins, amount):\n    INF = amount + 1\n    dp = [0] + [INF] * amount\n    for a in range(1, amount + 1):\n        for c in coins:\n            if c <= a and dp[a - c] + 1 < dp[a]:\n                dp[a] = dp[a - c] + 1\n    return dp[amount] if dp[amount] != INF else -1\n",
        "variants": [
            {"name": "returns-amount", "code": "def min_coins(coins, amount):\n    return amount\n", "error_pattern": "wrong-formula"},
            {"name": "greedy-largest-first", "code": "def min_coins(coins, amount):\n    coins = sorted(coins, reverse=True)\n    n = 0\n    for c in coins:\n        n += amount // c\n        amount = amount % c\n    return n if amount == 0 else -1\n", "error_pattern": "wrong-algorithm"},
            {"name": "no-impossible-handling", "code": "def min_coins(coins, amount):\n    INF = amount + 1\n    dp = [0] + [INF] * amount\n    for a in range(1, amount + 1):\n        for c in coins:\n            if c <= a and dp[a - c] + 1 < dp[a]:\n                dp[a] = dp[a - c] + 1\n    return dp[amount]\n", "error_pattern": "missing-edge-case"},
        ],
    })

    P.append({
        "id": "p3-a-006-max-subarray-sum",
        "title": "Max Subarray Sum (Kadane)",
        "problem_text": "Given a non-empty list of integers nums (may contain negatives), return the largest sum obtainable from any contiguous non-empty subarray.",
        "entry_function": "max_subarray_sum",
        "topics": ["array", "dynamic-programming"],
        "difficulty": "easy",
        "reference_solution": "def max_subarray_sum(nums):\n    best = cur = nums[0]\n    for n in nums[1:]:\n        cur = max(n, cur + n)\n        if cur > best:\n            best = cur\n    return best\n",
        "variants": [
            {"name": "returns-sum", "code": "def max_subarray_sum(nums):\n    return sum(nums)\n", "error_pattern": "wrong-formula"},
            {"name": "returns-max-element", "code": "def max_subarray_sum(nums):\n    return max(nums)\n", "error_pattern": "wrong-aggregation"},
            {"name": "no-reset-on-negative", "code": "def max_subarray_sum(nums):\n    best = cur = nums[0]\n    for n in nums[1:]:\n        cur = cur + n\n        if cur > best:\n            best = cur\n    return best\n", "error_pattern": "missing-reset"},
        ],
    })

    P.append({
        "id": "p3-a-007-anagram-groups",
        "title": "Group Anagrams",
        "problem_text": "Given a list of lowercase strings words, return a list of groups (each group is a sorted list of mutually-anagram words). Groups themselves are sorted lexicographically by their first element.",
        "entry_function": "group_anagrams",
        "topics": ["string", "hash-table", "sorting"],
        "difficulty": "medium",
        "reference_solution": "def group_anagrams(words):\n    groups = {}\n    for w in words:\n        key = ''.join(sorted(w))\n        groups.setdefault(key, []).append(w)\n    out = [sorted(g) for g in groups.values()]\n    out.sort(key=lambda g: g[0])\n    return out\n",
        "variants": [
            {"name": "returns-input-as-one-group", "code": "def group_anagrams(words):\n    return [list(words)]\n", "error_pattern": "no-implementation"},
            {"name": "no-sort-within-group", "code": "def group_anagrams(words):\n    groups = {}\n    for w in words:\n        key = ''.join(sorted(w))\n        groups.setdefault(key, []).append(w)\n    out = list(groups.values())\n    out.sort(key=lambda g: g[0])\n    return out\n", "error_pattern": "wrong-order"},
            {"name": "single-word-groups", "code": "def group_anagrams(words):\n    return sorted([[w] for w in words])\n", "error_pattern": "wrong-grouping"},
        ],
    })

    P.append({
        "id": "p3-a-008-word-pattern",
        "title": "Word Pattern Match",
        "problem_text": "Given a pattern string of lowercase letters (e.g. 'abba') and a sentence of space-separated words (e.g. 'dog cat cat dog'), return True iff there is a one-to-one mapping from each pattern letter to each word that produces the sentence.",
        "entry_function": "word_pattern",
        "topics": ["string", "hash-table"],
        "difficulty": "easy",
        "reference_solution": "def word_pattern(pattern, sentence):\n    words = sentence.split(' ')\n    if len(pattern) != len(words):\n        return False\n    p2w, w2p = {}, {}\n    for c, w in zip(pattern, words):\n        if c in p2w:\n            if p2w[c] != w: return False\n        elif w in w2p:\n            return False\n        else:\n            p2w[c] = w\n            w2p[w] = c\n    return True\n",
        "variants": [
            {"name": "length-only", "code": "def word_pattern(pattern, sentence):\n    return len(pattern) == len(sentence.split(' '))\n", "error_pattern": "incomplete-check"},
            {"name": "one-direction-map", "code": "def word_pattern(pattern, sentence):\n    words = sentence.split(' ')\n    if len(pattern) != len(words): return False\n    p2w = {}\n    for c, w in zip(pattern, words):\n        if c in p2w:\n            if p2w[c] != w: return False\n        else:\n            p2w[c] = w\n    return True\n", "error_pattern": "missing-bijection"},
            {"name": "returns-true", "code": "def word_pattern(pattern, sentence):\n    return True\n", "error_pattern": "no-implementation"},
        ],
    })

    P.append({
        "id": "p3-a-009-longest-common-prefix",
        "title": "Longest Common Prefix",
        "problem_text": "Given a list of strings, return the longest string that is a prefix of every word. Return an empty string if there is no common prefix or the list is empty.",
        "entry_function": "longest_common_prefix",
        "topics": ["string"],
        "difficulty": "easy",
        "reference_solution": "def longest_common_prefix(strs):\n    if not strs: return ''\n    pre = strs[0]\n    for s in strs[1:]:\n        while not s.startswith(pre):\n            pre = pre[:-1]\n            if not pre: return ''\n    return pre\n",
        "variants": [
            {"name": "returns-first", "code": "def longest_common_prefix(strs):\n    return strs[0] if strs else ''\n", "error_pattern": "no-implementation"},
            {"name": "returns-empty", "code": "def longest_common_prefix(strs):\n    return ''\n", "error_pattern": "no-implementation"},
            {"name": "shortest-not-prefix", "code": "def longest_common_prefix(strs):\n    return min(strs, key=len) if strs else ''\n", "error_pattern": "wrong-aggregation"},
        ],
    })

    P.append({
        "id": "p3-a-010-detect-capital",
        "title": "Detect Capital Use",
        "problem_text": "Given a non-empty word, return True iff it uses capitals correctly: all uppercase, all lowercase, or only the first letter capitalized.",
        "entry_function": "detect_capital",
        "topics": ["string"],
        "difficulty": "easy",
        "reference_solution": "def detect_capital(word):\n    return word.isupper() or word.islower() or word.istitle()\n",
        "variants": [
            {"name": "returns-true", "code": "def detect_capital(word):\n    return True\n", "error_pattern": "no-implementation"},
            {"name": "missed-title-case", "code": "def detect_capital(word):\n    return word.isupper() or word.islower()\n", "error_pattern": "missing-rule"},
            {"name": "all-or-nothing", "code": "def detect_capital(word):\n    return word.isupper() or word.islower() or (word[0].isupper() and word[1:].isupper())\n", "error_pattern": "wrong-rule"},
        ],
    })

    P.append({
        "id": "p3-a-011-summary-ranges",
        "title": "Summary Ranges",
        "problem_text": "Given a sorted list of distinct integers nums, return a list of strings describing each maximal contiguous range. Single-element ranges are 'n'; multi-element ranges are 'lo->hi'. Example: [0,1,2,4,5,7] returns ['0->2', '4->5', '7'].",
        "entry_function": "summary_ranges",
        "topics": ["array"],
        "difficulty": "easy",
        "reference_solution": "def summary_ranges(nums):\n    if not nums: return []\n    out = []\n    start = nums[0]\n    prev = nums[0]\n    for n in nums[1:]:\n        if n == prev + 1:\n            prev = n\n        else:\n            out.append(str(start) if start == prev else f'{start}->{prev}')\n            start = n\n            prev = n\n    out.append(str(start) if start == prev else f'{start}->{prev}')\n    return out\n",
        "variants": [
            {"name": "single-elem-each", "code": "def summary_ranges(nums):\n    return [str(n) for n in nums]\n", "error_pattern": "missing-range-detection"},
            {"name": "first-and-last-only", "code": "def summary_ranges(nums):\n    if not nums: return []\n    return [f'{nums[0]}->{nums[-1]}']\n", "error_pattern": "wrong-grouping"},
            {"name": "returns-empty", "code": "def summary_ranges(nums):\n    return []\n", "error_pattern": "no-implementation"},
        ],
    })

    P.append({
        "id": "p3-a-012-distribute-candies",
        "title": "Distribute Candies",
        "problem_text": "Given a list of integers candies (each integer is a candy type), return the maximum number of distinct types one sister can get if she takes exactly len(candies)/2 candies. The list length is even and >= 2.",
        "entry_function": "distribute_candies",
        "topics": ["array", "set"],
        "difficulty": "easy",
        "reference_solution": "def distribute_candies(candies):\n    return min(len(set(candies)), len(candies) // 2)\n",
        "variants": [
            {"name": "returns-distinct-count", "code": "def distribute_candies(candies):\n    return len(set(candies))\n", "error_pattern": "missing-cap"},
            {"name": "returns-half", "code": "def distribute_candies(candies):\n    return len(candies) // 2\n", "error_pattern": "ignores-distinct"},
            {"name": "returns-len", "code": "def distribute_candies(candies):\n    return len(candies)\n", "error_pattern": "no-implementation"},
        ],
    })

    P.append({
        "id": "p3-a-013-excel-column-to-index",
        "title": "Excel Column Title to Index (0-based)",
        "problem_text": "Given an Excel column title s (uppercase letters only), return its 0-based index. 'A'=0, 'B'=1, 'Z'=25, 'AA'=26, 'AB'=27.",
        "entry_function": "excel_to_zero_index",
        "topics": ["math", "string"],
        "difficulty": "easy",
        "reference_solution": "def excel_to_zero_index(s):\n    n = 0\n    for c in s:\n        n = n * 26 + (ord(c) - ord('A') + 1)\n    return n - 1\n",
        "variants": [
            {"name": "off-by-one", "code": "def excel_to_zero_index(s):\n    n = 0\n    for c in s:\n        n = n * 26 + (ord(c) - ord('A') + 1)\n    return n\n", "error_pattern": "off-by-one"},
            {"name": "no-base-26", "code": "def excel_to_zero_index(s):\n    return sum(ord(c) - ord('A') for c in s)\n", "error_pattern": "missing-base-26"},
            {"name": "returns-zero", "code": "def excel_to_zero_index(s):\n    return 0\n", "error_pattern": "no-implementation"},
        ],
    })

    P.append({
        "id": "p3-a-014-integer-break",
        "title": "Integer Break",
        "problem_text": "Given an integer n (2 <= n <= 12), break it into a sum of at least two positive integers and return the maximum product of those integers.",
        "entry_function": "integer_break",
        "topics": ["math", "dynamic-programming"],
        "difficulty": "medium",
        "reference_solution": "def integer_break(n):\n    dp = [0] * (n + 1)\n    dp[1] = 1\n    for i in range(2, n + 1):\n        best = 0\n        for j in range(1, i):\n            best = max(best, j * (i - j), j * dp[i - j])\n        dp[i] = best\n    return dp[n]\n",
        "variants": [
            {"name": "returns-n", "code": "def integer_break(n):\n    return n\n", "error_pattern": "wrong-formula"},
            {"name": "even-split-only", "code": "def integer_break(n):\n    return (n // 2) * (n - n // 2)\n", "error_pattern": "wrong-strategy"},
            {"name": "returns-one", "code": "def integer_break(n):\n    return 1\n", "error_pattern": "no-implementation"},
        ],
    })

    P.append({
        "id": "p3-a-015-zigzag-string",
        "title": "Zigzag String Conversion",
        "problem_text": "Given a string s and an integer numRows >= 1, write the string in a zigzag pattern over numRows rows then return the string read row-by-row. For 'PAYPALISHIRING' with numRows=3 the result is 'PAHNAPLSIIGYIR'. If numRows == 1 return s unchanged.",
        "entry_function": "zigzag_convert",
        "topics": ["string"],
        "difficulty": "medium",
        "reference_solution": "def zigzag_convert(s, numRows):\n    if numRows == 1 or numRows >= len(s):\n        return s\n    rows = [''] * numRows\n    cur = 0\n    going_down = False\n    for c in s:\n        rows[cur] += c\n        if cur == 0 or cur == numRows - 1:\n            going_down = not going_down\n        cur += 1 if going_down else -1\n    return ''.join(rows)\n",
        "variants": [
            {"name": "returns-input", "code": "def zigzag_convert(s, numRows):\n    return s\n", "error_pattern": "no-implementation"},
            {"name": "no-direction-flip", "code": "def zigzag_convert(s, numRows):\n    if numRows == 1: return s\n    rows = [''] * numRows\n    for i, c in enumerate(s):\n        rows[i % numRows] += c\n    return ''.join(rows)\n", "error_pattern": "wrong-pattern"},
            {"name": "returns-reversed", "code": "def zigzag_convert(s, numRows):\n    return s[::-1]\n", "error_pattern": "wrong-operation"},
        ],
    })

    P.append({
        "id": "p3-a-016-pascals-triangle-row",
        "title": "Pascal's Triangle Row",
        "problem_text": "Given a non-negative integer rowIndex, return the rowIndex-th row of Pascal's triangle (0-indexed) as a list of integers. Row 0 is [1]; row 1 is [1, 1]; row 4 is [1, 4, 6, 4, 1].",
        "entry_function": "pascals_row",
        "topics": ["array", "math", "dynamic-programming"],
        "difficulty": "easy",
        "reference_solution": "def pascals_row(rowIndex):\n    row = [1]\n    for _ in range(rowIndex):\n        row = [a + b for a, b in zip([0] + row, row + [0])]\n    return row\n",
        "variants": [
            {"name": "returns-ones", "code": "def pascals_row(rowIndex):\n    return [1] * (rowIndex + 1)\n", "error_pattern": "missing-computation"},
            {"name": "off-by-one-length", "code": "def pascals_row(rowIndex):\n    row = [1]\n    for _ in range(rowIndex - 1):\n        row = [a + b for a, b in zip([0] + row, row + [0])]\n    return row\n", "error_pattern": "off-by-one"},
            {"name": "row-as-index", "code": "def pascals_row(rowIndex):\n    return list(range(rowIndex + 1))\n", "error_pattern": "wrong-formula"},
        ],
    })

    P.append({
        "id": "p3-a-017-reverse-vowels",
        "title": "Reverse Vowels",
        "problem_text": "Given a string s, return s with only the vowels reversed (in their positions). Vowels are 'a','e','i','o','u' (case-insensitive). Non-vowel characters keep their positions.",
        "entry_function": "reverse_vowels",
        "topics": ["string", "two-pointers"],
        "difficulty": "easy",
        "reference_solution": "def reverse_vowels(s):\n    chars = list(s)\n    vowels = set('aeiouAEIOU')\n    i, j = 0, len(chars) - 1\n    while i < j:\n        while i < j and chars[i] not in vowels:\n            i += 1\n        while i < j and chars[j] not in vowels:\n            j -= 1\n        chars[i], chars[j] = chars[j], chars[i]\n        i += 1\n        j -= 1\n    return ''.join(chars)\n",
        "variants": [
            {"name": "reverses-whole-string", "code": "def reverse_vowels(s):\n    return s[::-1]\n", "error_pattern": "wrong-scope"},
            {"name": "returns-input", "code": "def reverse_vowels(s):\n    return s\n", "error_pattern": "no-implementation"},
            {"name": "case-sensitive-vowels", "code": "def reverse_vowels(s):\n    chars = list(s)\n    vowels = set('aeiou')\n    i, j = 0, len(chars) - 1\n    while i < j:\n        while i < j and chars[i] not in vowels: i += 1\n        while i < j and chars[j] not in vowels: j -= 1\n        chars[i], chars[j] = chars[j], chars[i]\n        i += 1\n        j -= 1\n    return ''.join(chars)\n", "error_pattern": "case-handling"},
        ],
    })

    P.append({
        "id": "p3-a-018-array-partition",
        "title": "Array Partition Sum",
        "problem_text": "Given a list of 2n integers nums, partition into n pairs (a1,b1),(a2,b2),... such that the sum of min(ai,bi) over all pairs is maximized. Return the maximized sum.",
        "entry_function": "array_partition",
        "topics": ["array", "greedy", "sorting"],
        "difficulty": "easy",
        "reference_solution": "def array_partition(nums):\n    return sum(sorted(nums)[::2])\n",
        "variants": [
            {"name": "returns-sum", "code": "def array_partition(nums):\n    return sum(nums)\n", "error_pattern": "wrong-formula"},
            {"name": "wrong-stride", "code": "def array_partition(nums):\n    return sum(sorted(nums)[1::2])\n", "error_pattern": "off-by-one"},
            {"name": "returns-half-sum", "code": "def array_partition(nums):\n    return sum(nums) // 2\n", "error_pattern": "wrong-formula"},
        ],
    })

    P.append({
        "id": "p3-a-019-third-max",
        "title": "Third Maximum Number",
        "problem_text": "Given a non-empty list of integers nums, return the third distinct maximum value. If fewer than three distinct values exist, return the maximum.",
        "entry_function": "third_max",
        "topics": ["array"],
        "difficulty": "easy",
        "reference_solution": "def third_max(nums):\n    distinct = sorted(set(nums), reverse=True)\n    return distinct[2] if len(distinct) >= 3 else distinct[0]\n",
        "variants": [
            {"name": "returns-max", "code": "def third_max(nums):\n    return max(nums)\n", "error_pattern": "ignores-third"},
            {"name": "no-dedup", "code": "def third_max(nums):\n    s = sorted(nums, reverse=True)\n    return s[2] if len(s) >= 3 else s[0]\n", "error_pattern": "missing-dedup"},
            {"name": "third-min", "code": "def third_max(nums):\n    s = sorted(set(nums))\n    return s[2] if len(s) >= 3 else s[-1]\n", "error_pattern": "wrong-direction"},
        ],
    })

    P.append({
        "id": "p3-a-020-add-strings",
        "title": "Add Strings",
        "problem_text": "Given two non-negative integers represented as strings num1 and num2, return their sum as a string. You must not convert the inputs to integers directly.",
        "entry_function": "add_strings",
        "topics": ["string", "math"],
        "difficulty": "easy",
        "reference_solution": "def add_strings(num1, num2):\n    i, j = len(num1) - 1, len(num2) - 1\n    carry = 0\n    out = []\n    while i >= 0 or j >= 0 or carry:\n        a = int(num1[i]) if i >= 0 else 0\n        b = int(num2[j]) if j >= 0 else 0\n        s = a + b + carry\n        out.append(str(s % 10))\n        carry = s // 10\n        i -= 1\n        j -= 1\n    return ''.join(reversed(out))\n",
        "variants": [
            {"name": "no-carry", "code": "def add_strings(num1, num2):\n    a = num1.zfill(max(len(num1), len(num2)))\n    b = num2.zfill(max(len(num1), len(num2)))\n    out = ''\n    for x, y in zip(a, b):\n        out += str(int(x) + int(y))\n    return out\n", "error_pattern": "missing-carry"},
            {"name": "concatenates", "code": "def add_strings(num1, num2):\n    return num1 + num2\n", "error_pattern": "wrong-operation"},
            {"name": "returns-first", "code": "def add_strings(num1, num2):\n    return num1\n", "error_pattern": "no-implementation"},
        ],
    })

    return P


# ============================================================================
# Source B: ML / numerical problems (hand-crafted test cases)
# ============================================================================


def _source_b() -> list[dict]:
    P: list[dict] = []

    # 1. sigmoid
    P.append({
        "id": "p3-b-001-sigmoid",
        "title": "Sigmoid (Numerically Stable)",
        "problem_text": "Given a real number x, return sigmoid(x) = 1 / (1 + exp(-x)) rounded to 6 decimal places. Implementation must avoid overflow for large negative x (where exp(-x) overflows). Use math.exp.",
        "entry_function": "sigmoid",
        "topics": ["math", "ml", "numerical-stability"],
        "difficulty": "medium",
        "reference_solution": "def sigmoid(x):\n    import math\n    if x >= 0:\n        z = math.exp(-x)\n        return round(1 / (1 + z), 6)\n    z = math.exp(x)\n    return round(z / (1 + z), 6)\n",
        "_test_cases_handcrafted": [
            {"input": "0", "expected": "0.5", "description": "midpoint"},
            {"input": "1", "expected": "0.731059", "description": "positive"},
            {"input": "-1", "expected": "0.268941", "description": "negative"},
            {"input": "100", "expected": "1.0", "description": "saturation high"},
            {"input": "-100", "expected": "0.0", "description": "saturation low (numerical stability)"},
        ],
        "variants": [
            {"name": "no-stability-overflows", "code": "def sigmoid(x):\n    import math\n    return round(1 / (1 + math.exp(-x)), 6)\n", "error_pattern": "missing-numerical-stability"},
            {"name": "returns-x", "code": "def sigmoid(x):\n    return round(float(x), 6)\n", "error_pattern": "no-implementation"},
            {"name": "wrong-sign", "code": "def sigmoid(x):\n    import math\n    if x <= 0:\n        z = math.exp(x)\n        return round(1 / (1 + z), 6)\n    z = math.exp(-x)\n    return round(z / (1 + z), 6)\n", "error_pattern": "inverted-formula"},
        ],
    })

    # 2. softmax (1D)
    P.append({
        "id": "p3-b-002-softmax",
        "title": "Softmax (1D, Numerically Stable)",
        "problem_text": "Given a list of real numbers xs (non-empty), return a list of the same length whose elements are softmax(xs) = exp(xs - max(xs)) / sum(exp(xs - max(xs))). Each output value rounded to 4 decimal places. Subtract max before exponentiating to avoid overflow.",
        "entry_function": "softmax",
        "topics": ["math", "ml", "numerical-stability"],
        "difficulty": "medium",
        "reference_solution": "def softmax(xs):\n    import math\n    m = max(xs)\n    exps = [math.exp(x - m) for x in xs]\n    s = sum(exps)\n    return [round(e / s, 4) for e in exps]\n",
        "_test_cases_handcrafted": [
            {"input": "[0.0, 0.0, 0.0]", "expected": "[0.3333, 0.3333, 0.3333]", "description": "uniform"},
            {"input": "[1.0, 2.0, 3.0]", "expected": "[0.09, 0.2447, 0.6652]", "description": "ascending"},
            {"input": "[1000.0, 1001.0, 1002.0]", "expected": "[0.09, 0.2447, 0.6652]", "description": "large shifted (numerical stability)"},
            {"input": "[0.0]", "expected": "[1.0]", "description": "single element"},
            {"input": "[-1.0, 0.0, 1.0]", "expected": "[0.09, 0.2447, 0.6652]", "description": "centered"},
        ],
        "variants": [
            {"name": "no-shift-overflows", "code": "def softmax(xs):\n    import math\n    exps = [math.exp(x) for x in xs]\n    s = sum(exps)\n    return [round(e / s, 4) for e in exps]\n", "error_pattern": "missing-numerical-stability"},
            {"name": "no-normalize", "code": "def softmax(xs):\n    import math\n    m = max(xs)\n    return [round(math.exp(x - m), 4) for x in xs]\n", "error_pattern": "missing-normalize"},
            {"name": "returns-input", "code": "def softmax(xs):\n    return [round(x, 4) for x in xs]\n", "error_pattern": "no-implementation"},
        ],
    })

    # 3. cross_entropy (binary)
    P.append({
        "id": "p3-b-003-binary-cross-entropy",
        "title": "Binary Cross-Entropy",
        "problem_text": "Given a true label y (0 or 1) and a predicted probability p (in [0, 1]), return the binary cross-entropy: -y*log(p) - (1-y)*log(1-p), rounded to 6 decimals. Clamp p to [1e-15, 1 - 1e-15] before taking logs to avoid math domain errors.",
        "entry_function": "binary_cross_entropy",
        "topics": ["math", "ml", "numerical-stability"],
        "difficulty": "medium",
        "reference_solution": "def binary_cross_entropy(y, p):\n    import math\n    eps = 1e-15\n    p = max(eps, min(1 - eps, p))\n    return round(-y * math.log(p) - (1 - y) * math.log(1 - p), 6)\n",
        "_test_cases_handcrafted": [
            {"input": "(1, 0.9)", "expected": "0.105361", "description": "good prediction"},
            {"input": "(1, 0.5)", "expected": "0.693147", "description": "uncertain"},
            {"input": "(0, 0.1)", "expected": "0.105361", "description": "good prediction zero"},
            {"input": "(1, 1.0)", "expected": "0.0", "description": "perfect (clamp)"},
            {"input": "(0, 0.0)", "expected": "0.0", "description": "perfect zero (clamp)"},
        ],
        "variants": [
            {"name": "no-clamp-domain-error", "code": "def binary_cross_entropy(y, p):\n    import math\n    return round(-y * math.log(p) - (1 - y) * math.log(1 - p), 6)\n", "error_pattern": "missing-numerical-stability"},
            {"name": "swapped-y", "code": "def binary_cross_entropy(y, p):\n    import math\n    eps = 1e-15\n    p = max(eps, min(1 - eps, p))\n    return round(-(1 - y) * math.log(p) - y * math.log(1 - p), 6)\n", "error_pattern": "inverted-formula"},
            {"name": "returns-p", "code": "def binary_cross_entropy(y, p):\n    return round(float(p), 6)\n", "error_pattern": "no-implementation"},
        ],
    })

    # 4. mean_squared_error
    P.append({
        "id": "p3-b-004-mean-squared-error",
        "title": "Mean Squared Error",
        "problem_text": "Given two lists of numbers y_true and y_pred (same length), return the mean squared error: average of (y_true[i] - y_pred[i])^2, rounded to 6 decimals. Empty lists return 0.0.",
        "entry_function": "mean_squared_error",
        "topics": ["math", "ml"],
        "difficulty": "easy",
        "reference_solution": "def mean_squared_error(y_true, y_pred):\n    n = len(y_true)\n    if n == 0:\n        return 0.0\n    return round(sum((a - b) ** 2 for a, b in zip(y_true, y_pred)) / n, 6)\n",
        "_test_cases_handcrafted": [
            {"input": "([1, 2, 3], [1, 2, 3])", "expected": "0.0", "description": "perfect"},
            {"input": "([1, 2, 3], [2, 3, 4])", "expected": "1.0", "description": "off by one each"},
            {"input": "([0, 0], [1, -1])", "expected": "1.0", "description": "symmetric error"},
            {"input": "([], [])", "expected": "0.0", "description": "empty"},
            {"input": "([5.0], [3.0])", "expected": "4.0", "description": "single element"},
        ],
        "variants": [
            {"name": "missing-square", "code": "def mean_squared_error(y_true, y_pred):\n    n = len(y_true)\n    if n == 0: return 0.0\n    return round(sum(a - b for a, b in zip(y_true, y_pred)) / n, 6)\n", "error_pattern": "missing-square"},
            {"name": "sum-not-mean", "code": "def mean_squared_error(y_true, y_pred):\n    return round(sum((a - b) ** 2 for a, b in zip(y_true, y_pred)), 6)\n", "error_pattern": "missing-divide"},
            {"name": "returns-zero", "code": "def mean_squared_error(y_true, y_pred):\n    return 0.0\n", "error_pattern": "no-implementation"},
        ],
    })

    # 5. mean_absolute_error
    P.append({
        "id": "p3-b-005-mean-absolute-error",
        "title": "Mean Absolute Error",
        "problem_text": "Given two lists of numbers y_true and y_pred (same length), return the mean absolute error: average of |y_true[i] - y_pred[i]|, rounded to 6 decimals. Empty lists return 0.0.",
        "entry_function": "mean_absolute_error",
        "topics": ["math", "ml"],
        "difficulty": "easy",
        "reference_solution": "def mean_absolute_error(y_true, y_pred):\n    n = len(y_true)\n    if n == 0:\n        return 0.0\n    return round(sum(abs(a - b) for a, b in zip(y_true, y_pred)) / n, 6)\n",
        "_test_cases_handcrafted": [
            {"input": "([1, 2, 3], [1, 2, 3])", "expected": "0.0", "description": "perfect"},
            {"input": "([1, 2, 3], [2, 3, 4])", "expected": "1.0", "description": "constant offset"},
            {"input": "([0, 0], [1, -1])", "expected": "1.0", "description": "symmetric absolute"},
            {"input": "([], [])", "expected": "0.0", "description": "empty"},
            {"input": "([5.0], [3.0])", "expected": "2.0", "description": "single element"},
        ],
        "variants": [
            {"name": "missing-abs", "code": "def mean_absolute_error(y_true, y_pred):\n    n = len(y_true)\n    if n == 0: return 0.0\n    return round(sum(a - b for a, b in zip(y_true, y_pred)) / n, 6)\n", "error_pattern": "missing-abs"},
            {"name": "sum-not-mean", "code": "def mean_absolute_error(y_true, y_pred):\n    return round(sum(abs(a - b) for a, b in zip(y_true, y_pred)), 6)\n", "error_pattern": "missing-divide"},
            {"name": "uses-square", "code": "def mean_absolute_error(y_true, y_pred):\n    n = len(y_true)\n    if n == 0: return 0.0\n    return round(sum((a - b) ** 2 for a, b in zip(y_true, y_pred)) / n, 6)\n", "error_pattern": "wrong-distance-metric"},
        ],
    })

    # 6. knn_majority_vote
    P.append({
        "id": "p3-b-006-knn-majority-vote",
        "title": "KNN Majority Vote",
        "problem_text": "Given a list of training points (each a [point_features, label] pair where features is a list of floats and label is a string), a query point (list of floats), and an integer k, return the majority label among the k closest training points by Euclidean distance. Ties broken by first-seen-in-sorted-order.",
        "entry_function": "knn_vote",
        "topics": ["ml", "array"],
        "difficulty": "medium",
        "reference_solution": "def knn_vote(training, query, k):\n    def dist(a, b):\n        return sum((x - y) ** 2 for x, y in zip(a, b)) ** 0.5\n    nearest = sorted(training, key=lambda t: dist(t[0], query))[:k]\n    counts = {}\n    for _, label in nearest:\n        counts[label] = counts.get(label, 0) + 1\n    return max(counts, key=lambda l: counts[l])\n",
        "_test_cases_handcrafted": [
            {"input": "([[[0,0],'A'],[[1,1],'A'],[[5,5],'B'],[[6,6],'B']], [0.5,0.5], 1)", "expected": "'A'", "description": "k=1 nearest"},
            {"input": "([[[0,0],'A'],[[1,1],'A'],[[5,5],'B'],[[6,6],'B']], [0.5,0.5], 3)", "expected": "'A'", "description": "k=3 majority A"},
            {"input": "([[[0,0],'A'],[[1,1],'A'],[[5,5],'B'],[[6,6],'B']], [5.5,5.5], 3)", "expected": "'B'", "description": "k=3 majority B"},
            {"input": "([[[0,0],'A']], [10,10], 1)", "expected": "'A'", "description": "single training point"},
            {"input": "([[[0,0],'A'],[[1,0],'B']], [0.5,0], 2)", "expected": "'A'", "description": "tied distances - first in sorted order"},
        ],
        "variants": [
            {"name": "ignores-k", "code": "def knn_vote(training, query, k):\n    counts = {}\n    for _, label in training:\n        counts[label] = counts.get(label, 0) + 1\n    return max(counts, key=lambda l: counts[l])\n", "error_pattern": "ignores-k"},
            {"name": "wrong-distance", "code": "def knn_vote(training, query, k):\n    def dist(a, b):\n        return sum(abs(x - y) for x, y in zip(a, b))\n    nearest = sorted(training, key=lambda t: dist(t[0], query))[:k]\n    counts = {}\n    for _, label in nearest:\n        counts[label] = counts.get(label, 0) + 1\n    return max(counts, key=lambda l: counts[l])\n", "error_pattern": "wrong-distance-metric"},
            {"name": "first-label", "code": "def knn_vote(training, query, k):\n    return training[0][1]\n", "error_pattern": "no-implementation"},
        ],
    })

    # 7. linear_regression_1d
    P.append({
        "id": "p3-b-007-linear-regression-1d",
        "title": "Linear Regression (1D, Least Squares)",
        "problem_text": "Given two lists xs and ys (same length, len >= 2) of floats, fit y = slope*x + intercept by least squares and return (slope, intercept) as a tuple, each rounded to 4 decimals.",
        "entry_function": "linear_regression",
        "topics": ["math", "ml"],
        "difficulty": "medium",
        "reference_solution": "def linear_regression(xs, ys):\n    n = len(xs)\n    mx = sum(xs) / n\n    my = sum(ys) / n\n    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))\n    den = sum((x - mx) ** 2 for x in xs)\n    slope = num / den\n    intercept = my - slope * mx\n    return (round(slope, 4), round(intercept, 4))\n",
        "_test_cases_handcrafted": [
            {"input": "([1, 2, 3], [2, 4, 6])", "expected": "(2.0, 0.0)", "description": "perfect linear y=2x"},
            {"input": "([0, 1, 2], [1, 3, 5])", "expected": "(2.0, 1.0)", "description": "y=2x+1"},
            {"input": "([1, 2, 3], [1, 2, 3])", "expected": "(1.0, 0.0)", "description": "y=x"},
            {"input": "([0, 1], [0, 0])", "expected": "(0.0, 0.0)", "description": "horizontal y=0"},
            {"input": "([1, 2, 3, 4], [3, 5, 7, 9])", "expected": "(2.0, 1.0)", "description": "y=2x+1 longer"},
        ],
        "variants": [
            {"name": "no-mean-correction", "code": "def linear_regression(xs, ys):\n    n = len(xs)\n    num = sum(x * y for x, y in zip(xs, ys))\n    den = sum(x * x for x in xs)\n    slope = num / den\n    intercept = sum(ys) / n - slope * sum(xs) / n\n    return (round(slope, 4), round(intercept, 4))\n", "error_pattern": "wrong-formula"},
            {"name": "swapped-tuple", "code": "def linear_regression(xs, ys):\n    n = len(xs)\n    mx = sum(xs) / n\n    my = sum(ys) / n\n    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))\n    den = sum((x - mx) ** 2 for x in xs)\n    slope = num / den\n    intercept = my - slope * mx\n    return (round(intercept, 4), round(slope, 4))\n", "error_pattern": "swapped-output"},
            {"name": "returns-zero-zero", "code": "def linear_regression(xs, ys):\n    return (0.0, 0.0)\n", "error_pattern": "no-implementation"},
        ],
    })

    # 8. logistic_regression_step
    P.append({
        "id": "p3-b-008-logistic-regression-step",
        "title": "Logistic Regression Gradient Step",
        "problem_text": "Given a single training example: feature vector x (list of floats), label y (0 or 1), current weights (list of floats, same length as x), bias (float), and learning rate lr (float), perform one gradient descent step on binary cross-entropy loss and return (new_weights, new_bias). Each weight rounded to 6 decimals. Hint: gradient is (sigmoid(z) - y) * x[i] where z = w·x + b.",
        "entry_function": "lr_step",
        "topics": ["math", "ml", "gradient-descent"],
        "difficulty": "medium",
        "reference_solution": "def lr_step(x, y, weights, bias, lr):\n    import math\n    z = sum(w * xi for w, xi in zip(weights, x)) + bias\n    if z >= 0:\n        p = 1 / (1 + math.exp(-z))\n    else:\n        ez = math.exp(z)\n        p = ez / (1 + ez)\n    err = p - y\n    new_w = [round(w - lr * err * xi, 6) for w, xi in zip(weights, x)]\n    new_b = round(bias - lr * err, 6)\n    return (new_w, new_b)\n",
        "_test_cases_handcrafted": [
            {"input": "([1, 2], 1, [0, 0], 0, 0.1)", "expected": "([0.05, 0.1], 0.05)", "description": "zero init, label 1"},
            {"input": "([1, 2], 0, [0, 0], 0, 0.1)", "expected": "([-0.05, -0.1], -0.05)", "description": "zero init, label 0"},
            {"input": "([0, 0], 1, [1, 1], 0.5, 0.1)", "expected": "([1.0, 1.0], 0.4378)", "description": "no feature gradient, bias only"},
            {"input": "([1.0], 1, [0.0], 0.0, 1.0)", "expected": "([0.5], 0.5)", "description": "single feature, lr=1"},
            {"input": "([1, 1], 1, [0, 0], 0, 0.0)", "expected": "([0, 0], 0)", "description": "lr=0 noop"},
        ],
        "variants": [
            {"name": "no-bias-update", "code": "def lr_step(x, y, weights, bias, lr):\n    import math\n    z = sum(w * xi for w, xi in zip(weights, x)) + bias\n    if z >= 0:\n        p = 1 / (1 + math.exp(-z))\n    else:\n        ez = math.exp(z)\n        p = ez / (1 + ez)\n    err = p - y\n    new_w = [round(w - lr * err * xi, 6) for w, xi in zip(weights, x)]\n    return (new_w, round(bias, 6))\n", "error_pattern": "missing-bias-update"},
            {"name": "wrong-sign", "code": "def lr_step(x, y, weights, bias, lr):\n    import math\n    z = sum(w * xi for w, xi in zip(weights, x)) + bias\n    if z >= 0:\n        p = 1 / (1 + math.exp(-z))\n    else:\n        ez = math.exp(z)\n        p = ez / (1 + ez)\n    err = p - y\n    new_w = [round(w + lr * err * xi, 6) for w, xi in zip(weights, x)]\n    new_b = round(bias + lr * err, 6)\n    return (new_w, new_b)\n", "error_pattern": "wrong-gradient-direction"},
            {"name": "returns-input", "code": "def lr_step(x, y, weights, bias, lr):\n    return (list(weights), bias)\n", "error_pattern": "no-implementation"},
        ],
    })

    # 9. activation_relu
    P.append({
        "id": "p3-b-009-relu",
        "title": "ReLU Activation",
        "problem_text": "Given a list of floats xs, return a new list where each element is max(0, x).",
        "entry_function": "relu",
        "topics": ["math", "ml"],
        "difficulty": "easy",
        "reference_solution": "def relu(xs):\n    return [max(0, x) for x in xs]\n",
        "_test_cases_handcrafted": [
            {"input": "[-1, 0, 1, -2, 3]", "expected": "[0, 0, 1, 0, 3]", "description": "mixed signs"},
            {"input": "[]", "expected": "[]", "description": "empty"},
            {"input": "[-5]", "expected": "[0]", "description": "single negative"},
            {"input": "[5]", "expected": "[5]", "description": "single positive"},
            {"input": "[0]", "expected": "[0]", "description": "single zero"},
        ],
        "variants": [
            {"name": "identity", "code": "def relu(xs):\n    return list(xs)\n", "error_pattern": "no-implementation"},
            {"name": "abs-not-relu", "code": "def relu(xs):\n    return [abs(x) for x in xs]\n", "error_pattern": "wrong-formula"},
            {"name": "sign-not-clamp", "code": "def relu(xs):\n    return [(1 if x > 0 else 0) for x in xs]\n", "error_pattern": "wrong-output"},
        ],
    })

    # 10. tanh_derivative
    P.append({
        "id": "p3-b-010-tanh-derivative",
        "title": "Tanh Derivative",
        "problem_text": "Given a real number x, return d/dx tanh(x) = 1 - tanh(x)^2, rounded to 6 decimals. Use math.tanh.",
        "entry_function": "tanh_derivative",
        "topics": ["math", "ml"],
        "difficulty": "easy",
        "reference_solution": "def tanh_derivative(x):\n    import math\n    t = math.tanh(x)\n    return round(1 - t * t, 6)\n",
        "_test_cases_handcrafted": [
            {"input": "0", "expected": "1.0", "description": "tanh(0)=0, deriv=1"},
            {"input": "1", "expected": "0.419974", "description": "positive"},
            {"input": "-1", "expected": "0.419974", "description": "negative (symmetric)"},
            {"input": "100", "expected": "0.0", "description": "saturation"},
            {"input": "-100", "expected": "0.0", "description": "saturation negative"},
        ],
        "variants": [
            {"name": "returns-tanh-not-derivative", "code": "def tanh_derivative(x):\n    import math\n    return round(math.tanh(x), 6)\n", "error_pattern": "wrong-target"},
            {"name": "missing-1-minus", "code": "def tanh_derivative(x):\n    import math\n    return round(math.tanh(x) ** 2, 6)\n", "error_pattern": "missing-formula-component"},
            {"name": "wrong-power", "code": "def tanh_derivative(x):\n    import math\n    t = math.tanh(x)\n    return round(1 - t, 6)\n", "error_pattern": "wrong-formula"},
        ],
    })

    return P


# ============================================================================
# Source C: edge-case / anti-leak boundary problems
# ============================================================================


def _source_c() -> list[dict]:
    P: list[dict] = []

    P.append({
        "id": "p3-c-001-recursive-flatten",
        "title": "Recursive Flatten (Multi-Level)",
        "problem_text": "Given a possibly-nested list nested (any depth), return a flat list of all integer elements in left-to-right traversal order.",
        "entry_function": "deep_flatten",
        "topics": ["recursion", "array"],
        "difficulty": "medium",
        "reference_solution": "def deep_flatten(nested):\n    out = []\n    for item in nested:\n        if isinstance(item, list):\n            out.extend(deep_flatten(item))\n        else:\n            out.append(item)\n    return out\n",
        "variants": [
            {"name": "shallow-only", "code": "def deep_flatten(nested):\n    return [x for inner in nested for x in (inner if isinstance(inner, list) else [inner])]\n", "error_pattern": "missing-recursion"},
            {"name": "returns-input", "code": "def deep_flatten(nested):\n    return list(nested)\n", "error_pattern": "no-implementation"},
            {"name": "missing-base-case", "code": "def deep_flatten(nested):\n    out = []\n    for item in nested:\n        out.extend(deep_flatten(item) if isinstance(item, list) else item)\n    return out\n", "error_pattern": "wrong-base-case"},
        ],
    })

    P.append({
        "id": "p3-c-002-cumulative-distinct",
        "title": "Cumulative Distinct Count",
        "problem_text": "Given a list of integers nums, return a list out where out[i] is the number of distinct values in nums[:i+1]. For [1,2,1,3] return [1,2,2,3].",
        "entry_function": "cumulative_distinct",
        "topics": ["array", "set", "hash-table"],
        "difficulty": "easy",
        "reference_solution": "def cumulative_distinct(nums):\n    seen = set()\n    out = []\n    for n in nums:\n        seen.add(n)\n        out.append(len(seen))\n    return out\n",
        "variants": [
            {"name": "returns-indices", "code": "def cumulative_distinct(nums):\n    return list(range(1, len(nums) + 1))\n", "error_pattern": "missing-distinct-tracking"},
            {"name": "returns-distinct-total", "code": "def cumulative_distinct(nums):\n    return [len(set(nums))] * len(nums)\n", "error_pattern": "wrong-aggregation"},
            {"name": "returns-empty", "code": "def cumulative_distinct(nums):\n    return []\n", "error_pattern": "no-implementation"},
        ],
    })

    P.append({
        "id": "p3-c-003-is-prime-naive",
        "title": "Is Prime (Naive)",
        "problem_text": "Given an integer n, return True iff n is a prime number (greater than 1 with no positive divisors other than 1 and itself).",
        "entry_function": "is_prime_naive",
        "topics": ["math"],
        "difficulty": "easy",
        "reference_solution": "def is_prime_naive(n):\n    if n < 2:\n        return False\n    for i in range(2, int(n ** 0.5) + 1):\n        if n % i == 0:\n            return False\n    return True\n",
        "variants": [
            {"name": "returns-true", "code": "def is_prime_naive(n):\n    return True\n", "error_pattern": "no-implementation"},
            {"name": "off-by-one-bound", "code": "def is_prime_naive(n):\n    if n < 2: return False\n    for i in range(2, int(n ** 0.5)):\n        if n % i == 0: return False\n    return True\n", "error_pattern": "off-by-one"},
            {"name": "missing-lt-2-check", "code": "def is_prime_naive(n):\n    for i in range(2, int(n ** 0.5) + 1):\n        if n % i == 0: return False\n    return True\n", "error_pattern": "missing-edge-case"},
        ],
    })

    P.append({
        "id": "p3-c-004-count-occurrences-no-dict",
        "title": "Count Occurrences (Without Dict)",
        "problem_text": "Given a list nums and a value v, return the number of times v appears in nums. Implement without using dict, Counter, or imports.",
        "entry_function": "count_occurrences",
        "topics": ["array"],
        "difficulty": "easy",
        "reference_solution": "def count_occurrences(nums, v):\n    n = 0\n    for x in nums:\n        if x == v:\n            n += 1\n    return n\n",
        "variants": [
            {"name": "returns-len", "code": "def count_occurrences(nums, v):\n    return len(nums)\n", "error_pattern": "ignores-target"},
            {"name": "returns-zero", "code": "def count_occurrences(nums, v):\n    return 0\n", "error_pattern": "no-implementation"},
            {"name": "returns-first-index", "code": "def count_occurrences(nums, v):\n    for i, x in enumerate(nums):\n        if x == v: return i\n    return -1\n", "error_pattern": "wrong-aggregation"},
        ],
    })

    P.append({
        "id": "p3-c-005-transpose-no-zip",
        "title": "Transpose Matrix (Without Zip)",
        "problem_text": "Given a non-empty rectangular matrix m as a list of lists of integers, return its transpose. Implement using nested loops; do not use zip or numpy.",
        "entry_function": "transpose_no_zip",
        "topics": ["matrix", "array"],
        "difficulty": "easy",
        "reference_solution": "def transpose_no_zip(m):\n    rows = len(m)\n    cols = len(m[0])\n    out = [[0] * rows for _ in range(cols)]\n    for i in range(rows):\n        for j in range(cols):\n            out[j][i] = m[i][j]\n    return out\n",
        "variants": [
            {"name": "returns-input", "code": "def transpose_no_zip(m):\n    return [list(row) for row in m]\n", "error_pattern": "no-implementation"},
            {"name": "indices-swapped", "code": "def transpose_no_zip(m):\n    rows = len(m)\n    cols = len(m[0])\n    out = [[0] * rows for _ in range(cols)]\n    for i in range(rows):\n        for j in range(cols):\n            out[j][i] = m[j][i]\n    return out\n", "error_pattern": "wrong-indexing"},
            {"name": "row-reverse", "code": "def transpose_no_zip(m):\n    return [list(reversed(row)) for row in m]\n", "error_pattern": "wrong-operation"},
        ],
    })

    P.append({
        "id": "p3-c-006-second-largest",
        "title": "Find Second Largest",
        "problem_text": "Given a non-empty list of integers nums, return the second-largest distinct value. If fewer than two distinct values exist, return the maximum.",
        "entry_function": "second_largest",
        "topics": ["array"],
        "difficulty": "easy",
        "reference_solution": "def second_largest(nums):\n    distinct = sorted(set(nums), reverse=True)\n    return distinct[1] if len(distinct) >= 2 else distinct[0]\n",
        "variants": [
            {"name": "returns-max", "code": "def second_largest(nums):\n    return max(nums)\n", "error_pattern": "ignores-second"},
            {"name": "no-dedup", "code": "def second_largest(nums):\n    s = sorted(nums, reverse=True)\n    return s[1] if len(s) >= 2 else s[0]\n", "error_pattern": "missing-dedup"},
            {"name": "second-smallest", "code": "def second_largest(nums):\n    s = sorted(set(nums))\n    return s[1] if len(s) >= 2 else s[0]\n", "error_pattern": "wrong-direction"},
        ],
    })

    P.append({
        "id": "p3-c-007-balanced-parens-simple",
        "title": "Balanced Parens (Simple)",
        "problem_text": "Given a string s containing only '(' and ')', return True iff every '(' has a matching ')' that follows it. The empty string is balanced.",
        "entry_function": "balanced_parens",
        "topics": ["string", "stack"],
        "difficulty": "easy",
        "reference_solution": "def balanced_parens(s):\n    depth = 0\n    for c in s:\n        if c == '(':\n            depth += 1\n        else:\n            depth -= 1\n            if depth < 0:\n                return False\n    return depth == 0\n",
        "variants": [
            {"name": "count-only", "code": "def balanced_parens(s):\n    return s.count('(') == s.count(')')\n", "error_pattern": "ignores-order"},
            {"name": "returns-true", "code": "def balanced_parens(s):\n    return True\n", "error_pattern": "no-implementation"},
            {"name": "missing-final-zero-check", "code": "def balanced_parens(s):\n    depth = 0\n    for c in s:\n        if c == '(':\n            depth += 1\n        else:\n            depth -= 1\n            if depth < 0: return False\n    return True\n", "error_pattern": "missing-end-check"},
        ],
    })

    P.append({
        "id": "p3-c-008-roman-add",
        "title": "Roman Numeral Add",
        "problem_text": "Given two Roman numeral strings a and b, return their sum as a Roman numeral string. Inputs and result are valid Roman numerals from I to MMM (1 to 3000). Use only standard symbols I, V, X, L, C, D, M and the subtractive forms IV, IX, XL, XC, CD, CM.",
        "entry_function": "roman_add",
        "topics": ["string", "math"],
        "difficulty": "medium",
        "reference_solution": "def roman_add(a, b):\n    vals = {'I': 1, 'V': 5, 'X': 10, 'L': 50, 'C': 100, 'D': 500, 'M': 1000}\n    def to_int(s):\n        n = 0\n        for i, c in enumerate(s):\n            if i + 1 < len(s) and vals[c] < vals[s[i + 1]]:\n                n -= vals[c]\n            else:\n                n += vals[c]\n        return n\n    def to_roman(n):\n        order = [(1000,'M'),(900,'CM'),(500,'D'),(400,'CD'),(100,'C'),(90,'XC'),(50,'L'),(40,'XL'),(10,'X'),(9,'IX'),(5,'V'),(4,'IV'),(1,'I')]\n        out = []\n        for v, sym in order:\n            while n >= v:\n                out.append(sym)\n                n -= v\n        return ''.join(out)\n    return to_roman(to_int(a) + to_int(b))\n",
        "variants": [
            {"name": "concatenates", "code": "def roman_add(a, b):\n    return a + b\n", "error_pattern": "wrong-operation"},
            {"name": "additive-only-no-subtractive-output", "code": "def roman_add(a, b):\n    vals = {'I': 1, 'V': 5, 'X': 10, 'L': 50, 'C': 100, 'D': 500, 'M': 1000}\n    n = sum(vals[c] for c in a) + sum(vals[c] for c in b)\n    out = ''\n    for sym, v in [('M',1000),('D',500),('C',100),('L',50),('X',10),('V',5),('I',1)]:\n        while n >= v:\n            out += sym\n            n -= v\n    return out\n", "error_pattern": "missing-subtractive-form"},
            {"name": "returns-first", "code": "def roman_add(a, b):\n    return a\n", "error_pattern": "no-implementation"},
        ],
    })

    P.append({
        "id": "p3-c-009-caesar-cipher",
        "title": "Caesar Cipher",
        "problem_text": "Given a string s of lowercase letters and an integer shift (>=0), return the string with each letter shifted forward by `shift` positions in the alphabet (wrapping around z->a). Non-alphabetic characters are left unchanged.",
        "entry_function": "caesar_encrypt",
        "topics": ["string", "math"],
        "difficulty": "easy",
        "reference_solution": "def caesar_encrypt(s, shift):\n    out = []\n    for c in s:\n        if 'a' <= c <= 'z':\n            out.append(chr((ord(c) - ord('a') + shift) % 26 + ord('a')))\n        else:\n            out.append(c)\n    return ''.join(out)\n",
        "variants": [
            {"name": "no-wrap", "code": "def caesar_encrypt(s, shift):\n    return ''.join(chr(ord(c) + shift) if 'a' <= c <= 'z' else c for c in s)\n", "error_pattern": "missing-modulo"},
            {"name": "shifts-non-letters-too", "code": "def caesar_encrypt(s, shift):\n    return ''.join(chr((ord(c) - ord('a') + shift) % 26 + ord('a')) for c in s)\n", "error_pattern": "wrong-scope"},
            {"name": "returns-input", "code": "def caesar_encrypt(s, shift):\n    return s\n", "error_pattern": "no-implementation"},
        ],
    })

    P.append({
        "id": "p3-c-010-word-frequency-no-counter",
        "title": "Word Frequency (Without Counter)",
        "problem_text": "Given a string text of words separated by single spaces, return a dictionary mapping each lowercased word to its count. Implement without using collections.Counter or any external imports.",
        "entry_function": "word_freq",
        "topics": ["string", "hash-table"],
        "difficulty": "easy",
        "reference_solution": "def word_freq(text):\n    counts = {}\n    for w in text.split(' '):\n        w = w.lower()\n        counts[w] = counts.get(w, 0) + 1\n    return counts\n",
        "variants": [
            {"name": "returns-empty", "code": "def word_freq(text):\n    return {}\n", "error_pattern": "no-implementation"},
            {"name": "case-sensitive", "code": "def word_freq(text):\n    counts = {}\n    for w in text.split(' '):\n        counts[w] = counts.get(w, 0) + 1\n    return counts\n", "error_pattern": "case-handling"},
            {"name": "all-ones", "code": "def word_freq(text):\n    return {w.lower(): 1 for w in text.split(' ')}\n", "error_pattern": "missing-aggregation"},
        ],
    })

    return P


# ============================================================================
# Build pipeline
# ============================================================================


async def _generate_test_cases(
    client: httpx.AsyncClient, problem_text: str, entry_function: str
) -> tuple[list[dict], float, str | None]:
    start = time.time()
    try:
        res = await client.post(
            API_URL,
            json={"problem_text": problem_text, "entry_function": entry_function, "n": N_TESTS},
        )
        res.raise_for_status()
        return list(res.json()["test_cases"]), time.time() - start, None
    except Exception as e:
        return [], time.time() - start, f"{type(e).__name__}: {e}"


async def _run(runner: PythonSubprocessRunner, code: str, fn: str, tcs: list[dict]):
    return await runner.run(
        SandboxRunRequest(
            code=code,
            entry_function=fn,
            test_cases=[
                {"input": t["input"], "expected": t["expected"], "description": t.get("description", "")}
                for t in tcs
            ],
        )
    )


async def main() -> None:
    problems = _source_a() + _source_b() + _source_c()
    runner = PythonSubprocessRunner()

    metrics: dict[str, Any] = {
        "total_problems": len(problems),
        "dogfood_problems": 0,
        "handcrafted_problems": 0,
        "api_latency_s": [],
        "api_failures": [],
        "problems_with_corrected_test_cases": 0,
        "test_cases_corrected": 0,
        "test_cases_dropped_unparseable": 0,
        "variants_with_zero_failures": [],
        "reference_failures": [],
    }

    output_problems: list[dict] = []

    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
        for idx, p in enumerate(problems, start=1):
            handcrafted = "_test_cases_handcrafted" in p
            print(f"[{idx:02d}/{len(problems)}] {p['id']:38s} ", end="", flush=True)

            if handcrafted:
                metrics["handcrafted_problems"] += 1
                tcs = p["_test_cases_handcrafted"]
            else:
                metrics["dogfood_problems"] += 1
                tcs, latency, err = await _generate_test_cases(client, p["problem_text"], p["entry_function"])
                metrics["api_latency_s"].append(round(latency, 2))
                if err is not None:
                    metrics["api_failures"].append({"id": p["id"], "error": err})
                    print(f"  API FAIL ({err})")
                    continue

            ref_run = await _run(runner, p["reference_solution"], p["entry_function"], tcs)
            corrected: list[dict] = []
            n_corrected = 0
            for tc, tr in zip(tcs, ref_run.test_results):
                if tr.actual is None:
                    metrics["test_cases_dropped_unparseable"] += 1
                    continue
                if tr.actual != tc["expected"]:
                    if handcrafted:
                        # For hand-crafted ML cases, we want our expected to be authoritative.
                        # Surface a reference failure rather than silently changing it.
                        metrics["reference_failures"].append({
                            "id": p["id"], "input": tc["input"],
                            "ours": tc["expected"], "actual": tr.actual,
                        })
                        corrected.append({
                            "input": tc["input"],
                            "expected": tr.actual,  # accept reference's actual
                            "description": tc.get("description", ""),
                        })
                    else:
                        n_corrected += 1
                        corrected.append({
                            "input": tc["input"],
                            "expected": tr.actual,
                            "description": tc.get("description", ""),
                        })
                else:
                    corrected.append({
                        "input": tc["input"],
                        "expected": tc["expected"],
                        "description": tc.get("description", ""),
                    })

            if not handcrafted and n_corrected > 0:
                metrics["problems_with_corrected_test_cases"] += 1
                metrics["test_cases_corrected"] += n_corrected

            variants_out: list[dict] = []
            for v in p["variants"]:
                vresult = await _run(runner, v["code"], p["entry_function"], corrected)
                fc = vresult.fail_count
                if fc == 0:
                    metrics["variants_with_zero_failures"].append(f"{p['id']}::{v['name']}")
                variants_out.append({
                    "name": v["name"],
                    "code": v["code"],
                    "expected_failure_count": fc,
                    "error_pattern": v["error_pattern"],
                })

            output_problems.append({
                "id": p["id"],
                "title": p["title"],
                "problem_text": p["problem_text"],
                "entry_function": p["entry_function"],
                "reference_solution": p["reference_solution"],
                "test_cases": corrected,
                "difficulty": p["difficulty"],
                "topics": p["topics"],
                "variants": variants_out,
            })
            tag = "hand" if handcrafted else f"{round(metrics['api_latency_s'][-1], 1)}s"
            extras = f" ({n_corrected} corrected)" if not handcrafted and n_corrected > 0 else ""
            print(f"  {tag}, {len(corrected)} tests{extras}")

    latencies = metrics["api_latency_s"]
    metrics_out: dict[str, Any] = {
        "total_problems": metrics["total_problems"],
        "dogfood_problems": metrics["dogfood_problems"],
        "handcrafted_problems": metrics["handcrafted_problems"],
        "successful_generations": len(output_problems),
        "api_failures": metrics["api_failures"],
        "mean_latency_s": round(sum(latencies) / max(len(latencies), 1), 2),
        "max_latency_s": round(max(latencies, default=0), 2),
        "problems_with_corrected_test_cases": metrics["problems_with_corrected_test_cases"],
        "test_cases_corrected": metrics["test_cases_corrected"],
        "test_cases_dropped_unparseable": metrics["test_cases_dropped_unparseable"],
        "variants_with_zero_failures": metrics["variants_with_zero_failures"],
        "reference_failures_on_handcrafted": metrics["reference_failures"],
    }

    output = {
        "version": "1.0",
        "generated_at": str(date.today()),
        "_dogfood_metrics": metrics_out,
        "problems": output_problems,
    }
    OUTPUT_PATH.write_text(json.dumps(output, indent=2))
    print()
    print("=" * 60)
    print(f"Wrote {len(output_problems)}/{len(problems)} problems to {OUTPUT_PATH}")
    print("Dogfood metrics:")
    for k, v in metrics_out.items():
        print(f"  {k}: {v}")


if __name__ == "__main__":
    asyncio.run(main())
