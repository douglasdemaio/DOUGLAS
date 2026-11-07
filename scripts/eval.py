"""Evaluate a checkpoint on a frozen set and write results/<run>/scores.json.

    python -m scripts.eval --model doug-a --ckpt champion --seeds 3
    python -m scripts.eval --model doug-a --ckpt champion --engine replay \
        --predictions results/<run>/predictions.jsonl

Engines:
    replay    read committed/fixture model outputs (CI, hermetic)
    endpoint  call an OpenAI-compatible endpoint at $MODEL_ENDPOINT
    auto      endpoint when $MODEL_ENDPOINT is set, otherwise replay
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import sys
from pathlib import Path

import requests

from scripts.common import (
    ROOT,
    frozen_sha256,
    load_config,
    read_jsonl,
    recipe_sha256,
    sha256_file,
    tree_sha256,
    utc_now,
    utc_now_iso,
    verify_frozen_manifest,
    write_json,
)

RUN_STAMP = utc_now().strftime("%Y-%m-%dT%H%M%SZ")

# Harness keys -> config metric names
METRIC_ALIASES = {
    "doug-a": {
        "fixed": "fix_rate",
        "root_cause_correct": "root_cause_accuracy",
        "false_fix": "false_fix_rate",
    },
    "doug-l": {},
}


# --------------------------------------------------------------------------- #
# harness loading
# --------------------------------------------------------------------------- #
def load_grader(model: str):
    path = ROOT / "evals" / model / "harness" / "grader.py"
    spec = importlib.util.spec_from_file_location(f"grader_{model.replace('-', '_')}", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load harness for {model}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def build_prompt(model: str, item) -> dict:
    if model == "doug-a":
        meta = json.loads((Path(item) / "meta.json").read_text(encoding="utf-8"))
        files = {}
        for path in sorted((Path(item) / "repo").rglob("*")):
            if path.is_file():
                files[path.relative_to(Path(item) / "repo").as_posix()] = path.read_text(
                    encoding="utf-8"
                )
        body = "\n\n".join(f"### {name}\n```\n{text}```" for name, text in files.items())
        user = (
            f"Failing check: {meta['check']}\n\nRepository:\n{body}\n\n"
            "Return JSON only: {root_cause, patch (unified diff), commands}."
        )
        system = (
            "You are DOUG-A. Diagnose the failing check and return a minimal patch. "
            "Never propose destructive commands."
        )
        return {"system": system, "user": user, "id": meta["id"]}

    text = "\n".join(doc["text"] for doc in item["documents"])
    user = (
        "Extract the shipment fields, call plan_route with them, and explain the plan.\n"
        f"Document:\n{text}\nFleet:\n{json.dumps(item['fleet'])}\n"
        'Return JSON only: {extraction, solver_calls:[{tool:"plan_route",args:{}}], plan, explanation}.'
    )
    system = (
        "You are DOUG-L. Extract fields exactly, call the solver, and never perform "
        "optimisation arithmetic yourself."
    )
    return {"system": system, "user": user, "id": item["id"]}


# --------------------------------------------------------------------------- #
# engines
# --------------------------------------------------------------------------- #
def load_predictions(path: str) -> dict[str, dict]:
    predictions = {}
    for record in read_jsonl(path):
        item_id = record.get("id")
        output = record.get("output", record.get("prediction"))
        if item_id and isinstance(output, dict):
            predictions[item_id] = output
    return predictions


def parse_json_content(text: str) -> dict:
    text = text.strip()
    fenced = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if fenced:
        text = fenced.group(1).strip()
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError(f"model did not return a JSON object: {text[:300]!r}")
    return json.loads(text[start : end + 1])


def endpoint_engine(seed: int, model_name: str):
    url = os.environ["MODEL_ENDPOINT"]
    token = os.environ.get("MODEL_ENDPOINT_TOKEN") or os.environ.get("HF_TOKEN")
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    def predict(prompt: dict, _item_id: str, run_seed: int) -> dict:
        body = {
            "model": model_name,
            "messages": [
                {"role": "system", "content": prompt["system"]},
                {"role": "user", "content": prompt["user"]},
            ],
            "temperature": 0,
            "seed": run_seed,
        }
        response = requests.post(url, headers=headers, json=body, timeout=300)
        response.raise_for_status()
        content = response.json()["choices"][0]["message"]["content"]
        return parse_json_content(content)

    return predict


def replay_engine(predictions: dict[str, dict]):
    def predict(_prompt: dict, item_id: str, _seed: int) -> dict:
        if item_id not in predictions:
            raise KeyError(f"no replayed prediction for {item_id}")
        return predictions[item_id]

    return predict


# --------------------------------------------------------------------------- #
# aggregation
# --------------------------------------------------------------------------- #
def mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def stdev(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    avg = mean(values)
    return (sum((v - avg) ** 2 for v in values) / (len(values) - 1)) ** 0.5


def aggregate(per_seed: list[dict[str, list[float]]]) -> dict:
    metric_names = sorted({name for seed in per_seed for name in seed})
    metrics = {}
    for name in metric_names:
        seed_means = [mean(seed[name]) for seed in per_seed if seed.get(name)]
        metrics[name] = {
            "mean": round(mean(seed_means), 4),
            "std": round(stdev(seed_means), 4),
            "values": [round(v, 4) for v in seed_means],
        }
    return metrics


def adapter_sha(args, model: str, predictions_path: str | None) -> str:
    if args.adapter_dir:
        return tree_sha256(args.adapter_dir)
    if args.adapter_sha:
        return args.adapter_sha
    if predictions_path:
        return "replay:" + sha256_file(predictions_path)
    return f"unhashed:{model}:{args.ckpt}"


# --------------------------------------------------------------------------- #
# main
# --------------------------------------------------------------------------- #
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", required=True)
    parser.add_argument("--ckpt", default="champion")
    parser.add_argument("--seeds", type=int, default=3)
    parser.add_argument("--engine", choices=["replay", "endpoint", "auto"], default="auto")
    parser.add_argument("--predictions")
    parser.add_argument("--adapter-dir")
    parser.add_argument("--adapter-sha")
    parser.add_argument("--out")
    parser.add_argument("--run")
    parser.add_argument("--timeout", type=int, default=180)
    args = parser.parse_args(argv)

    problems = verify_frozen_manifest(args.model)
    if problems:
        for problem in problems:
            print(f"frozen manifest: {problem}", file=sys.stderr)
        return 2

    engine_mode = args.engine
    if engine_mode == "auto":
        engine_mode = "endpoint" if os.environ.get("MODEL_ENDPOINT") else "replay"

    grader = load_grader(args.model)
    items = list(grader.list_items()) if args.model == "doug-a" else grader.list_items()
    if not items:
        print("no frozen items", file=sys.stderr)
        return 2

    if engine_mode == "replay":
        if not args.predictions:
            print("--predictions is required for the replay engine", file=sys.stderr)
            return 2
        predict = replay_engine(load_predictions(args.predictions))
    else:
        predict = endpoint_engine(0, args.model)

    seeds = list(range(1, args.seeds + 1))
    per_seed_metrics: list[dict[str, list[float]]] = []
    failures: list[dict] = []

    for seed in seeds:
        collected: dict[str, list[float]] = {}
        for item in items:
            item_id = Path(item).name if args.model == "doug-a" else item["id"]
            prompt = build_prompt(args.model, item)
            prediction = predict(prompt, item_id, seed)
            result = grader.grade_item(item, prediction)
            aliases = METRIC_ALIASES.get(args.model, {})
            for key, value in result.items():
                if isinstance(value, (int, float)) and not isinstance(value, bool):
                    collected.setdefault(aliases.get(key, key), []).append(float(value))
            if args.model == "doug-a":
                if result["fixed"] != 1.0:
                    failures.append({"id": item_id, "seed": seed, **result})
            elif result["task_success"] != 1.0:
                failures.append({"id": item_id, "seed": seed, **result})
        per_seed_metrics.append(collected)

    metrics = aggregate(per_seed_metrics)
    run = args.run or f"{RUN_STAMP}-{args.model}-{args.ckpt}"
    scores = {
        "schema_version": 1,
        "run": run,
        "model": args.model,
        "ckpt": args.ckpt,
        "engine": engine_mode,
        "seeds": seeds,
        "items": len(items),
        "timestamp": utc_now_iso(),
        "metrics": metrics,
        "hashes": {
            "frozen_eval_sha256": frozen_sha256(args.model),
            "recipe_sha256": recipe_sha256(args.model),
            "adapter_sha256": adapter_sha(args, args.model, args.predictions),
        },
        "config_base_revision": load_config(args.model)["base"]["revision"],
    }

    out_dir = Path(args.out) if args.out else ROOT / "results" / run
    out_dir.mkdir(parents=True, exist_ok=True)
    write_json(out_dir / "scores.json", scores)
    write_failures(out_dir / "failures.md", args.model, metrics, failures)

    primary = load_config(args.model)["metrics"]["primary"]
    print(f"run: {run}")
    print(
        f"primary {primary}: {metrics.get(primary, {}).get('mean')} ± "
        f"{metrics.get(primary, {}).get('std')} over {len(seeds)} seeds"
    )
    try:
        shown = out_dir.relative_to(ROOT)
    except ValueError:
        shown = out_dir
    print(f"wrote {shown}/scores.json")
    return 0


def write_failures(path: Path, model: str, metrics: dict, failures: list[dict]) -> None:
    lines = [f"# {model} failure report", "", "## Metrics", ""]
    for name, entry in sorted(metrics.items()):
        lines.append(f"- `{name}`: {entry['mean']} ± {entry['std']} (per seed {entry['values']})")
    lines += ["", f"## Failures ({len(failures)})", ""]
    clusters: dict[str, list[dict]] = {}
    for failure in failures:
        key = failure.get("category") or failure.get("id", "unknown")
        clusters.setdefault(key, []).append(failure)
    for key, rows in sorted(clusters.items()):
        lines.append(f"### {key} ({len(rows)})")
        for row in rows[:10]:
            lines.append(f"- `{row['id']}` seed {row['seed']}")
            if row.get("destructive_commands"):
                lines.append(f"  - destructive: {row['destructive_commands']}")
            if row.get("constraint_problems"):
                lines.append(f"  - constraints: {row['constraint_problems']}")
        lines.append("")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    sys.exit(main())
