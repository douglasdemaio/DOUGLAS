"""Promotion gate. Only this script may promote a challenger to champion.

    python -m scripts.gate --model doug-a --challenger results/<run>
    python -m scripts.gate --model doug-a --challenger results/<run> --dry-run

Exit codes: 0 promoted / would promote, 1 rejected, 2 bad input.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from scripts.common import (
    ROOT,
    append_ledger,
    frozen_sha256,
    load_config,
    load_json,
    recipe_sha256,
    registry_dir,
    utc_now_iso,
    write_json,
)
from scripts.contamination import check as contamination_check
from scripts.sign_receipt import load_private_key, load_private_key_text, sign_payload

DEFAULT_KEY = Path.home() / ".config" / "douglas" / "signing_key"


# --------------------------------------------------------------------------- #
# evaluation
# --------------------------------------------------------------------------- #
def metric_mean(scores: dict, name: str) -> float | None:
    entry = scores.get("metrics", {}).get(name)
    if not entry:
        return None
    return float(entry["mean"])


def metric_std(scores: dict, name: str) -> float:
    entry = scores.get("metrics", {}).get(name)
    if not entry:
        return 0.0
    return float(entry.get("std", 0.0))


def resolve_challenger(path_or_run: str) -> Path:
    path = Path(path_or_run)
    if path.is_file():
        return path
    candidates = [
        ROOT / path_or_run / "scores.json",
        ROOT / "results" / path_or_run / "scores.json",
    ]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    raise FileNotFoundError(f"no scores.json found for challenger {path_or_run!r}")


def champion_path(model: str) -> Path:
    return registry_dir() / f"{model}.champion.scores.json"


def load_champion(model: str) -> dict | None:
    path = champion_path(model)
    if not path.exists():
        return None
    data = load_json(path)
    if not data or data.get("metrics") in (None, {}):
        return None
    return data


def evaluate(
    model: str,
    challenger: dict,
    champion: dict | None,
    config: dict,
    contamination: dict,
) -> tuple[bool, list[str], list[str]]:
    """Return (passed, failures, notes)."""
    failures: list[str] = []
    notes: list[str] = []

    if challenger.get("model") != model:
        failures.append(f"challenger model {challenger.get('model')!r} != {model!r}")

    seeds = challenger.get("seeds") or []
    if len(seeds) < 3:
        failures.append(f"need >=3 seeds, got {len(seeds)}")

    expected_frozen = frozen_sha256(model)
    got_frozen = (challenger.get("hashes") or {}).get("frozen_eval_sha256")
    if got_frozen != expected_frozen:
        failures.append(
            f"frozen eval hash mismatch (challenger {got_frozen}, current {expected_frozen})"
        )

    if not contamination.get("clean"):
        failures.append("contamination check is not clean")

    metrics = config["metrics"]
    primary = metrics["primary"]
    noise_margin = float(metrics["noise_margin"])

    c_mean = metric_mean(challenger, primary)
    if c_mean is None:
        failures.append(f"challenger is missing primary metric {primary!r}")
        return False, failures, notes

    if champion is None:
        floor = float(metrics.get("bootstrap_min_primary", 0.0))
        if c_mean < floor:
            failures.append(f"bootstrap: {primary} {c_mean:.3f} < required {floor:.3f}")
        else:
            notes.append(f"bootstrap promotion: {primary} {c_mean:.3f} >= {floor:.3f}")
    else:
        b_mean = metric_mean(champion, primary)
        if b_mean is None:
            failures.append(f"champion is missing primary metric {primary!r}")
        else:
            c_std = metric_std(challenger, primary)
            b_std = metric_std(champion, primary)
            threshold = max(noise_margin, c_std + b_std)
            delta = c_mean - b_mean
            notes.append(
                f"{primary}: challenger {c_mean:.3f} vs champion {b_mean:.3f} "
                f"(delta {delta:+.3f}, required > {threshold:.3f})"
            )
            if not delta > threshold:
                failures.append(
                    f"{primary} delta {delta:+.3f} is inside the noise margin {threshold:.3f}"
                )

    for name, spec in (metrics.get("guarded") or {}).items():
        direction = spec.get("direction", "higher")
        tolerance = float(spec.get("tolerance", 0.0))
        floor = spec.get("floor")
        c_val = metric_mean(challenger, name)
        if c_val is None:
            failures.append(f"challenger is missing guarded metric {name!r}")
            continue
        if floor is not None and c_val < float(floor):
            failures.append(f"guarded {name} {c_val:.3f} below floor {float(floor):.3f}")
        if champion is None:
            continue
        b_val = metric_mean(champion, name)
        if b_val is None:
            continue
        if direction == "higher" and c_val < b_val - tolerance:
            failures.append(
                f"guarded {name} regressed: {c_val:.3f} < {b_val:.3f} - {tolerance:.3f}"
            )
        if direction == "lower" and c_val > b_val + tolerance:
            failures.append(
                f"guarded {name} regressed: {c_val:.3f} > {b_val:.3f} + {tolerance:.3f}"
            )

    return not failures, failures, notes


# --------------------------------------------------------------------------- #
# promotion
# --------------------------------------------------------------------------- #
def build_payload(model: str, challenger: dict, timestamp: str) -> dict:
    config = load_config(model)
    return {
        "model_id": model,
        "base_revision": config["base"]["revision"],
        "adapter_sha256": challenger.get("hashes", {}).get("adapter_sha256"),
        "recipe_sha256": recipe_sha256(model),
        "frozen_eval_sha256": frozen_sha256(model),
        "scores": challenger.get("metrics", {}),
        "seeds": challenger.get("seeds", []),
        "timestamp": timestamp,
    }


def promote(model: str, challenger: dict, receipt: str, payload: dict) -> None:
    reg = registry_dir()
    reg.mkdir(parents=True, exist_ok=True)

    line = json.dumps({"receipt": receipt, "payload": payload}, sort_keys=True)
    with open(reg / f"{model}.jsonl", "a", encoding="utf-8") as fh:
        fh.write(line + "\n")

    champion = {
        **challenger,
        "ckpt": "champion",
        "promoted_at": payload["timestamp"],
        "receipt": receipt,
    }
    write_json(champion_path(model), champion)

    baseline_file = ROOT / "baseline.json"
    baseline = load_json(baseline_file) if baseline_file.exists() else {"models": {}}
    baseline.setdefault("models", {})[model] = {
        "champion": payload["adapter_sha256"],
        "run": challenger.get("run"),
        "scores": challenger.get("metrics"),
    }
    baseline["updated"] = utc_now_iso()[:10]
    write_json(baseline_file, baseline)

    append_ledger(
        {
            "kind": "promotion",
            "model": model,
            "run": challenger.get("run"),
            "receipt": receipt,
            "scores": challenger.get("metrics"),
        }
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", required=True)
    parser.add_argument("--challenger", required=True)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--key", default=os.environ.get("DOUGLAS_SIGNING_KEY", str(DEFAULT_KEY)))
    args = parser.parse_args(argv)

    challenger = load_json(resolve_challenger(args.challenger))
    champion = load_champion(args.model)
    config = load_config(args.model)
    contam = contamination_check(args.model)

    passed, failures, notes = evaluate(args.model, challenger, champion, config, contam)

    print(f"gate: {args.model} / {challenger.get('run')}")
    for note in notes:
        print(f"  note: {note}")
    print(f"  contamination: {'clean' if contam.get('clean') else 'DIRTY'}")
    if not passed:
        for failure in failures:
            print(f"  FAIL: {failure}")
        print("decision: REJECT")
        return 1

    timestamp = utc_now_iso()
    payload = build_payload(args.model, challenger, timestamp)
    if payload["adapter_sha256"] is None:
        print("  FAIL: challenger has no adapter_sha256")
        print("decision: REJECT")
        return 1

    if args.dry_run:
        print("decision: WOULD PROMOTE (dry run)")
        return 0

    key_path = Path(args.key)
    try:
        private = (
            load_private_key(key_path) if key_path.exists() else load_private_key_text(args.key)
        )
    except (OSError, ValueError) as exc:
        print(f"  FAIL: cannot load signing key: {exc}", file=sys.stderr)
        return 2
    receipt = sign_payload(payload, private)
    promote(args.model, challenger, receipt, payload)
    print("decision: PROMOTED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
