"""Generate synthetic DOUG-A incidents into data/doug-a/synthetic/sft.jsonl.

These are new bugs drawn from templates, not copies of the frozen set. Run:

    python evals/doug-a/harness/inject.py --count 12 --seed 7
"""

from __future__ import annotations

import argparse
import json
import random
import sys
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
        "test": "from mod import first\n\n\ndef test_non_empty():\n    assert first([5]) == 5\n\n\ndef test_empty():\n    assert first([]) is None\n",
        "cause": "first indexes an empty sequence without a guard",
    },
    {
        "name": "string-to-int",
        "buggy": "def total(values):\n    return sum(values)\n",
        "fixed": "def total(values):\n    return sum(int(v) for v in values)\n",
        "test": "from mod import total\n\n\ndef test_ints():\n    assert total([1, 2]) == 3\n\n\ndef test_strings():\n    assert total(['1', '2']) == 3\n",
        "cause": "total assumes integers but receives numeric strings",
    },
    {
        "name": "case-sensitive-compare",
        "buggy": "def same(a, b):\n    return a == b\n",
        "fixed": "def same(a, b):\n    return a.lower() == b.lower()\n",
        "test": "from mod import same\n\n\ndef test_exact():\n    assert same('abc', 'abc')\n\n\ndef test_case():\n    assert same('ABC', 'abc')\n",
        "cause": "same compares case-sensitively instead of normalising case",
    },
    {
        "name": "missing-dict-key",
        "buggy": "def get_name(user):\n    return user['display_name']\n",
        "fixed": "def get_name(user):\n    return user.get('display_name') or user.get('name', '')\n",
        "test": "from mod import get_name\n\n\ndef test_display():\n    assert get_name({'display_name': 'Ada'}) == 'Ada'\n\n\ndef test_fallback():\n    assert get_name({'name': 'Ada'}) == 'Ada'\n",
        "cause": "get_name assumes display_name always exists",
    },
]


def make_example(template: dict, index: int) -> dict:
    mod = f"mod_{index}"
    buggy = template["buggy"]
    fixed = template["fixed"]
    diff = (
        f"diff --git a/{mod}.py b/{mod}.py\n"
        f"--- a/{mod}.py\n"
        f"+++ b/{mod}.py\n"
        f"@@ -1,2 +1,{len(fixed.strip().splitlines())} @@\n"
        + "".join(f"-{line}\n" for line in buggy.splitlines())
        + "".join(f"+{line}\n" for line in fixed.splitlines())
    )
    answer = {
        "root_cause": template["cause"],
        "patch": diff,
        "commands": [],
    }
    user = (
        f"Repository file {mod}.py:\n```python\n{buggy}```\n\n"
        f"Failing check: python -m pytest -q tests/test_{mod}.py\n"
        f"Test file:\n```python\n{template['test']}```\n"
        f"Return JSON only."
    )
    return {
        "messages": [
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": user},
            {"role": "assistant", "content": json.dumps(answer)},
        ]
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--count", type=int, default=12)
    parser.add_argument("--seed", type=int, default=7)
    args = parser.parse_args(argv)

    rng = random.Random(args.seed)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as fh:
        for i in range(args.count):
            template = TEMPLATES[i % len(TEMPLATES)]
            fh.write(json.dumps(make_example(template, rng.randrange(10_000))) + "\n")
    print(f"wrote {args.count} synthetic incidents to {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
