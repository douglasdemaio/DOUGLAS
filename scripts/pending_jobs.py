"""Show jobs that are still pending or running.

python -m scripts.pending_jobs --model doug-a
python -m scripts.pending_jobs --model doug-a --refresh --json
"""

from __future__ import annotations

import argparse
import json
import os
import sys

from scripts.common import append_ledger, latest_jobs, utc_now_iso

ACTIVE = {"pending", "running"}

STAGE_MAP = {
    "SCHEDULING": "pending",
    "PENDING": "pending",
    "RUNNING": "running",
    "COMPLETED": "done",
    "CANCELED": "failed",
    "CANCELLED": "failed",
    "ERROR": "failed",
    "DELETED": "failed",
    "TIMEOUT": "failed",
}


def refresh(record: dict) -> dict:
    token = os.environ.get("HF_TOKEN") or os.environ.get("HUGGING_FACE_HUB_TOKEN")
    if not token or not record.get("job_id"):
        return record
    total_secs = None
    try:
        from huggingface_hub import inspect_job

        info = inspect_job(job_id=record["job_id"], token=token)
        status = STAGE_MAP.get(str(info.status.stage).upper(), "unknown")
        total_secs = getattr(getattr(info, "durations", None), "total_secs", None)
    except Exception as exc:  # network or auth failure must not hide the job
        record = {**record, "refresh_error": str(exc)}
        return record

    updates: dict = {}
    if status != record.get("status"):
        updates["status"] = status
        updates["finished_at"] = utc_now_iso() if status in {"done", "failed"} else None
    if (
        status in {"done", "failed"}
        and record.get("gpu_hours") is None
        and isinstance(total_secs, (int, float))
    ):
        # Charge what the job actually ran, not the pre-run estimate, so a
        # crash at startup does not consume the whole daily budget.
        updates["gpu_hours"] = round(total_secs / 3600.0, 4)
    if updates:
        record = {**record, **updates}
        append_ledger(record)
    return record


def pending(model: str, do_refresh: bool = False) -> list[dict]:
    jobs = latest_jobs(model)
    records = list(jobs.values())
    if do_refresh:
        records = [refresh(r) for r in records]
    records = [r for r in records if r.get("status") in ACTIVE]
    return sorted(records, key=lambda r: r.get("submitted_at") or r.get("ts") or "")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", required=True)
    parser.add_argument("--refresh", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    records = pending(args.model, args.refresh)
    if args.json:
        print(json.dumps(records, indent=2, sort_keys=True))
        return 0
    if not records:
        print(f"{args.model}: no pending jobs")
        return 0
    for rec in records:
        print(
            f"{rec.get('job_id')}  {rec.get('status')}  {rec.get('submitted_at', '')}  "
            f"{rec.get('hypothesis', '')}"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
