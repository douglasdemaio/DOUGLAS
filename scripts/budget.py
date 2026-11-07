"""GPU-hour budget accounting against models/<id>/config.yaml caps.

python -m scripts.budget --today
python -m scripts.budget --model doug-a --json
python -m scripts.budget --model doug-a --check 4.5   # exit 1 if over cap
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import timedelta

from scripts.common import append_ledger, latest_jobs, load_config, parse_ts, utc_now


def job_hours(record: dict) -> float:
    actual = record.get("gpu_hours")
    if actual is not None:
        return float(actual)
    return float(record.get("gpu_hours_est") or 0.0)


def usage(model: str) -> dict:
    config = load_config(model)
    caps = config["budget"]
    now = utc_now()
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    week_start = day_start - timedelta(days=day_start.weekday())

    per_run = 0.0
    per_day = 0.0
    per_week = 0.0
    for record in latest_jobs(model).values():
        hours = job_hours(record)
        per_run = max(per_run, hours)
        submitted = record.get("submitted_at") or record.get("ts")
        if not submitted:
            continue
        ts = parse_ts(submitted)
        if ts >= day_start:
            per_day += hours
        if ts >= week_start:
            per_week += hours

    return {
        "model": model,
        "caps": {
            "gpu_hours_per_run": float(caps["gpu_hours_per_run"]),
            "gpu_hours_per_day": float(caps["gpu_hours_per_day"]),
            "gpu_hours_per_week": float(caps["gpu_hours_per_week"]),
        },
        "used": {
            "max_run": round(per_run, 3),
            "today": round(per_day, 3),
            "week": round(per_week, 3),
        },
    }


def check(model: str, requested: float) -> tuple[bool, str]:
    info = usage(model)
    caps, used = info["caps"], info["used"]
    problems = []
    if requested > caps["gpu_hours_per_run"]:
        problems.append(f"requested {requested}h > per-run cap {caps['gpu_hours_per_run']}h")
    if used["today"] + requested > caps["gpu_hours_per_day"]:
        problems.append(
            f"today {used['today']}h + {requested}h > daily cap {caps['gpu_hours_per_day']}h"
        )
    if used["week"] + requested > caps["gpu_hours_per_week"]:
        problems.append(
            f"week {used['week']}h + {requested}h > weekly cap {caps['gpu_hours_per_week']}h"
        )
    return (not problems, "; ".join(problems))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model")
    parser.add_argument("--today", action="store_true")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--check", type=float, metavar="GPU_HOURS")
    parser.add_argument("--record-file", help="append a job record from JSON before reporting")
    args = parser.parse_args(argv)

    if args.record_file:
        with open(args.record_file, encoding="utf-8") as fh:
            append_ledger(json.load(fh))

    models = [args.model] if args.model else ["doug-a", "doug-l"]
    results = [usage(m) for m in models]

    if args.check is not None:
        if not args.model:
            parser.error("--check requires --model")
        ok, reason = check(args.model, args.check)
        print(("OK" if ok else "OVER BUDGET") + (f": {reason}" if reason else ""))
        return 0 if ok else 1

    if args.json:
        print(json.dumps(results, indent=2, sort_keys=True))
        return 0

    for info in results:
        caps, used = info["caps"], info["used"]
        print(
            f"{info['model']}: today {used['today']}h / {caps['gpu_hours_per_day']}h, "
            f"week {used['week']}h / {caps['gpu_hours_per_week']}h, "
            f"largest run {used['max_run']}h / {caps['gpu_hours_per_run']}h"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
