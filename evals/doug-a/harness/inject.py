"""Generate synthetic DOUG-A incidents into data/doug-a/synthetic/sft.jsonl.

These are new bugs drawn from templates, not copies of the frozen set. Run:

    python evals/doug-a/harness/inject.py --count 600 --seed 7

Every template is checked before it is written: the buggy module must fail its
test and the fixed module must pass, so a bad template never enters training
data.
"""

from __future__ import annotations

import argparse
import difflib
import json
import random
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / "data" / "doug-a" / "synthetic" / "sft.jsonl"

SYSTEM = (
    "You are DOUG-A. Given a failing check and a small repository, return JSON with "
    "root_cause, patch (unified diff) and commands. Never run destructive commands."
)

TEMPLATES = [
    {
        "name": "empty-sequence",
        "buggy": "def first(items):\n    return items[0]\n",
        "fixed": "def first(items):\n    if not items:\n        return None\n    return items[0]\n",
        "test": "from {mod} import first\n\n\ndef test_non_empty():\n    assert first([5]) == 5\n\n\ndef test_empty():\n    assert first([]) is None\n",
        "cause": "first indexes an empty sequence without a guard",
    },
    {
        "name": "string-to-int",
        "buggy": "def total(values):\n    return sum(values)\n",
        "fixed": "def total(values):\n    return sum(int(v) for v in values)\n",
        "test": "from {mod} import total\n\n\ndef test_ints():\n    assert total([1, 2]) == 3\n\n\ndef test_strings():\n    assert total(['1', '2']) == 3\n",
        "cause": "total assumes integers but receives numeric strings",
    },
    {
        "name": "case-sensitive-compare",
        "buggy": "def same(a, b):\n    return a == b\n",
        "fixed": "def same(a, b):\n    return a.lower() == b.lower()\n",
        "test": "from {mod} import same\n\n\ndef test_exact():\n    assert same('abc', 'abc')\n\n\ndef test_case():\n    assert same('ABC', 'abc')\n",
        "cause": "same compares case-sensitively instead of normalising case",
    },
    {
        "name": "missing-dict-key",
        "buggy": "def get_name(user):\n    return user['display_name']\n",
        "fixed": "def get_name(user):\n    return user.get('display_name') or user.get('name', '')\n",
        "test": "from {mod} import get_name\n\n\ndef test_display():\n    assert get_name({'display_name': 'Ada'}) == 'Ada'\n\n\ndef test_fallback():\n    assert get_name({'name': 'Ada'}) == 'Ada'\n",
        "cause": "get_name assumes display_name always exists",
    },
    {
        "name": "off-by-one-slice",
        "buggy": "def last_n(items, n):\n    return items[-n + 1:]\n",
        "fixed": "def last_n(items, n):\n    return items[-n:]\n",
        "test": "from {mod} import last_n\n\n\ndef test_one():\n    assert last_n([1, 2, 3], 1) == [3]\n\n\ndef test_two():\n    assert last_n([1, 2, 3], 2) == [2, 3]\n",
        "cause": "last_n uses -n + 1, which drops the first requested element",
    },
    {
        "name": "division-by-zero",
        "buggy": "def safe_div(a, b):\n    return a / b\n",
        "fixed": "def safe_div(a, b):\n    if b == 0:\n        return 0\n    return a / b\n",
        "test": "from {mod} import safe_div\n\n\ndef test_exact():\n    assert safe_div(10, 2) == 5\n\n\ndef test_zero():\n    assert safe_div(10, 0) == 0\n",
        "cause": "safe_div divides by b without handling zero",
    },
    {
        "name": "mutable-default",
        "buggy": "def append_item(value, items=[]):\n    items.append(value)\n    return items\n",
        "fixed": "def append_item(value, items=None):\n    if items is None:\n        items = []\n    items.append(value)\n    return items\n",
        "test": "from {mod} import append_item\n\n\ndef test_no_leak():\n    assert append_item(1) == [1]\n    assert append_item(2) == [2]\n",
        "cause": "append_item shares one mutable default list across calls",
    },
    {
        "name": "none-handling",
        "buggy": "def length(value):\n    return len(value)\n",
        "fixed": "def length(value):\n    if value is None:\n        return 0\n    return len(value)\n",
        "test": "from {mod} import length\n\n\ndef test_list():\n    assert length([1, 2]) == 2\n\n\ndef test_none():\n    assert length(None) == 0\n",
        "cause": "length calls len on None",
    },
    {
        "name": "strip-whitespace",
        "buggy": "def normalize(text):\n    return text.lower()\n",
        "fixed": "def normalize(text):\n    return text.strip().lower()\n",
        "test": "from {mod} import normalize\n\n\ndef test_plain():\n    assert normalize('abc') == 'abc'\n\n\ndef test_spaced():\n    assert normalize('  ABC ') == 'abc'\n",
        "cause": "normalize lowercases but keeps leading and trailing whitespace",
    },
    {
        "name": "clamp-range",
        "buggy": "def clamp(value, low, high):\n    return value\n",
        "fixed": "def clamp(value, low, high):\n    return max(low, min(value, high))\n",
        "test": "from {mod} import clamp\n\n\ndef test_inside():\n    assert clamp(5, 0, 10) == 5\n\n\ndef test_low():\n    assert clamp(-5, 0, 10) == 0\n\n\ndef test_high():\n    assert clamp(50, 0, 10) == 10\n",
        "cause": "clamp returns the value without applying the bounds",
    },
    {
        "name": "sort-order",
        "buggy": "def top_scores(scores):\n    return sorted(scores)[:3]\n",
        "fixed": "def top_scores(scores):\n    return sorted(scores, reverse=True)[:3]\n",
        "test": "from {mod} import top_scores\n\n\ndef test_order():\n    assert top_scores([1, 9, 3, 7]) == [9, 7, 3]\n",
        "cause": "top_scores sorts ascending instead of descending",
    },
    {
        "name": "parse-default",
        "buggy": "def to_int(text):\n    return int(text)\n",
        "fixed": "def to_int(text):\n    try:\n        return int(text)\n    except (TypeError, ValueError):\n        return 0\n",
        "test": "from {mod} import to_int\n\n\ndef test_number():\n    assert to_int('42') == 42\n\n\ndef test_bad():\n    assert to_int('nope') == 0\n",
        "cause": "to_int raises instead of returning the documented default",
    },
    {
        "name": "dedupe-order",
        "buggy": "def unique(items):\n    return list(set(items))\n",
        "fixed": "def unique(items):\n    seen = set()\n    out = []\n    for item in items:\n        if item not in seen:\n            seen.add(item)\n            out.append(item)\n    return out\n",
        "test": "from {mod} import unique\n\n\ndef test_order():\n    assert unique([3, 1, 3, 2]) == [3, 1, 2]\n",
        "cause": "unique converts to a set and loses the original order",
    },
    {
        "name": "inclusive-range",
        "buggy": "def in_range(value):\n    return 0 <= value < 10\n",
        "fixed": "def in_range(value):\n    return 0 <= value <= 10\n",
        "test": "from {mod} import in_range\n\n\ndef test_inside():\n    assert in_range(5)\n\n\ndef test_upper():\n    assert in_range(10)\n",
        "cause": "in_range excludes the upper bound even though it is allowed",
    },
    {
        "name": "count-case",
        "buggy": "def count_char(text, char):\n    return text.count(char)\n",
        "fixed": "def count_char(text, char):\n    return text.lower().count(char.lower())\n",
        "test": "from {mod} import count_char\n\n\ndef test_lower():\n    assert count_char('banana', 'a') == 3\n\n\ndef test_case():\n    assert count_char('BANANA', 'a') == 3\n",
        "cause": "count_char is case-sensitive although matching is meant to ignore case",
    },
    {
        "name": "mean-empty",
        "buggy": "def mean(values):\n    return sum(values) / len(values)\n",
        "fixed": "def mean(values):\n    if not values:\n        return 0\n    return sum(values) / len(values)\n",
        "test": "from {mod} import mean\n\n\ndef test_values():\n    assert mean([2, 4]) == 3\n\n\ndef test_empty():\n    assert mean([]) == 0\n",
        "cause": "mean divides by the length without handling an empty list",
    },
    {
        "name": "dict-merge",
        "buggy": "def merge(base, extra):\n    base.update(extra)\n    return extra\n",
        "fixed": "def merge(base, extra):\n    out = dict(base)\n    out.update(extra)\n    return out\n",
        "test": "from {mod} import merge\n\n\ndef test_keeps_base():\n    assert merge({'a': 1}, {'b': 2}) == {'a': 1, 'b': 2}\n\n\ndef test_no_mutation():\n    base = {'a': 1}\n    merge(base, {'b': 2})\n    assert base == {'a': 1}\n",
        "cause": "merge mutates the base mapping and returns only the extra keys",
    },
    {
        "name": "truncate-suffix",
        "buggy": "def truncate(text, limit):\n    return text[:limit]\n",
        "fixed": "def truncate(text, limit):\n    if len(text) <= limit:\n        return text\n    return text[: max(0, limit - 3)] + '...'\n",
        "test": "from {mod} import truncate\n\n\ndef test_short():\n    assert truncate('abc', 5) == 'abc'\n\n\ndef test_long():\n    assert truncate('abcdefg', 6) == 'abc...'\n",
        "cause": "truncate cuts the text without adding the documented ellipsis",
    },
    {
        "name": "to-bool",
        "buggy": "def to_bool(value):\n    return bool(value)\n",
        "fixed": "def to_bool(value):\n    if isinstance(value, str):\n        return value.strip().lower() in {'1', 'true', 'yes', 'on'}\n    return bool(value)\n",
        "test": "from {mod} import to_bool\n\n\ndef test_true():\n    assert to_bool('true') is True\n\n\ndef test_false():\n    assert to_bool('false') is False\n",
        "cause": "to_bool treats every non-empty string as true, including 'false'",
    },
    {
        "name": "flatten-one-level",
        "buggy": "def flatten(rows):\n    return rows\n",
        "fixed": "def flatten(rows):\n    return [item for row in rows for item in row]\n",
        "test": "from {mod} import flatten\n\n\ndef test_rows():\n    assert flatten([[1, 2], [3]]) == [1, 2, 3]\n",
        "cause": "flatten returns the nested rows instead of one flat list",
    },
    {
        "name": "sum-squares",
        "buggy": "def sum_squares(values):\n    return sum(values) ** 2\n",
        "fixed": "def sum_squares(values):\n    return sum(v * v for v in values)\n",
        "test": "from {mod} import sum_squares\n\n\ndef test_values():\n    assert sum_squares([1, 2, 3]) == 14\n",
        "cause": "sum_squares squares the total instead of each value",
    },
    {
        "name": "percent",
        "buggy": "def percent(part, whole):\n    return part / whole\n",
        "fixed": "def percent(part, whole):\n    if whole == 0:\n        return 0.0\n    return round(100.0 * part / whole, 2)\n",
        "test": "from {mod} import percent\n\n\ndef test_half():\n    assert percent(1, 2) == 50.0\n\n\ndef test_zero():\n    assert percent(1, 0) == 0.0\n",
        "cause": "percent returns a fraction and divides by zero instead of returning 0.0",
    },
    {
        "name": "max-or-default",
        "buggy": "def max_or(values, default):\n    return max(values)\n",
        "fixed": "def max_or(values, default):\n    return max(values) if values else default\n",
        "test": "from {mod} import max_or\n\n\ndef test_values():\n    assert max_or([1, 4], 0) == 4\n\n\ndef test_empty():\n    assert max_or([], 7) == 7\n",
        "cause": "max_or raises on an empty list instead of using the default",
    },
    {
        "name": "round-cents",
        "buggy": "def round_cents(value):\n    return int(value)\n",
        "fixed": "def round_cents(value):\n    return round(value, 2)\n",
        "test": "from {mod} import round_cents\n\n\ndef test_fraction():\n    assert round_cents(1.234) == 1.23\n\n\ndef test_whole():\n    assert round_cents(2.0) == 2.0\n",
        "cause": "round_cents truncates to whole units instead of two decimals",
    },
]


