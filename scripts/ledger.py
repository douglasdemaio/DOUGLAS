"""Append-only experiment ledger helpers.

python -m scripts.ledger append --file record.json
python -m scripts.ledger list [--model doug-a] [--kind job]
"""

from __future__ import annotations

import argparse
import json
import sys

from scripts.common import append_ledger, ledger_path, read_jsonl


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    p_append = sub.add_parser("append")
    p_append.add_argument("--file", required=True, help="JSON object or '-' for stdin")

    p_list = sub.add_parser("list")
    p_list.add_argument("--model")
    p_list.add_argument("--kind")

    args = parser.parse_args(argv)

    if args.command == "append":
        if args.file == "-":
            record = json.load(sys.stdin)
        else:
            with open(args.file, encoding="utf-8") as fh:
                record = json.load(fh)
        append_ledger(record)
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
