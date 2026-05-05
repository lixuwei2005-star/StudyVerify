"""Phase-2 builder: dogfood /api/v1/generate-test-cases against the prod
backend, then auto-correct any LLM `expected` that disagrees with the
reference solution's sandboxed output.

Run once:
    cd backend && uv run python -m benchmark._generate_via_api

Output: benchmark/problems_part_2.json plus a top-level _dogfood_metrics
field summarizing how often the LLM's expected values needed correction.
"""

from __future__ import annotations

import asyncio
import json
import time
from datetime import date
from pathlib import Path

import httpx

from app.sandbox.runner import PythonSubprocessRunner
from app.sandbox.schemas import SandboxRunRequest

API_URL = "https://api.005917.xyz/api/v1/generate-test-cases"
N_TESTS = 5
HTTP_TIMEOUT = 60.0
OUTPUT_PATH = Path(__file__).resolve().parent / "problems_part_2.json"

# ---------- Tree helper, embedded in tree-problem reference solutions ----------
TREE = """
class _N:
    def __init__(self, v):
        self.v, self.l, self.r = v, None, None

def _build(lst):
    if not lst or lst[0] is None:
        return None
    nodes = [None if v is None else _N(v) for v in lst]
    queue = [nodes[0]]
    i = 1
    while queue and i < len(nodes):
        node = queue.pop(0)
        if i < len(nodes):
            node.l = nodes[i]
            if nodes[i] is not None: queue.append(nodes[i])
            i += 1
        if i < len(nodes):
            node.r = nodes[i]
            if nodes[i] is not None: queue.append(nodes[i])
            i += 1
    return nodes[0]

def _to_list(root):
    if not root: return []
    out = []
    queue = [root]
    while queue:
        n = queue.pop(0)
        if n is None:
            out.append(None)
        else:
            out.append(n.v)
            queue.append(n.l)
            queue.append(n.r)
    while out and out[-1] is None:
        out.pop()
    return out
"""

# ---------- Linked-list helper for some variants ----------
# We represent linked lists as Python lists in inputs/outputs; references
# work directly on lists, so no helper needed for most cases.


# ---------- Problem definitions ----------

