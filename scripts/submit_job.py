"""Submit a training job to Hugging Face Jobs, subject to the budget caps.

    python -m scripts.submit_job --model doug-a --stage sft \
        --hypothesis "adding deduped CI-failure examples raises fix_rate"
    python -m scripts.submit_job --model doug-a --dry-run

The job downloads a tarball of this repository at the current commit, installs
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
    utc_now,
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


def repo_slug(repo_url: str) -> str:
    """Return ``owner/name`` for a GitHub clone URL."""
    slug = repo_url.rstrip("/")
    if slug.endswith(".git"):
        slug = slug[:-4]
    parts = slug.split("/")
    if len(parts) < 2:
        raise ValueError(f"cannot parse a repository slug from {repo_url!r}")
    return "/".join(parts[-2:])


def eval_test_runner() -> str:
    """Return the pytest pin from requirements.lock, the developer/CI environment."""
    for line in (ROOT / "requirements.lock").read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.startswith("pytest=="):
            return line
    raise RuntimeError("requirements.lock does not pin pytest")


def build_command(args, model_cfg: dict, adapter_repo: str) -> list[str]:
    repo_url = os.environ.get("DOUGLAS_REPO_URL", DEFAULT_REPO_URL)
    sha = current_sha()
    # The CUDA images ship python3, pip and tar but no git or curl, so fetch a
    # tarball of the pinned commit instead of cloning.
    ref = sha or "refs/heads/main"
    tarball = f"https://codeload.github.com/{repo_slug(repo_url)}/tar.gz/{ref}"
    fetch = (
        "python3 - <<'PY'\n"
        "import urllib.request\n"
        f"urllib.request.urlretrieve({tarball!r}, '/tmp/douglas.tar.gz')\n"
        "PY"
    )
    if args.stage == "predict":
        train_args = (
            f"python3 -m scripts.predict_remote --model {args.model} --adapter {adapter_repo}"
        )
        if getattr(args, "run", None):
            train_args += f" --run {args.run}"
    else:
        train_args = (
            f"python3 -m scripts.train_remote --model {args.model} --stage {args.stage} "
            f"--output-repo {adapter_repo}"
        )
        if args.stage == "dpo":
            train_args += f" --init-adapter {args.init_adapter or adapter_repo}"
        if args.max_steps:
            train_args += f" --max-steps {args.max_steps}"
    install = "python3 -m pip install -q -r requirements.train.lock\n"
    if args.stage == "predict" and args.model == "doug-a":
        # DOUG-A grades a patch by running the frozen pytest checks inside this
        # image. requirements.train.lock is a protected path, so install the
        # runner at the exact developer/CI pin instead of editing that lock.
        install += f"python3 -m pip install -q '{eval_test_runner()}'\n"
    script = (
        "set -euo pipefail\n"
        "mkdir -p /workspace\n"
        f"{fetch}\n"
        "tar -xzf /tmp/douglas.tar.gz -C /workspace --strip-components=1\n"
        "cd /workspace\n"
        f"{install}"
        f"{train_args}\n"
    )
    return ["bash", "-lc", script]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", required=True)
    parser.add_argument("--stage", choices=["sft", "dpo", "predict"], default="sft")
    parser.add_argument("--hypothesis", default="unspecified")
    parser.add_argument("--concern", default="unspecified")
    parser.add_argument("--init-adapter")
    parser.add_argument("--max-steps", type=int)
    parser.add_argument("--run", help="eval run name (predict stage)")
    parser.add_argument("--flavor")
    parser.add_argument("--gpu-hours", type=float)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    if args.stage == "predict" and not args.run:
        args.run = f"{args.model}-predict-{utc_now().strftime('%Y%m%dT%H%M%SZ')}"

    config = load_config(args.model)
    load_recipe(args.model)  # fail early if the recipe is malformed
    caps = config["budget"]
    default_hours = 1.0 if args.stage == "predict" else float(caps["gpu_hours_per_run"])
    requested = args.gpu_hours or default_hours
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
        "timeout": "1h" if args.stage == "predict" else f"{int(caps['gpu_hours_per_run'])}h",
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
    if args.stage == "predict":
        record["run"] = args.run
        record["scores_url"] = f"https://huggingface.co/{adapter_repo}/tree/main/evals/{args.run}"
    append_ledger(record)
    print(job.id)
    return 0


if __name__ == "__main__":
    sys.exit(main())
