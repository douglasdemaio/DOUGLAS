"""Score an H3-DO baseline and write results/<run>/scores.json.

    python -m evals.h3do.tools.baseline --seeds 3
    python -m evals.h3do.tools.baseline --engine endpoint \
        --endpoint-url "https://example.hf.space/predict" --seeds 3

The replay engine is offline and uses the committed numeric fixture. The
optional endpoint engine posts only manifest metadata and a seed; the response
must follow the prediction contract documented in evals/h3do/README.md. Use
`--require-token` for the backend-secret path; the token is read from
`H3DO_ENDPOINT_TOKEN` or `HF_TOKEN`, is never printed, and is not stored in the
run directory. Endpoints that report `capability.backend_configured: false`
fail closed instead of writing a misleading zero-score run.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.request
from collections import defaultdict
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from scripts.common import (
    ROOT,
    canonical_json,
    load_json,
    load_yaml,
    read_jsonl,
    sha256_file,
    utc_now,
    utc_now_iso,
    write_json,
)

from . import report
from .quality_metrics import score_item

DEFAULT_MANIFEST = ROOT / "evals" / "h3do" / "research" / "eval_manifest.json"
DEFAULT_PREDICTIONS = ROOT / "evals" / "h3do" / "research" / "synthetic_predictions.jsonl"
DEFAULT_CONFIG = ROOT / "evals" / "h3do" / "config.yaml"
RUN_STAMP = utc_now().strftime("%Y-%m-%dT%H%M%SZ")


def validate_manifest(
    manifest: Mapping[str, Any], prompts: list[dict], seeds: list[int]
) -> list[str]:
    problems: list[str] = []
    if manifest.get("schema_version") != 1:
        problems.append("manifest schema_version must be 1")
    if manifest.get("track") != "h3do":
        problems.append("manifest track must be h3do")
    items = manifest.get("items")
    if not isinstance(items, list) or not items:
        problems.append("manifest has no items")
        return problems

    prompt_ids = {prompt.get("id") for prompt in prompts}
    seen_items: set[str] = set()
    for item in items:
        if not isinstance(item, Mapping) or not item.get("id") or not item.get("prompt_id"):
            problems.append("each item needs an id and prompt_id")
            continue
        if item["id"] in seen_items:
            problems.append(f"duplicate item id: {item['id']}")
        seen_items.add(item["id"])
        if item["prompt_id"] not in prompt_ids:
            problems.append(f"missing prompt {item['prompt_id']} for item {item['id']}")

    if len(seeds) < 3:
        problems.append("at least 3 seeds are required")
    required = manifest.get("seeds_required", 3)
    if len(seeds) < required:
        problems.append(f"manifest requires {required} seeds")
    return problems


def load_predictions(path: Path) -> dict[tuple[str, int], dict]:
    index: dict[tuple[str, int], dict] = {}
    for record in read_jsonl(path):
        try:
            key = (str(record["id"]), int(record["seed"]))
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"{path}: prediction missing valid id/seed: {exc}") from exc
        if key in index:
            raise ValueError(f"{path}: duplicate prediction for {key}")
        index[key] = record
    return index


def replay_engine(index: dict[tuple[str, int], dict]) -> Callable[[dict, int], dict]:
    def predict(item: dict, seed: int) -> dict:
        key = (item["id"], seed)
        if key not in index:
            raise ValueError(f"no replayed prediction for {key}")
        return index[key]

    return predict


def endpoint_target(url: str) -> str:
    """Return a log-safe https endpoint URL, rejecting embedded credentials."""
    parsed = urlsplit(url)
    if parsed.scheme != "https" or not parsed.hostname:
        raise ValueError("endpoint URL must be an absolute https URL")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("endpoint URL must not contain credentials, query, or fragment")
    return f"{parsed.scheme}://{parsed.netloc}{parsed.path or '/'}"


def endpoint_token() -> tuple[str | None, str | None]:
    """Read the endpoint token without ever returning it to logs or results."""
    for name in ("H3DO_ENDPOINT_TOKEN", "HF_TOKEN"):
        value = os.environ.get(name)
        if value and value.strip():
            return value.strip(), name
    return None, None


def endpoint_engine(
    url: str,
    manifest: Mapping[str, Any],
    timeout: int,
    token: str | None = None,
) -> Callable[[dict, int], dict]:
    target = endpoint_target(url)

    def predict(item: dict, seed: int) -> dict:
        body = {
            "id": item["id"],
            "prompt_id": item["prompt_id"],
            "seed": seed,
            "task": item.get("task", manifest.get("variant")),
            "duration_seconds": item.get("duration_seconds", manifest.get("duration_seconds")),
            "resolution": manifest.get("resolution"),
        }
        headers = {"Content-Type": "application/json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        request = urllib.request.Request(
            target,
            data=canonical_json(body),
            headers=headers,
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
        if not isinstance(payload, dict):
            raise ValueError(f"endpoint returned non-object prediction for {item['id']}")
        capability = payload.get("capability")
        if isinstance(capability, Mapping) and capability.get("backend_configured") is False:
            reason = capability.get("reason") or "endpoint backend is not configured"
            raise ValueError(f"endpoint backend not configured for {item['id']}: {reason}")
        return payload

    return predict


def failure_reason(
    result: Mapping[str, float], prediction: Mapping[str, Any], artifact_tolerance: float
) -> str:
    reasons = []
    if result.get("format_valid") != 1.0:
        reasons.append("invalid prediction format")
    if result.get("artifact_rate", 1.0) > artifact_tolerance:
        reasons.append("artifact rate too high")
    if result.get("audio_video_sync") != 1.0:
        reasons.append("audio/video sync invalid")
    if result.get("timings_valid") != 1.0:
        reasons.append("invalid timings")
    if prediction.get("errors"):
        reasons.append("engine errors")
    return ", ".join(reasons) or "success_rate != 1"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", default=str(DEFAULT_MANIFEST))
    parser.add_argument("--config", default=str(DEFAULT_CONFIG))
    parser.add_argument("--predictions", default=str(DEFAULT_PREDICTIONS))
    parser.add_argument("--seeds", type=int, default=3)
    parser.add_argument("--engine", choices=["replay", "endpoint"], default="replay")
    parser.add_argument("--endpoint-url")
    parser.add_argument(
        "--require-token",
        action="store_true",
        help="fail closed when no H3DO_ENDPOINT_TOKEN or HF_TOKEN is set",
    )
    parser.add_argument("--timeout", type=int, default=180)
    parser.add_argument("--out")
    parser.add_argument("--run")
    args = parser.parse_args(argv)

    manifest_path = Path(args.manifest).expanduser()
    config_path = Path(args.config).expanduser()
    predictions_path = Path(args.predictions).expanduser()

    try:
        manifest = load_json(manifest_path)
        config = load_yaml(config_path)
        prompts = list(read_jsonl(manifest_path.parent / "prompts.jsonl"))
        seeds = list(range(1, args.seeds + 1))
        problems = validate_manifest(manifest, prompts, seeds)
        if problems:
            for problem in problems:
                print(f"manifest: {problem}", file=sys.stderr)
            return 2

        endpoint_info: dict[str, Any] | None = None
        token: str | None = None
        auth_source: str | None = None
        if args.engine == "endpoint":
            if not args.endpoint_url:
                print("--endpoint-url is required for the endpoint engine", file=sys.stderr)
                return 2
            target = endpoint_target(args.endpoint_url)
            token, auth_source = endpoint_token()
            if args.require_token and not token:
                print(
                    "--require-token needs H3DO_ENDPOINT_TOKEN or HF_TOKEN",
                    file=sys.stderr,
                )
                return 2
            endpoint_info = {
                "url": target,
                "auth_source": auth_source,
                "require_token": args.require_token,
            }

        items = manifest["items"]
        if args.engine == "replay":
            predict = replay_engine(load_predictions(predictions_path))
            predictions_hash = sha256_file(predictions_path)
        else:
            predict = endpoint_engine(target, manifest, args.timeout, token)
            predictions_hash = "endpoint"

        per_seed: list[dict[str, list[float]]] = []
        failures: list[dict[str, Any]] = []
        for seed in seeds:
            collected: dict[str, list[float]] = defaultdict(list)
            for item in items:
                prediction = predict(item, seed)
                result = score_item(prediction, item, manifest)
                for name, value in result.items():
                    if isinstance(value, (int, float)) and not isinstance(value, bool):
                        collected[name].append(float(value))
                if result["success_rate"] != 1.0:
                    failures.append(
                        {
                            "id": item["id"],
                            "seed": seed,
                            "reason": failure_reason(
                                result, prediction, float(manifest.get("artifact_tolerance", 0.05))
                            ),
                        }
                    )
            per_seed.append(dict(collected))

        metrics = report.aggregate(per_seed)
        run = args.run or f"{RUN_STAMP}-h3do-baseline"
        out_dir = Path(args.out).expanduser() if args.out else ROOT / "results" / run
        scores = {
            "schema_version": 1,
            "run": run,
            "track": "h3do",
            "model": "minimax-h3",
            "variant": manifest.get("variant"),
            "engine": args.engine,
            "seeds": seeds,
            "items": len(items),
            "timestamp": utc_now_iso(),
            "metrics": metrics,
            "hashes": {
                "manifest_sha256": sha256_file(manifest_path),
                "config_sha256": sha256_file(config_path),
                "predictions_sha256": predictions_hash,
            },
            "config_base_revision": config["base"]["revision"],
            "failure_count": len(failures),
        }
        if endpoint_info is not None:
            scores["endpoint"] = endpoint_info

        out_dir.mkdir(parents=True, exist_ok=True)
        write_json(out_dir / "scores.json", scores)
        report.write_markdown(out_dir / "report.md", scores, failures)
    except (OSError, ValueError, KeyError) as exc:
        print(f"h3do baseline: {exc}", file=sys.stderr)
        return 2

    print(f"run: {run}")
    for name in (
        "success_rate",
        "prompt_alignment",
        "artifact_rate",
        "output_seconds_per_gpu_second",
    ):
        entry = metrics.get(name, {})
        print(f"{name}: {entry.get('mean')} ± {entry.get('std')}")
    try:
        shown = out_dir.relative_to(ROOT)
    except ValueError:
        shown = out_dir
    print(f"wrote {shown}/scores.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
