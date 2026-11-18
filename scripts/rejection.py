"""Append-only rejection reports for the DOUGLAS review system.

Every rejected change gets a report with four sections: what failed, why it
matters, what would make it acceptable, and a root cause (never a silent
guess). Reports are appended to reviews/rejections.jsonl and written as
human-readable Markdown under reviews/reports/.

    python -m scripts.rejection list [--model doug-a] [--diff <sha256>]
"""

from __future__ import annotations

import argparse
import secrets
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from scripts.common import ROOT, append_jsonl, atomic_write, read_jsonl, utc_now_iso

UNKNOWN_CAUSE = "cause unknown"
SECTIONS = ("what_failed", "why_it_matters", "how_to_make_acceptable", "root_cause")


def rejection_paths(root: Path = ROOT) -> tuple[Path, Path]:
    reviews = Path(root) / "reviews"
    return reviews / "rejections.jsonl", reviews / "reports"


def _dedup(values: list[str]) -> list[str]:
    seen: set[str] = set()
    out = []
    for value in values:
        text = str(value).strip()
        if text and text not in seen:
            seen.add(text)
            out.append(text)
    return out


def build_report(
    *,
    model: str,
    run: str | None,
    diff_sha256: str,
    failures: list[dict[str, Any]],
    root_cause: str | None = None,
    addresses: str | None = None,
    ts: str | None = None,
) -> dict[str, Any]:
    """Build a report from failed checks. Each failure has check, evidence,
    why and fix; an optional root_cause is used only when it is explicit."""
    for failure in failures:
        missing = [key for key in ("check", "evidence", "why", "fix") if not failure.get(key)]
        if missing:
            raise ValueError(f"rejection failure missing {missing}: {failure!r}")

    stamp = ts or utc_now_iso()
    report_id = f"{stamp.replace(':', '').replace('-', '')}-{secrets.token_hex(4)}"
    diagnoses = _dedup([str(f["root_cause"]) for f in failures if f.get("root_cause")])
    if root_cause:
        cause = str(root_cause).strip() or UNKNOWN_CAUSE
    elif len(diagnoses) == 1:
        cause = diagnoses[0]
    else:
        cause = UNKNOWN_CAUSE

    return {
        "schema_version": 1,
        "id": report_id,
        "ts": stamp,
        "model": model,
        "run": run,
        "diff_sha256": diff_sha256,
        "addresses": addresses,
        "what_failed": [{"check": f["check"], "evidence": f["evidence"]} for f in failures],
        "why_it_matters": _dedup([str(f["why"]) for f in failures]),
        "how_to_make_acceptable": _dedup([str(f["fix"]) for f in failures]),
        "root_cause": cause,
    }


def validate_report(report: dict[str, Any]) -> list[str]:
    problems = []
    for section in SECTIONS:
        value = report.get(section)
        if not value or (isinstance(value, str) and not value.strip()):
            problems.append(f"missing section {section!r}")
    if not report.get("diff_sha256"):
        problems.append("missing diff_sha256")
    return problems


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        f"# Rejection {report['id']}",
        "",
        f"- model: `{report.get('model')}`",
        f"- run: `{report.get('run')}`",
        f"- diff sha256: `{report.get('diff_sha256')}`",
        f"- timestamp: `{report.get('ts')}`",
    ]
    if report.get("addresses"):
        lines.append(f"- addresses: `{report['addresses']}`")
    lines += ["", "## What failed", ""]
    for item in report["what_failed"]:
        lines.append(f"- **{item['check']}**: {item['evidence']}")
    lines += ["", "## Why it matters", ""]
    lines += [f"- {item}" for item in report["why_it_matters"]]
    lines += ["", "## What would make it acceptable", ""]
    lines += [f"- {item}" for item in report["how_to_make_acceptable"]]
    lines += ["", "## Root cause", "", str(report["root_cause"]), ""]
    return "\n".join(lines)


def write_report(report: dict[str, Any], *, root: Path = ROOT) -> tuple[str, str]:
    """Append the report to the log and write its Markdown copy. Returns the
    readable path (repo-relative) and the report id. Never rewrites a report."""
    problems = validate_report(report)
    if problems:
        raise ValueError("invalid rejection report: " + "; ".join(problems))
    log, reports_dir = rejection_paths(root)
    append_jsonl(log, report)
    path = reports_dir / f"{report['id']}.md"
    if path.exists():
        raise FileExistsError(f"rejection report already exists: {path}")
    atomic_write(path, render_markdown(report))
    return str(path.relative_to(ROOT)) if path.is_relative_to(ROOT) else str(path), report["id"]


def load_rejections(*, root: Path = ROOT) -> Iterator[dict[str, Any]]:
    log, _ = rejection_paths(root)
    yield from read_jsonl(log)


def find_rejections(diff_sha256: str, *, root: Path = ROOT) -> list[dict[str, Any]]:
    return [r for r in load_rejections(root=root) if r.get("diff_sha256") == diff_sha256]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    p_list = sub.add_parser("list")
    p_list.add_argument("--model")
    p_list.add_argument("--diff")
    args = parser.parse_args(argv)

    for report in load_rejections():
        if args.model and report.get("model") != args.model:
            continue
        if args.diff and report.get("diff_sha256") != args.diff:
            continue
        print(f"{report['id']}  {report.get('model')}  {report.get('run')}")
        print(f"  what failed: {[f['check'] for f in report['what_failed']]}")
        print(f"  root cause: {report['root_cause']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
