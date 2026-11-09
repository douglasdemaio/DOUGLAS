"""Say which trained adapters still need scoring, and fetch finished scores.

    python -m scripts.eval_queue --model doug-a
    python -m scripts.eval_queue --model doug-a --fetch

A finished sft/dpo job is "awaiting predict" until a non-failed predict job was
submitted after it. Finished predict jobs have their Hub artifacts
(predictions.jsonl, scores.json, failures.md) downloaded to results/<run>/ so a
run can re-grade them hermetically with `make eval ENGINE=replay`.
"""

from __future__ import annotations

import argparse
import os
import sys

from scripts.common import ROOT, latest_jobs

TRAIN_STAGES = {"sft", "dpo"}


def _submitted(record: dict) -> str:
    return record.get("submitted_at") or record.get("ts") or ""


def classify(jobs: list[dict]) -> dict:
    trained = [j for j in jobs if j.get("stage") in TRAIN_STAGES and j.get("status") == "done"]
    predicts = [j for j in jobs if j.get("stage") == "predict"]
    active = [j for j in predicts if j.get("status") in {"pending", "running"}]
    scored = [j for j in predicts if j.get("status") == "done" and j.get("run")]

    awaiting = None
    if trained:
        latest = max(trained, key=_submitted)
        covered = [j for j in predicts if j.get("status") != "failed"]
        if not any(_submitted(j) > _submitted(latest) for j in covered):
            awaiting = latest
    return {"awaiting_predict": awaiting, "predict_active": active, "scored": scored}


def fetch(record: dict) -> str | None:
    from huggingface_hub import snapshot_download

    run = record["run"]
    try:
        snapshot_download(
            repo_id=record["adapter_repo"],
            repo_type="model",
            allow_patterns=[f"evals/{run}/*"],
            local_dir=str(ROOT / "_hub"),
            token=os.environ.get("HF_TOKEN"),
        )
    except Exception as exc:  # a missing artifact must not hide the queue
        print(f"  could not fetch {run}: {exc}", file=sys.stderr)
        return None
    src = ROOT / "_hub" / "evals" / run
    dest = ROOT / "results" / run
    if not src.is_dir():
        return None
    dest.mkdir(parents=True, exist_ok=True)
    for path in src.iterdir():
        (dest / path.name).write_bytes(path.read_bytes())
    return str(dest.relative_to(ROOT))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", required=True)
    parser.add_argument("--fetch", action="store_true")
    args = parser.parse_args(argv)

    state = classify(list(latest_jobs(args.model).values()))
    awaiting = state["awaiting_predict"]
    if awaiting:
        print(
            f"{args.model}: AWAITING PREDICT — adapter {awaiting.get('adapter_repo')} "
            f"(job {awaiting.get('job_id')}) is trained but unscored"
        )
    for job in state["predict_active"]:
        print(
            f"{args.model}: predict {job.get('job_id')} is {job.get('status')} ({job.get('run')})"
        )
    for job in state["scored"]:
        where = fetch(job) if args.fetch else None
        print(f"{args.model}: scored run {job['run']}" + (f" -> {where}" if where else ""))
    if not (awaiting or state["predict_active"] or state["scored"]):
        print(f"{args.model}: nothing to score")
    return 0


if __name__ == "__main__":
    sys.exit(main())
