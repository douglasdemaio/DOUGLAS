"""Append-only experiment ledger helpers.

python -m scripts.ledger append --file record.json
python -m scripts.ledger list [--model doug-a] [--kind job]
python -m scripts.ledger summary [--limit 20] [--max-bytes 12000]
"""

from __future__ import annotations

import argparse
import json
import sys

from scripts.common import append_ledger, ledger_path, read_jsonl

SUMMARY_FIELDS = (
    "ts",
    "kind",
    "model",
    "concern",
    "hypothesis",
    "stage",
    "status",
    "job_id",
    "run",
    "commit",
    "note",
)
SUMMARY_STRING_CHARS = 160
SUMMARY_CONCERN_CHARS = 2000


def _clip(value: str, limit: int) -> str:
    return value if len(value) <= limit else value[: limit - 1] + "…"


def _project(record: dict) -> dict:
    projected = {}
    for field in SUMMARY_FIELDS:
        value = record.get(field)
        if value is None:
            continue
        if isinstance(value, str):
            value = _clip(value, SUMMARY_STRING_CHARS)
        projected[field] = value
    return projected


def summary(limit: int = 20, max_bytes: int = 12000) -> str:
    """Return a bounded text view of the ledger for agent context."""
    records = list(read_jsonl(ledger_path()))
    concerns: dict[str, set[str]] = {}
    for record in records:
        concern = record.get("concern")
        if concern is None:
            continue
        concerns.setdefault(str(record.get("model", "?")), set()).add(str(concern))

    lines = [f"ledger entries: {len(records)}"]
    for model in sorted(concerns):
        names = ", ".join(sorted(concerns[model]))
        lines.append(f"seen concerns ({model}): {_clip(names, SUMMARY_CONCERN_CHARS)}")
    lines.append(f"recent entries (last {min(limit, len(records))}):")

    used = sum(len(line) + 1 for line in lines)
    for record in records[-limit:]:
        line = json.dumps(
            _project(record), sort_keys=True, separators=(",", ":"), ensure_ascii=False
        )
        if used + len(line) + 1 > max_bytes:
            lines.append("... older recent entries omitted to stay within the context budget")
            break
        lines.append(line)
        used += len(line) + 1
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    p_append = sub.add_parser("append")
    p_append.add_argument("--file", required=True, help="JSON object or '-' for stdin")

    p_list = sub.add_parser("list")
    p_list.add_argument("--model")
    p_list.add_argument("--kind")

    p_summary = sub.add_parser("summary")
    p_summary.add_argument("--limit", type=int, default=20)
    p_summary.add_argument("--max-bytes", type=int, default=12000)

    args = parser.parse_args(argv)

    if args.command == "append":
        if args.file == "-":
            record = json.load(sys.stdin)
        else:
            with open(args.file, encoding="utf-8") as fh:
                record = json.load(fh)
        append_ledger(record)
        return 0

    if args.command == "summary":
        sys.stdout.write(summary(args.limit, args.max_bytes))
        return 0

    for record in read_jsonl(ledger_path()):
        if args.model and record.get("model") != args.model:
            continue
        if args.kind and record.get("kind") != args.kind:
            continue
        print(json.dumps(record, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
