"""Deterministic backstop for AGENTS.md constraint 1: one model, one concern.

python -m scripts.scope --base origin/main
python -m scripts.scope --files models/doug-a/recipe.yaml data/doug-a/seed/sft.jsonl
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys

from scripts.common import MODELS

BOOKKEEPING_PREFIXES = (
    "experiments/",
    "results/",
    "docs/",
    "registry/",
)

CONCERN_RULES = (
    (re.compile(r"^models/(?P<model>[^/]+)/config\.yaml$"), "hyperparameters"),
    (re.compile(r"^models/(?P<model>[^/]+)/recipe\.yaml$"), "recipe"),
    (re.compile(r"^data/(?P<model>[^/]+)/"), "data"),
    (re.compile(r"^evals/(?P<model>[^/]+)/harness/"), "harness"),
)

INFRA_PREFIXES = ("scripts/", "tests/", "schemas/", ".github/", "evals/")
INFRA_FILES = {"Makefile", "pyproject.toml", "requirements.lock", "requirements.train.lock"}


def changed_files(base: str, worktree: bool = False) -> list[str]:
    files = subprocess.run(
        ["git", "diff", "--name-only", f"{base}...HEAD"],
        capture_output=True,
        text=True,
        check=False,
    ).stdout.split()
    if worktree or not files:
        status = subprocess.run(
            ["git", "status", "--porcelain"], capture_output=True, text=True, check=False
        ).stdout
        for line in status.splitlines():
            path = line[3:].strip()
            if " -> " in path:
                path = path.split(" -> ", 1)[1]
            if path:
                files.append(path)
    return sorted(set(files))


def classify(files: list[str]) -> tuple[bool, str]:
    """Return (ok, reason) for a list of changed paths."""
    concern_files = [f for f in files if not f.startswith(BOOKKEEPING_PREFIXES)]
    if not concern_files:
        return True, "only bookkeeping paths changed"

    models: set[str] = set()
    concerns: set[str] = set()
    infra: list[str] = []

    for path in concern_files:
        matched = False
        for pattern, concern in CONCERN_RULES:
            m = pattern.match(path)
            if m:
                model = m.group("model")
                if model not in MODELS:
                    return False, f"unknown model directory in {path}"
                models.add(model)
                concerns.add(concern)
                matched = True
                break
        if matched:
            continue
        if path.startswith(INFRA_PREFIXES) or path in INFRA_FILES:
            infra.append(path)
            continue
        return False, f"unclassified change: {path}"

    if len(models) > 1:
        return False, f"changes touch more than one model: {sorted(models)}"
    if len(concerns) > 1:
        return False, f"changes touch more than one concern: {sorted(concerns)}"
    if concerns and infra:
        return False, f"concern change mixed with infra change: {sorted(concerns)} + {infra[:5]}"
    if not concerns and infra:
        return True, "infra-only change"
    if not concerns:
        return True, "no concern change"
    return True, f"single model {sorted(models)[0] if models else '?'} / single concern {concerns}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", default="origin/main")
    parser.add_argument("--files", nargs="*")
    parser.add_argument("--worktree", action="store_true")
    args = parser.parse_args(argv)

    files = args.files if args.files is not None else changed_files(args.base, args.worktree)
    ok, reason = classify(files)
    print(f"scope: {'OK' if ok else 'REJECT'} — {reason}")
    if not ok:
        print("changed files:")
        for path in files:
            print(f"  {path}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