def make_problems() -> list[dict]:
    P: list[dict] = []

    # ---------------- A. Data-structure problems (15) ----------------

    # 1. reverse_linked_list_iterative
    P.append({
        "id": "hr-001-reverse-linked-list",
        "title": "Reverse Linked List",
        "problem_text": "Given a list of integers nums representing a singly linked list (head first), return a list representing the same nodes in reverse order.",
        "entry_function": "reverse_linked_list",
        "difficulty": "easy",
        "topics": ["linked-list", "array"],
        "reference_solution": "def reverse_linked_list(nums):\n    return list(nums)[::-1]\n",
        "variants": [
            {"name": "returns-input", "code": "def reverse_linked_list(nums):\n    return list(nums)\n", "error_pattern": "no-implementation"},
            {"name": "drops-head", "code": "def reverse_linked_list(nums):\n    return list(nums)[1:][::-1]\n", "error_pattern": "off-by-one"},
            {"name": "sorts-instead", "code": "def reverse_linked_list(nums):\n    return sorted(nums, reverse=True)\n", "error_pattern": "wrong-operation"},
        ],
    })

    # 2. palindrome_linked_list
    P.append({
        "id": "hr-002-palindrome-linked-list",
        "title": "Palindrome Linked List",
        "problem_text": "Given a list of integers nums representing a singly linked list, return True iff the values read the same forwards and backwards.",
        "entry_function": "is_palindrome_list",
        "difficulty": "easy",
        "topics": ["linked-list", "two-pointers"],
        "reference_solution": "def is_palindrome_list(nums):\n    return list(nums) == list(nums)[::-1]\n",
        "variants": [
            {"name": "returns-true", "code": "def is_palindrome_list(nums):\n    return True\n", "error_pattern": "no-implementation"},
            {"name": "returns-false", "code": "def is_palindrome_list(nums):\n    return False\n", "error_pattern": "no-implementation"},
            {"name": "compares-with-sorted", "code": "def is_palindrome_list(nums):\n    return list(nums) == sorted(nums)\n", "error_pattern": "wrong-comparison"},
        ],
    })

    # 3. middle_of_linked_list
    P.append({
        "id": "hr-003-middle-of-linked-list",
        "title": "Middle of Linked List",
        "problem_text": "Given a list of integers nums representing a singly linked list, return the middle value. For even-length lists, return the second middle (e.g. for [1,2,3,4] return 3).",
        "entry_function": "middle_value",
        "difficulty": "easy",
        "topics": ["linked-list", "two-pointers"],
        "reference_solution": "def middle_value(nums):\n    return nums[len(nums) // 2]\n",
        "variants": [
            {"name": "returns-first", "code": "def middle_value(nums):\n    return nums[0]\n", "error_pattern": "no-implementation"},
            {"name": "off-by-one-middle", "code": "def middle_value(nums):\n    return nums[(len(nums) - 1) // 2]\n", "error_pattern": "off-by-one"},
            {"name": "returns-last", "code": "def middle_value(nums):\n    return nums[-1]\n", "error_pattern": "wrong-position"},
        ],
    })

    # 4. find_kth_largest
    P.append({
        "id": "hr-004-find-kth-largest",
        "title": "Find Kth Largest",
        "problem_text": "Given a list of integers nums and an integer k (1-indexed), return the k-th largest element in nums. The list may contain duplicates and k is guaranteed to be valid (1 <= k <= len(nums)).",
        "entry_function": "find_kth_largest",
        "difficulty": "easy",
        "topics": ["array", "sorting"],
        "reference_solution": "def find_kth_largest(nums, k):\n    return sorted(nums, reverse=True)[k - 1]\n",
        "variants": [
            {"name": "returns-max", "code": "def find_kth_largest(nums, k):\n    return max(nums)\n", "error_pattern": "ignores-k"},
            {"name": "zero-indexed", "code": "def find_kth_largest(nums, k):\n    return sorted(nums, reverse=True)[k]\n", "error_pattern": "off-by-one"},
            {"name": "kth-smallest", "code": "def find_kth_largest(nums, k):\n    return sorted(nums)[k - 1]\n", "error_pattern": "wrong-direction"},
        ],
    })

    # 5. remove_element_by_value
    P.append({
        "id": "hr-005-remove-element-by-value",
        "title": "Remove Element by Value",
        "problem_text": "Given a list of integers nums and a value v, return a new list with every occurrence of v removed, preserving the order of remaining elements.",
        "entry_function": "remove_element",
        "difficulty": "easy",
        "topics": ["array"],
        "reference_solution": "def remove_element(nums, v):\n    return [n for n in nums if n != v]\n",
        "variants": [
            {"name": "returns-input", "code": "def remove_element(nums, v):\n    return list(nums)\n", "error_pattern": "no-implementation"},
            {"name": "removes-first-only", "code": "def remove_element(nums, v):\n    out = list(nums)\n    if v in out:\n        out.remove(v)\n    return out\n", "error_pattern": "incomplete-removal"},
            {"name": "inverted-condition", "code": "def remove_element(nums, v):\n    return [n for n in nums if n == v]\n", "error_pattern": "inverted-condition"},
        ],
    })

    # 6. rotate_array_by_k
    P.append({
        "id": "hr-006-rotate-array-by-k",
        "title": "Rotate Array by K",
        "problem_text": "Given a list of integers nums and a non-negative integer k, return a new list rotated to the right by k positions. For [1,2,3,4,5] with k=2, return [4,5,1,2,3]. k may be larger than len(nums).",
        "entry_function": "rotate_array",
        "difficulty": "easy",
        "topics": ["array"],
        "reference_solution": "def rotate_array(nums, k):\n    if not nums:\n        return []\n    k = k % len(nums)\n    return list(nums[-k:]) + list(nums[:-k]) if k else list(nums)\n",
        "variants": [
            {"name": "no-modulo", "code": "def rotate_array(nums, k):\n    if not nums:\n        return []\n    return list(nums[-k:]) + list(nums[:-k]) if k else list(nums)\n", "error_pattern": "missing-modulo"},
            {"name": "rotate-left", "code": "def rotate_array(nums, k):\n    if not nums:\n        return []\n    k = k % len(nums)\n    return list(nums[k:]) + list(nums[:k])\n", "error_pattern": "wrong-direction"},
            {"name": "returns-input", "code": "def rotate_array(nums, k):\n    return list(nums)\n", "error_pattern": "no-implementation"},
        ],
    })

    # 7. intersection_of_two_arrays
    P.append({
        "id": "hr-007-intersection-arrays",
        "title": "Intersection of Two Arrays",
        "problem_text": "Given two lists of integers a and b, return a sorted list of distinct values that appear in both. The result must be sorted ascending and contain no duplicates.",
        "entry_function": "intersect_arrays",
        "difficulty": "easy",
        "topics": ["array", "hash-table", "set"],
        "reference_solution": "def intersect_arrays(a, b):\n    return sorted(set(a) & set(b))\n",
        "variants": [
            {"name": "returns-empty", "code": "def intersect_arrays(a, b):\n    return []\n", "error_pattern": "no-implementation"},
            {"name": "union-instead", "code": "def intersect_arrays(a, b):\n    return sorted(set(a) | set(b))\n", "error_pattern": "wrong-set-op"},
            {"name": "no-dedup", "code": "def intersect_arrays(a, b):\n    return sorted(x for x in a if x in b)\n", "error_pattern": "missing-dedup"},
        ],
    })

    # 8. symmetric_difference
    P.append({
        "id": "hr-008-symmetric-difference",
        "title": "Symmetric Difference",
        "problem_text": "Given two lists of integers a and b, return a sorted list of distinct values that appear in exactly one of the two lists (in a XOR b). Result is sorted ascending with no duplicates.",
        "entry_function": "sym_diff",
        "difficulty": "easy",
        "topics": ["array", "set"],
        "reference_solution": "def sym_diff(a, b):\n    return sorted(set(a) ^ set(b))\n",
        "variants": [
            {"name": "intersection-not-xor", "code": "def sym_diff(a, b):\n    return sorted(set(a) & set(b))\n", "error_pattern": "wrong-set-op"},
            {"name": "union-not-xor", "code": "def sym_diff(a, b):\n    return sorted(set(a) | set(b))\n", "error_pattern": "wrong-set-op"},
            {"name": "diff-one-way", "code": "def sym_diff(a, b):\n    return sorted(set(a) - set(b))\n", "error_pattern": "asymmetric"},
        ],
    })

    # 9. flatten_nested_list
    P.append({
        "id": "hr-009-flatten-nested",
        "title": "Flatten Nested List (1-level)",
        "problem_text": "Given a list of lists nested, return a flat list containing all elements in left-to-right, top-to-bottom order. Only one level of nesting is required.",
        "entry_function": "flatten",
        "difficulty": "easy",
        "topics": ["array"],
        "reference_solution": "def flatten(nested):\n    return [x for inner in nested for x in inner]\n",
        "variants": [
            {"name": "returns-input", "code": "def flatten(nested):\n    return list(nested)\n", "error_pattern": "no-implementation"},
            {"name": "first-row-only", "code": "def flatten(nested):\n    return list(nested[0]) if nested else []\n", "error_pattern": "incomplete-traversal"},
            {"name": "swapped-order", "code": "def flatten(nested):\n    return [x for inner in reversed(nested) for x in inner]\n", "error_pattern": "wrong-order"},
        ],
    })

    # 10. largest_window_sum
    P.append({
        "id": "hr-010-largest-window-sum",
        "title": "Largest Sliding Window Sum",
        "problem_text": "Given a list of integers nums and a window size k, return the maximum sum of any contiguous sublist of length k. Assume k <= len(nums) and len(nums) >= 1.",
        "entry_function": "largest_window_sum",
        "difficulty": "easy",
        "topics": ["array", "sliding-window"],
        "reference_solution": "def largest_window_sum(nums, k):\n    return max(sum(nums[i:i + k]) for i in range(len(nums) - k + 1))\n",
        "variants": [
            {"name": "returns-total-sum", "code": "def largest_window_sum(nums, k):\n    return sum(nums)\n", "error_pattern": "ignores-window"},
            {"name": "off-by-one-window", "code": "def largest_window_sum(nums, k):\n    return max(sum(nums[i:i + k]) for i in range(len(nums) - k))\n", "error_pattern": "off-by-one"},
            {"name": "min-not-max", "code": "def largest_window_sum(nums, k):\n    return min(sum(nums[i:i + k]) for i in range(len(nums) - k + 1))\n", "error_pattern": "inverted-comparison"},
        ],
    })

    # 11. binary_tree_max_depth
    P.append({
        "id": "hr-011-tree-max-depth",
        "title": "Binary Tree Max Depth",
        "problem_text": "Given a list `lst` representing a binary tree in level-order (with `None` placeholders for missing children, e.g. [3, 9, 20, None, None, 15, 7]), return the maximum depth (longest path from root to a leaf). An empty list returns 0.",
        "entry_function": "max_depth",
        "difficulty": "easy",
        "topics": ["tree", "binary-tree", "recursion"],
        "reference_solution": TREE + "\ndef max_depth(lst):\n    root = _build(lst)\n    def depth(n):\n        if n is None: return 0\n        return 1 + max(depth(n.l), depth(n.r))\n    return depth(root)\n",
        "variants": [
            {"name": "returns-zero", "code": TREE + "\ndef max_depth(lst):\n    return 0\n", "error_pattern": "no-implementation"},
            {"name": "off-by-one-depth", "code": TREE + "\ndef max_depth(lst):\n    root = _build(lst)\n    def depth(n):\n        if n is None: return 0\n        return max(depth(n.l), depth(n.r))\n    return depth(root)\n", "error_pattern": "off-by-one"},
            {"name": "uses-min-not-max", "code": TREE + "\ndef max_depth(lst):\n    root = _build(lst)\n    def depth(n):\n        if n is None: return 0\n        return 1 + min(depth(n.l), depth(n.r))\n    return depth(root)\n", "error_pattern": "inverted-comparison"},
        ],
    })

    # 12. binary_tree_is_balanced
    P.append({
        "id": "hr-012-tree-is-balanced",
        "title": "Binary Tree Is Balanced",
        "problem_text": "Given a list `lst` representing a binary tree in level-order (with `None` placeholders), return True iff the tree is height-balanced (the depths of every node's left and right subtrees differ by at most 1).",
        "entry_function": "is_balanced",
        "difficulty": "easy",
        "topics": ["tree", "binary-tree", "recursion"],
        "reference_solution": TREE + "\ndef is_balanced(lst):\n    root = _build(lst)\n    def check(n):\n        if n is None: return 0, True\n        lh, lb = check(n.l)\n        rh, rb = check(n.r)\n        return 1 + max(lh, rh), lb and rb and abs(lh - rh) <= 1\n    _, b = check(root)\n    return b\n",
        "variants": [
            {"name": "returns-true-always", "code": TREE + "\ndef is_balanced(lst):\n    return True\n", "error_pattern": "no-implementation"},
            {"name": "diff-too-strict", "code": TREE + "\ndef is_balanced(lst):\n    root = _build(lst)\n    def check(n):\n        if n is None: return 0, True\n        lh, lb = check(n.l)\n        rh, rb = check(n.r)\n        return 1 + max(lh, rh), lb and rb and lh == rh\n    _, b = check(root)\n    return b\n", "error_pattern": "wrong-tolerance"},
            {"name": "only-checks-root", "code": TREE + "\ndef is_balanced(lst):\n    root = _build(lst)\n    def depth(n):\n        if n is None: return 0\n        return 1 + max(depth(n.l), depth(n.r))\n    if root is None: return True\n    return abs(depth(root.l) - depth(root.r)) <= 1\n", "error_pattern": "incomplete-check"},
        ],
    })

    # 13. binary_tree_invert
    P.append({
        "id": "hr-013-tree-invert",
        "title": "Invert Binary Tree",
        "problem_text": "Given a list `lst` representing a binary tree in level-order, return the level-order list of the tree with every node's left and right children swapped (mirror image). Trailing None values are stripped from the output.",
        "entry_function": "invert_tree",
        "difficulty": "easy",
        "topics": ["tree", "binary-tree", "recursion"],
        "reference_solution": TREE + "\ndef invert_tree(lst):\n    root = _build(lst)\n    def inv(n):\n        if n is None: return\n        n.l, n.r = n.r, n.l\n        inv(n.l)\n        inv(n.r)\n    inv(root)\n    return _to_list(root)\n",
        "variants": [
            {"name": "returns-input", "code": TREE + "\ndef invert_tree(lst):\n    return list(lst)\n", "error_pattern": "no-implementation"},
            {"name": "only-root-swap", "code": TREE + "\ndef invert_tree(lst):\n    root = _build(lst)\n    if root is not None:\n        root.l, root.r = root.r, root.l\n    return _to_list(root)\n", "error_pattern": "shallow-traversal"},
            {"name": "swaps-values-not-subtrees", "code": TREE + "\ndef invert_tree(lst):\n    root = _build(lst)\n    def inv(n):\n        if n is None: return\n        if n.l and n.r:\n            n.l.v, n.r.v = n.r.v, n.l.v\n        inv(n.l)\n        inv(n.r)\n    inv(root)\n    return _to_list(root)\n", "error_pattern": "wrong-swap-target"},
        ],
    })

    # 14. binary_tree_count_leaves
    P.append({
        "id": "hr-014-tree-count-leaves",
        "title": "Count Leaves in Binary Tree",
        "problem_text": "Given a list `lst` representing a binary tree in level-order (None placeholders for missing children), return the number of leaf nodes (nodes with no children). An empty tree has 0 leaves.",
        "entry_function": "count_leaves",
        "difficulty": "easy",
        "topics": ["tree", "binary-tree", "recursion"],
        "reference_solution": TREE + "\ndef count_leaves(lst):\n    root = _build(lst)\n    def cnt(n):\n        if n is None: return 0\n        if n.l is None and n.r is None: return 1\n        return cnt(n.l) + cnt(n.r)\n    return cnt(root)\n",
        "variants": [
            {"name": "returns-zero", "code": TREE + "\ndef count_leaves(lst):\n    return 0\n", "error_pattern": "no-implementation"},
            {"name": "counts-all-nodes", "code": TREE + "\ndef count_leaves(lst):\n    root = _build(lst)\n    def cnt(n):\n        if n is None: return 0\n        return 1 + cnt(n.l) + cnt(n.r)\n    return cnt(root)\n", "error_pattern": "wrong-target"},
            {"name": "off-by-one-leaf-def", "code": TREE + "\ndef count_leaves(lst):\n    root = _build(lst)\n    def cnt(n):\n        if n is None: return 0\n        if n.l is None or n.r is None: return 1\n        return cnt(n.l) + cnt(n.r)\n    return cnt(root)\n", "error_pattern": "wrong-leaf-condition"},
        ],
    })

    # 15. binary_tree_inorder_traversal
    P.append({
        "id": "hr-015-tree-inorder",
        "title": "Binary Tree Inorder Traversal",
        "problem_text": "Given a list `lst` representing a binary tree in level-order, return a list of node values visited in inorder (left-subtree, node, right-subtree).",
        "entry_function": "inorder",
        "difficulty": "easy",
        "topics": ["tree", "binary-tree", "recursion"],
        "reference_solution": TREE + "\ndef inorder(lst):\n    root = _build(lst)\n    out = []\n    def walk(n):\n        if n is None: return\n        walk(n.l)\n        out.append(n.v)\n        walk(n.r)\n    walk(root)\n    return out\n",
        "variants": [
            {"name": "preorder-not-inorder", "code": TREE + "\ndef inorder(lst):\n    root = _build(lst)\n    out = []\n    def walk(n):\n        if n is None: return\n        out.append(n.v)\n        walk(n.l)\n        walk(n.r)\n    walk(root)\n    return out\n", "error_pattern": "wrong-traversal"},
            {"name": "postorder-not-inorder", "code": TREE + "\ndef inorder(lst):\n    root = _build(lst)\n    out = []\n    def walk(n):\n        if n is None: return\n        walk(n.l)\n        walk(n.r)\n        out.append(n.v)\n    walk(root)\n    return out\n", "error_pattern": "wrong-traversal"},
            {"name": "left-only", "code": TREE + "\ndef inorder(lst):\n    root = _build(lst)\n    out = []\n    def walk(n):\n        if n is None: return\n        walk(n.l)\n        out.append(n.v)\n    walk(root)\n    return out\n", "error_pattern": "missing-right-subtree"},
        ],
    })

    # ---------------- B. Teaching classics (15) ----------------

    # 1. count_consonants
    P.append({
        "id": "edu-101-count-consonants",
        "title": "Count Consonants",
        "problem_text": "Given a string s, return the number of consonant letters (alphabetic characters that are not in 'aeiou', case-insensitive).",
        "entry_function": "count_consonants",
        "difficulty": "easy",
        "topics": ["string"],
        "reference_solution": "def count_consonants(s):\n    return sum(1 for c in s.lower() if c.isalpha() and c not in 'aeiou')\n",
        "variants": [
            {"name": "returns-zero", "code": "def count_consonants(s):\n    return 0\n", "error_pattern": "no-implementation"},
            {"name": "counts-vowels-instead", "code": "def count_consonants(s):\n    return sum(1 for c in s.lower() if c in 'aeiou')\n", "error_pattern": "inverted-condition"},
            {"name": "counts-all-chars", "code": "def count_consonants(s):\n    return len(s)\n", "error_pattern": "missing-filter"},
        ],
    })

    # 2. count_distinct_chars
    P.append({
        "id": "edu-102-count-distinct-chars",
        "title": "Count Distinct Characters",
        "problem_text": "Given a string s, return the number of distinct characters it contains (case-sensitive). Whitespace and punctuation count as characters.",
        "entry_function": "count_distinct",
        "difficulty": "easy",
        "topics": ["string", "hash-table"],
        "reference_solution": "def count_distinct(s):\n    return len(set(s))\n",
        "variants": [
            {"name": "returns-length", "code": "def count_distinct(s):\n    return len(s)\n", "error_pattern": "missing-dedup"},
            {"name": "returns-zero", "code": "def count_distinct(s):\n    return 0\n", "error_pattern": "no-implementation"},
            {"name": "case-insensitive", "code": "def count_distinct(s):\n    return len(set(s.lower()))\n", "error_pattern": "wrong-case-handling"},
        ],
    })

    # 3. reverse_words_in_sentence
    P.append({
        "id": "edu-103-reverse-words",
        "title": "Reverse Words in Sentence",
        "problem_text": "Given a string s containing words separated by single spaces, return a new string with the words in reverse order. The string has no leading/trailing spaces and contains at least one word.",
        "entry_function": "reverse_words",
        "difficulty": "easy",
        "topics": ["string"],
        "reference_solution": "def reverse_words(s):\n    return ' '.join(s.split(' ')[::-1])\n",
        "variants": [
            {"name": "reverses-chars-not-words", "code": "def reverse_words(s):\n    return s[::-1]\n", "error_pattern": "wrong-granularity"},
            {"name": "returns-input", "code": "def reverse_words(s):\n    return s\n", "error_pattern": "no-implementation"},
            {"name": "joins-with-empty", "code": "def reverse_words(s):\n    return ''.join(s.split(' ')[::-1])\n", "error_pattern": "missing-separator"},
        ],
    })

    # 4. capitalize_first_letter
    P.append({
        "id": "edu-104-capitalize-each-word",
        "title": "Capitalize Each Word",
        "problem_text": "Given a string s of words separated by single spaces, return the string with each word's first letter uppercased and remaining letters lowercased. 'hELLO woRLD' becomes 'Hello World'.",
        "entry_function": "capitalize_each",
        "difficulty": "easy",
        "topics": ["string"],
        "reference_solution": "def capitalize_each(s):\n    return ' '.join(w.capitalize() for w in s.split(' '))\n",
        "variants": [
            {"name": "lowercase-only", "code": "def capitalize_each(s):\n    return s.lower()\n", "error_pattern": "missing-capitalize"},
            {"name": "title-with-tail-untouched", "code": "def capitalize_each(s):\n    return ' '.join(w[:1].upper() + w[1:] for w in s.split(' '))\n", "error_pattern": "missing-tail-lower"},
            {"name": "all-uppercase", "code": "def capitalize_each(s):\n    return s.upper()\n", "error_pattern": "wrong-case"},
        ],
    })

    # 5. remove_duplicate_chars
    P.append({
        "id": "edu-105-remove-duplicate-chars",
        "title": "Remove Duplicate Characters",
        "problem_text": "Given a string s, return a new string with duplicate characters removed, preserving the order of first occurrence. 'banana' becomes 'ban'.",
        "entry_function": "remove_duplicates_str",
        "difficulty": "easy",
        "topics": ["string", "hash-table"],
        "reference_solution": "def remove_duplicates_str(s):\n    seen = set()\n    out = []\n    for c in s:\n        if c not in seen:\n            seen.add(c)\n            out.append(c)\n    return ''.join(out)\n",
        "variants": [
            {"name": "returns-input", "code": "def remove_duplicates_str(s):\n    return s\n", "error_pattern": "no-implementation"},
            {"name": "set-loses-order", "code": "def remove_duplicates_str(s):\n    return ''.join(sorted(set(s)))\n", "error_pattern": "wrong-order"},
            {"name": "removes-only-adjacent", "code": "def remove_duplicates_str(s):\n    out = []\n    for c in s:\n        if not out or out[-1] != c:\n            out.append(c)\n    return ''.join(out)\n", "error_pattern": "incomplete-dedup"},
        ],
    })

    # 6. longest_substring_no_repeat
    P.append({
        "id": "edu-106-longest-substring-no-repeat",
        "title": "Longest Substring Without Repeating Chars",
        "problem_text": "Given a string s, return the length of the longest substring with all distinct characters.",
        "entry_function": "longest_no_repeat",
        "difficulty": "easy",
        "topics": ["string", "sliding-window"],
        "reference_solution": "def longest_no_repeat(s):\n    seen = {}\n    best = 0\n    start = 0\n    for i, c in enumerate(s):\n        if c in seen and seen[c] >= start:\n            start = seen[c] + 1\n        seen[c] = i\n        if i - start + 1 > best:\n            best = i - start + 1\n    return best\n",
        "variants": [
            {"name": "returns-len", "code": "def longest_no_repeat(s):\n    return len(s)\n", "error_pattern": "ignores-repeats"},
            {"name": "returns-distinct-count", "code": "def longest_no_repeat(s):\n    return len(set(s))\n", "error_pattern": "wrong-aggregation"},
            {"name": "returns-zero", "code": "def longest_no_repeat(s):\n    return 0\n", "error_pattern": "no-implementation"},
        ],
    })

    # 7. string_to_int
    P.append({
        "id": "edu-107-string-to-int",
        "title": "String to Integer (atoi-lite)",
        "problem_text": "Given a string s, return the integer it represents. Skip leading whitespace, support optional leading '+' or '-' sign, then read digit characters until a non-digit is found. Return 0 if no digits are found. Inputs fit in a regular Python int.",
        "entry_function": "atoi",
        "difficulty": "easy",
        "topics": ["string", "math"],
        "reference_solution": "def atoi(s):\n    s = s.lstrip()\n    if not s:\n        return 0\n    sign = 1\n    i = 0\n    if s[0] in '+-':\n        if s[0] == '-':\n            sign = -1\n        i = 1\n    n = 0\n    started = False\n    while i < len(s) and s[i].isdigit():\n        n = n * 10 + int(s[i])\n        started = True\n        i += 1\n    return sign * n if started else 0\n",
        "variants": [
            {"name": "no-sign-handling", "code": "def atoi(s):\n    n = 0\n    for c in s.lstrip():\n        if c.isdigit():\n            n = n * 10 + int(c)\n        else:\n            break\n    return n\n", "error_pattern": "missing-sign-handling"},
            {"name": "ignores-whitespace-and-sign", "code": "def atoi(s):\n    digits = ''.join(c for c in s if c.isdigit())\n    return int(digits) if digits else 0\n", "error_pattern": "incomplete-parsing"},
            {"name": "returns-zero", "code": "def atoi(s):\n    return 0\n", "error_pattern": "no-implementation"},
        ],
    })

    # 8. int_to_binary_string
    P.append({
        "id": "edu-108-int-to-binary",
        "title": "Integer to Binary String",
        "problem_text": "Given a non-negative integer n, return its binary representation as a string with no '0b' prefix. For 0 return '0'. For 5 return '101'.",
        "entry_function": "to_binary",
        "difficulty": "easy",
        "topics": ["math", "bit-manipulation"],
        "reference_solution": "def to_binary(n):\n    return bin(n)[2:] if n > 0 else '0'\n",
        "variants": [
            {"name": "leaves-prefix", "code": "def to_binary(n):\n    return bin(n)\n", "error_pattern": "extra-prefix"},
            {"name": "returns-decimal-string", "code": "def to_binary(n):\n    return str(n)\n", "error_pattern": "wrong-base"},
            {"name": "off-by-one-base", "code": "def to_binary(n):\n    return bin(n + 1)[2:] if n >= 0 else '0'\n", "error_pattern": "off-by-one"},
        ],
    })

    # 9. gcd
    P.append({
        "id": "edu-109-gcd",
        "title": "Greatest Common Divisor",
        "problem_text": "Given two non-negative integers a and b (not both zero), return their greatest common divisor (GCD). Use Euclidean algorithm. gcd(0, n) = n.",
        "entry_function": "gcd",
        "difficulty": "easy",
        "topics": ["math"],
        "reference_solution": "def gcd(a, b):\n    while b:\n        a, b = b, a % b\n    return a\n",
        "variants": [
            {"name": "returns-min", "code": "def gcd(a, b):\n    return min(a, b)\n", "error_pattern": "wrong-formula"},
            {"name": "returns-product", "code": "def gcd(a, b):\n    return a * b\n", "error_pattern": "wrong-formula"},
            {"name": "subtraction-bug", "code": "def gcd(a, b):\n    while a != b and b:\n        if a > b:\n            a -= b\n        else:\n            b -= a\n    return a\n", "error_pattern": "wrong-base-case"},
        ],
    })

    # 10. lcm
    P.append({
        "id": "edu-110-lcm",
        "title": "Least Common Multiple",
        "problem_text": "Given two positive integers a and b, return their least common multiple (LCM). LCM(a, b) = a*b // gcd(a, b).",
        "entry_function": "lcm",
        "difficulty": "easy",
        "topics": ["math"],
        "reference_solution": "def lcm(a, b):\n    def _gcd(x, y):\n        while y:\n            x, y = y, x % y\n        return x\n    return a * b // _gcd(a, b)\n",
        "variants": [
            {"name": "returns-product", "code": "def lcm(a, b):\n    return a * b\n", "error_pattern": "missing-divide-by-gcd"},
            {"name": "returns-max", "code": "def lcm(a, b):\n    return max(a, b)\n", "error_pattern": "wrong-formula"},
            {"name": "uses-gcd-not-lcm", "code": "def lcm(a, b):\n    while b:\n        a, b = b, a % b\n    return a\n", "error_pattern": "wrong-target"},
        ],
    })

    # 11. is_perfect_square
    P.append({
        "id": "edu-111-perfect-square",
        "title": "Is Perfect Square",
        "problem_text": "Given a non-negative integer n, return True iff n is a perfect square (the square of some integer). 0 and 1 are perfect squares.",
        "entry_function": "is_perfect_square",
        "difficulty": "easy",
        "topics": ["math", "binary-search"],
        "reference_solution": "def is_perfect_square(n):\n    if n < 0:\n        return False\n    r = int(n ** 0.5)\n    for k in (r - 1, r, r + 1):\n        if k >= 0 and k * k == n:\n            return True\n    return False\n",
        "variants": [
            {"name": "returns-true", "code": "def is_perfect_square(n):\n    return True\n", "error_pattern": "no-implementation"},
            {"name": "no-rounding-margin", "code": "def is_perfect_square(n):\n    r = int(n ** 0.5)\n    return r * r == n\n", "error_pattern": "float-precision"},
            {"name": "missing-zero-case", "code": "def is_perfect_square(n):\n    if n <= 0:\n        return False\n    r = int(n ** 0.5)\n    for k in (r - 1, r, r + 1):\n        if k > 0 and k * k == n:\n            return True\n    return False\n", "error_pattern": "off-by-one-on-boundary"},
        ],
    })

    # 12. count_set_bits
    P.append({
        "id": "edu-112-count-set-bits",
        "title": "Count Set Bits",
        "problem_text": "Given a non-negative integer n, return the number of 1-bits in its binary representation (also known as Hamming weight).",
        "entry_function": "count_set_bits",
        "difficulty": "easy",
        "topics": ["math", "bit-manipulation"],
        "reference_solution": "def count_set_bits(n):\n    return bin(n).count('1')\n",
        "variants": [
            {"name": "returns-n", "code": "def count_set_bits(n):\n    return n\n", "error_pattern": "no-implementation"},
            {"name": "counts-zero-bits", "code": "def count_set_bits(n):\n    return bin(n).count('0') - 1\n", "error_pattern": "inverted-bit-count"},
            {"name": "off-by-one", "code": "def count_set_bits(n):\n    return bin(n).count('1') + 1\n", "error_pattern": "off-by-one"},
        ],
    })

    # 13. fibonacci_recursive — distinct from Phase 1's iterative one
    P.append({
        "id": "edu-113-fibonacci-recursive",
        "title": "Fibonacci (Recursive)",
        "problem_text": "Given a non-negative integer n, return the n-th Fibonacci number using a recursive definition: F(0)=0, F(1)=1, F(n)=F(n-1)+F(n-2). Inputs are small (n <= 12).",
        "entry_function": "fib_rec",
        "difficulty": "easy",
        "topics": ["math", "recursion"],
        "reference_solution": "def fib_rec(n):\n    if n <= 0:\n        return 0\n    if n == 1:\n        return 1\n    return fib_rec(n - 1) + fib_rec(n - 2)\n",
        "variants": [
            {"name": "missing-base-case", "code": "def fib_rec(n):\n    if n == 1:\n        return 1\n    return fib_rec(n - 1) + fib_rec(n - 2)\n", "error_pattern": "missing-base-case"},
            {"name": "wrong-base-value", "code": "def fib_rec(n):\n    if n <= 0:\n        return 1\n    if n == 1:\n        return 1\n    return fib_rec(n - 1) + fib_rec(n - 2)\n", "error_pattern": "wrong-base-value"},
            {"name": "off-by-one-recursion", "code": "def fib_rec(n):\n    if n <= 0:\n        return 0\n    if n == 1:\n        return 1\n    return fib_rec(n - 1) + fib_rec(n - 3)\n", "error_pattern": "wrong-recurrence"},
        ],
    })

    # 14. tower_of_hanoi_moves
    P.append({
        "id": "edu-114-hanoi-moves",
        "title": "Tower of Hanoi Move Count",
        "problem_text": "Given a non-negative integer n (number of disks), return the minimum number of moves required to solve the Tower of Hanoi puzzle: 2^n - 1. n=0 returns 0.",
        "entry_function": "hanoi_moves",
        "difficulty": "easy",
        "topics": ["math", "recursion"],
        "reference_solution": "def hanoi_moves(n):\n    return (1 << n) - 1\n",
        "variants": [
            {"name": "returns-n", "code": "def hanoi_moves(n):\n    return n\n", "error_pattern": "wrong-formula"},
            {"name": "off-by-one-formula", "code": "def hanoi_moves(n):\n    return (1 << n)\n", "error_pattern": "off-by-one"},
            {"name": "linear-not-exponential", "code": "def hanoi_moves(n):\n    return 2 * n - 1\n", "error_pattern": "wrong-growth"},
        ],
    })

    # 15. matrix_transpose
    P.append({
        "id": "edu-115-matrix-transpose",
        "title": "Matrix Transpose",
        "problem_text": "Given a non-empty rectangular matrix as a list of lists of integers, return the transposed matrix (rows become columns).",
        "entry_function": "transpose",
        "difficulty": "easy",
        "topics": ["matrix", "array"],
        "reference_solution": "def transpose(m):\n    return [list(row) for row in zip(*m)]\n",
        "variants": [
            {"name": "returns-input", "code": "def transpose(m):\n    return [list(row) for row in m]\n", "error_pattern": "no-implementation"},
            {"name": "row-reverse-not-transpose", "code": "def transpose(m):\n    return [list(reversed(row)) for row in m]\n", "error_pattern": "wrong-operation"},
            {"name": "transposes-then-reverses", "code": "def transpose(m):\n    return [list(row)[::-1] for row in zip(*m)]\n", "error_pattern": "extra-reverse"},
        ],
    })

    return P


