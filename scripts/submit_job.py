"""Submit a training job to Hugging Face Jobs, subject to the budget caps.

    python -m scripts.submit_job --model doug-a --stage sft \
        --hypothesis "adding deduped CI-failure examples raises fix_rate"
    python -m scripts.submit_job --model doug-a --dry-run

The job clones this repository at the current commit, installs
requirements.train.lock, runs scripts.train_remote, and pushes the adapter to
the Hub. This command never blocks and never runs the model locally.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys

from scripts.budget import check as budget_check
from scripts.budget import usage
from scripts.common import (
    ROOT,
    append_ledger,
    load_config,
    load_recipe,
    recipe_sha256,
    utc_now_iso,
)

DEFAULT_IMAGE = "pytorch/pytorch:2.6.0-cuda12.4-cudnn9-devel"
DEFAULT_REPO_URL = "https://github.com/douglasdemaio/DOUGLAS.git"


def current_sha() -> str | None:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=False
    )
    return result.stdout.strip() if result.returncode == 0 else None


def namespace() -> str:
    explicit = os.environ.get("HF_NAMESPACE")
    if explicit:
        return explicit
    token = os.environ.get("HF_TOKEN")
    if not token:
        return "your-namespace"
    try:
        from huggingface_hub import whoami

        return whoami(token=token)["name"]
    except Exception:
        return "your-namespace"


def build_command(args, model_cfg: dict, adapter_repo: str) -> list[str]:
    repo_url = os.environ.get("DOUGLAS_REPO_URL", DEFAULT_REPO_URL)
    sha = current_sha()
    checkout = f"git fetch --depth 1 origin {sha} && git checkout --detach {sha}" if sha else "true"
    remote = f"cd /workspace && {checkout} && pip install -q -r requirements.train.lock"
    train_args = (
        f"python -m scripts.train_remote --model {args.model} --stage {args.stage} "
        f"--output-repo {adapter_repo}"
    )
    if args.stage == "dpo":
        train_args += f" --init-adapter {args.init_adapter or adapter_repo}"
    if args.max_steps:
        train_args += f" --max-steps {args.max_steps}"
    script = (
        f"set -euo pipefail\ngit clone --depth 1 {repo_url} /workspace\n{remote}\n{train_args}\n"
    )
    return ["bash", "-lc", script]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", required=True)
    parser.add_argument("--stage", choices=["sft", "dpo"], default="sft")
    parser.add_argument("--hypothesis", default="unspecified")
    parser.add_argument("--concern", default="unspecified")
    parser.add_argument("--init-adapter")
    parser.add_argument("--max-steps", type=int)
    parser.add_argument("--flavor")
    parser.add_argument("--gpu-hours", type=float)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    config = load_config(args.model)
    load_recipe(args.model)  # fail early if the recipe is malformed
    caps = config["budget"]
    requested = args.gpu_hours or float(caps["gpu_hours_per_run"])
    flavor = args.flavor or caps["flavor"]

    ok, reason = budget_check(args.model, requested)
    if not ok:
        print(f"budget: REFUSED — {reason}", file=sys.stderr)
        print(json.dumps(usage(args.model), indent=2, sort_keys=True), file=sys.stderr)
        return 1

    adapter_repo = f"{namespace()}/douglas-{args.model}"
    command = build_command(args, config, adapter_repo)
    spec = {
        "image": DEFAULT_IMAGE,
        "command": command,
        "flavor": flavor,
        "timeout": f"{int(caps['gpu_hours_per_run'])}h",
        "labels": {"douglas-model": args.model, "douglas-stage": args.stage},
        "secrets": ["HF_TOKEN"],
    }

    if args.dry_run:
        print(json.dumps(spec, indent=2, sort_keys=True))
        return 0

    token = os.environ.get("HF_TOKEN")
    if not token:
        print("HF_TOKEN is required to submit a job", file=sys.stderr)
        return 2
    if not current_sha():
        print("commit the repository before submitting a job", file=sys.stderr)
        return 2

    from huggingface_hub import run_job

    job = run_job(
        image=spec["image"],
        command=spec["command"],
        flavor=flavor,
        timeout=spec["timeout"],
        labels=spec["labels"],
        secrets={"HF_TOKEN": token},
    )

    record = {
        "kind": "job",
        "model": args.model,
        "stage": args.stage,
        "job_id": job.id,
        "job_url": getattr(job, "url", None),
        "status": "pending",
        "submitted_at": utc_now_iso(),
        "gpu_hours_est": requested,
        "flavor": flavor,
        "hypothesis": args.hypothesis,
        "concern": args.concern,
        "recipe_sha256": recipe_sha256(args.model),
        "commit": current_sha(),
        "adapter_repo": adapter_repo,
    }
    append_ledger(record)
    print(job.id)
    return 0


if __name__ == "__main__":
    sys.exit(main())
