"""Print a single job's refreshed status.

python -m scripts.job_status --job 687f911eaea852de79c4a50a
"""

from __future__ import annotations

import argparse
import json
import sys

from scripts.common import latest_jobs
from scripts.pending_jobs import refresh


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--job", required=True)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    record = None
    for model in ("doug-a", "doug-l"):
        record = latest_jobs(model).get(args.job)
        if record:
            break
    if not record:
        print(f"unknown job {args.job}", file=sys.stderr)
        return 2

    record = refresh(record)
    if args.json:
        print(json.dumps(record, indent=2, sort_keys=True))
        return 0
    print(f"{record['job_id']}: {record.get('status')}")
    print(json.dumps(record, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