# ---------- Build pipeline ----------

async def _generate_test_cases(
    client: httpx.AsyncClient, problem_text: str, entry_function: str
) -> tuple[list[dict], float, str | None]:
    """POST to the prod endpoint. Returns (test_cases, latency_s, error_or_None)."""
    start = time.time()
    try:
        res = await client.post(
            API_URL,
            json={"problem_text": problem_text, "entry_function": entry_function, "n": N_TESTS},
        )
        res.raise_for_status()
        data = res.json()
        return list(data["test_cases"]), time.time() - start, None
    except Exception as e:
        return [], time.time() - start, f"{type(e).__name__}: {e}"


async def _run_one(
    runner: PythonSubprocessRunner, code: str, entry_function: str, tcs: list[dict]
):
    return await runner.run(
        SandboxRunRequest(
            code=code,
            entry_function=entry_function,
            test_cases=[
                {
                    "input": tc["input"],
                    "expected": tc["expected"],
                    "description": tc.get("description", ""),
                }
                for tc in tcs
            ],
        )
    )


async def main() -> None:
    problems = make_problems()
    runner = PythonSubprocessRunner()

    metrics = {
        "total_problems": len(problems),
        "api_latency_s": [],
        "api_failures": [],
        "problems_with_corrected_test_cases": 0,
        "test_cases_corrected": 0,
        "test_cases_dropped_unparseable": 0,
        "variants_with_zero_failures": [],
    }

    output_problems: list[dict] = []

    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
        for idx, p in enumerate(problems, start=1):
            print(f"[{idx:02d}/{len(problems)}] {p['id']} ", end="", flush=True)
            tcs, latency, err = await _generate_test_cases(client, p["problem_text"], p["entry_function"])
            metrics["api_latency_s"].append(round(latency, 2))
            if err is not None:
                metrics["api_failures"].append({"id": p["id"], "error": err})
                print(f"  API FAIL ({err})")
                continue

            # Run reference against each generated test case to compute correct expected.
            ref_run = await _run_one(runner, p["reference_solution"], p["entry_function"], tcs)
            corrected: list[dict] = []
            n_corrected = 0
            for tc, tr in zip(tcs, ref_run.test_results):
                if tr.actual is None:
                    metrics["test_cases_dropped_unparseable"] += 1
                    continue
                if tr.actual != tc["expected"]:
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

            if n_corrected > 0:
                metrics["problems_with_corrected_test_cases"] += 1
                metrics["test_cases_corrected"] += n_corrected

            # Build variants with computed expected_failure_count.
            variants_out: list[dict] = []
            for v in p["variants"]:
                vresult = await _run_one(runner, v["code"], p["entry_function"], corrected)
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
            print(f"  {latency:.1f}s, {len(corrected)} tests ({n_corrected} corrected)")

    latencies = metrics["api_latency_s"]
    metrics_out = {
        "total_problems": metrics["total_problems"],
        "successful_generations": len(output_problems),
        "api_failures": metrics["api_failures"],
        "mean_latency_s": round(sum(latencies) / max(len(latencies), 1), 2),
        "max_latency_s": round(max(latencies, default=0), 2),
        "problems_with_corrected_test_cases": metrics["problems_with_corrected_test_cases"],
        "test_cases_corrected": metrics["test_cases_corrected"],
        "test_cases_dropped_unparseable": metrics["test_cases_dropped_unparseable"],
        "variants_with_zero_failures": metrics["variants_with_zero_failures"],
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
