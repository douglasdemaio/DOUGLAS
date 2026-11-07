"""Deterministic backstop for AGENTS.md constraints 2 and 6.

Refuses diffs that touch frozen evals, gate/signing code, the verification key,
dependency locks, workflow definitions, or the protected sections of
models/<id>/config.yaml (base pin, budget caps, metric thresholds).

    python -m scripts.protect --base origin/main
"""

from __future__ import annotations

import argparse
import fnmatch
import subprocess
import sys

import yaml

from scripts.common import MODELS, ROOT

PROTECTED_GLOBS = (
    "evals/*/frozen/*",
    "evals/*/frozen/**",
    "scripts/gate.py",
    "scripts/sign_receipt.py",
    "scripts/protect.py",
    "scripts/scope.py",
    "registry/verification_key.pub",
    "requirements.lock",
    "requirements.train.lock",
    ".github/workflows/douglas-improvement.md",
    ".github/workflows/douglas-improvement.lock.yml",
    ".github/workflows/gate.yml",
)

PROTECTED_CONFIG_SECTIONS = ("base", "budget", "metrics")


def is_protected(path: str) -> bool:
    return any(
        fnmatch.fnmatch(path, pattern)
        or (pattern.endswith("/**") and path.startswith(pattern[:-3]))
        for pattern in PROTECTED_GLOBS
    )


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


def _git_show(base: str, path: str) -> str | None:
    result = subprocess.run(
        ["git", "show", f"{base}:{path}"], capture_output=True, text=True, check=False
    )
    return result.stdout if result.returncode == 0 else None


def protected_section_changes(base: str) -> list[str]:
    problems = []
    for model in MODELS:
        path = f"models/{model}/config.yaml"
        old_text = _git_show(base, path)
        if old_text is None:
            continue
        current = (ROOT / path).read_text(encoding="utf-8")
        old = yaml.safe_load(old_text) or {}
        new = yaml.safe_load(current) or {}
        for section in PROTECTED_CONFIG_SECTIONS:
            if old.get(section) != new.get(section):
                problems.append(f"{path}: protected section {section!r} changed")
    return problems


def check(base: str, files: list[str]) -> tuple[bool, list[str]]:
    problems = []
    for path in files:
        if is_protected(path):
            problems.append(f"protected path changed: {path}")
    problems.extend(protected_section_changes(base))
    return (not problems, problems)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", default="origin/main")
    parser.add_argument("--files", nargs="*")
    parser.add_argument("--worktree", action="store_true")
    args = parser.parse_args(argv)

    files = args.files if args.files is not None else changed_files(args.base, args.worktree)
    ok, problems = check(args.base, files)
    print(f"protect: {'OK' if ok else 'REJECT'}")
    for problem in problems:
        print(f"  - {problem}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