def make_diff(mod: str, buggy: str, fixed: str) -> str:
    diff = "".join(
        difflib.unified_diff(
            buggy.splitlines(keepends=True),
            fixed.splitlines(keepends=True),
            fromfile=f"a/{mod}.py",
            tofile=f"b/{mod}.py",
            n=3,
        )
    )
    return f"diff --git a/{mod}.py b/{mod}.py\n{diff}"


def make_example(template: dict, index: int) -> dict:
    mod = f"mod_{index}"
    buggy = template["buggy"]
    fixed = template["fixed"]
    answer = {
        "root_cause": template["cause"],
        "patch": make_diff(mod, buggy, fixed),
        "commands": [],
    }
    user = (
        f"Repository file {mod}.py:\n```python\n{buggy}```\n\n"
        f"Failing check: python -m pytest -q tests/test_{mod}.py\n"
        f"Test file:\n```python\n{template['test'].replace('{mod}', mod)}```\n"
        f"Return JSON only."
    )
    return {
        "messages": [
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": user},
            {"role": "assistant", "content": json.dumps(answer)},
        ]
    }


def check_template(template: dict) -> str | None:
    """Return a problem string when the bad module does not fail or the fix does not pass."""
    with tempfile.TemporaryDirectory(prefix="doug-a-template-") as tmp:
        root = Path(tmp)
        (root / "tests").mkdir()
        test = template["test"].replace("{mod}", "mod")
        (root / "tests" / "test_mod.py").write_text(test, encoding="utf-8")
        results = {}
        for label, source in (("buggy", template["buggy"]), ("fixed", template["fixed"])):
            (root / "mod.py").write_text(source, encoding="utf-8")
            done = subprocess.run(
                [sys.executable, "-m", "pytest", "-q", "tests/test_mod.py"],
                cwd=root,
                capture_output=True,
                text=True,
            )
            results[label] = done.returncode
        if results["buggy"] == 0:
            return f"{template['name']}: buggy module passes its test"
        if results["fixed"] != 0:
            return f"{template['name']}: fixed module fails its test"
    return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--count", type=int, default=12)
    parser.add_argument("--seed", type=int, default=7)
    args = parser.parse_args(argv)

    problems = [problem for problem in map(check_template, TEMPLATES) if problem]
    if problems:
        for problem in problems:
            print(f"template check failed: {problem}", file=sys.stderr)
        return 1

    rng = random.Random(args.seed)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as fh:
        for i in range(args.count):
            template = TEMPLATES[i % len(TEMPLATES)]
            fh.write(json.dumps(make_example(template, rng.randrange(100_000))) + "\n")
    print(f"wrote {args.count} synthetic incidents to {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
