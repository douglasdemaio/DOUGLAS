"""One-command rollback to the previous signed champion.

    make rollback MODEL=doug-a
    python -m scripts.rollback --model doug-a

The restoration source must be a verified decision attestation whose gate
receipt is in the registry. An unsigned or older-than-current record can never
become a champion, and the rollback itself emits a signed attestation.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Any

from scripts import attestation, containment, policy
from scripts.common import ROOT, append_jsonl, load_json, utc_now_iso, write_json

PUBLIC_KEY = ROOT / "registry" / "verification_key.pub"


class RollbackError(RuntimeError):
    """Raised when there is no verifiable previous champion to restore."""


def champion_path(model: str, root: Path = ROOT) -> Path:
    return Path(root) / "registry" / f"{model}.champion.scores.json"


def current_champion(model: str, *, root: Path = ROOT) -> dict[str, Any]:
    path = champion_path(model, root)
    if not path.exists():
        return {}
    data = load_json(path)
    return data if isinstance(data, dict) else {}


def verified_promotions(
    model: str, *, root: Path = ROOT, pub_path: Path = PUBLIC_KEY
) -> list[dict[str, Any]]:
    promotions = []
    for entry in attestation.load_decisions(root=root):
        raw = entry.get("payload") or {}
        if raw.get("kind") != "promotion" or raw.get("model_id") != model:
            continue
        try:
            promotions.append(attestation.verify_decision(entry["receipt"], pub_path))
        except (KeyError, ValueError, OSError):
            continue  # an unverifiable attestation is never a rollback source
    return promotions


def previous_promotion(
    model: str, *, root: Path = ROOT, pub_path: Path = PUBLIC_KEY
) -> dict[str, Any]:
    current = current_champion(model, root=root)
    receipt = current.get("receipt")
    if not receipt:
        raise RollbackError(f"{model}: current champion has no signed receipt")
    promotions = verified_promotions(model, root=root, pub_path=pub_path)

    current_ts = current.get("promoted_at")
    if not current_ts:
        matches = [p for p in promotions if p.get("gate_receipt") == receipt]
        if not matches:
            raise RollbackError(f"{model}: cannot verify the current champion's receipt")
        current_ts = max(p["timestamp"] for p in matches)

    older = [p for p in promotions if p["timestamp"] < current_ts]
    if not older:
        raise RollbackError(f"{model}: no verified earlier champion to roll back to")
    return max(older, key=lambda p: p["timestamp"])


def rollback(
    model: str,
    key_text: str,
    *,
    root: Path = ROOT,
    pub_path: Path = PUBLIC_KEY,
    ts: str | None = None,
) -> tuple[str, dict[str, Any]]:
    stamp = ts or utc_now_iso()
    current = current_champion(model, root=root)
    target = previous_promotion(model, root=root, pub_path=pub_path)
    scores = target.get("promoted_scores")
    if not scores:
        raise RollbackError(f"{model}: attestation for {target['run']} has no scores snapshot")

    paths = [
        champion_path(model, root),
        Path(root) / "baseline.json",
        Path(root) / "experiments" / "ledger.jsonl",
        attestation.decisions_path(root),
        Path(root) / "docs" / "reviews" / "events.jsonl",
    ]
    for path in paths:
        containment.assert_writable(path, root=root)

    restored = {
        **scores,
        "ckpt": "champion",
        "promoted_at": stamp,
        "receipt": target["gate_receipt"],
        "rolled_back_to": target["run"],
    }
    write_json(champion_path(model, root), restored)

    baseline_file = Path(root) / "baseline.json"
    baseline = load_json(baseline_file) if baseline_file.exists() else {"models": {}}
    baseline.setdefault("models", {})[model] = {
        "champion": target["adapter_sha256"],
        "run": target["run"],
        "scores": target["metrics"],
    }
    baseline["updated"] = stamp[:10]
    write_json(baseline_file, baseline)

    append_jsonl(
        Path(root) / "experiments" / "ledger.jsonl",
        {
            "ts": stamp,
            "kind": "rollback",
            "model": model,
            "from": current.get("receipt"),
            "to": target["gate_receipt"],
            "run": target["run"],
        },
    )

    payload = attestation.build_payload(
        kind="rollback",
        model_id=model,
        run=target["run"],
        diff_sha256=target["diff_sha256"],
        diff=f"rollback to {target['run']}",
        per_seed=target["per_seed"],
        metrics=target["metrics"],
        adapter_sha256=target["adapter_sha256"],
        gate_decision="rollback",
        gate_receipt=target["gate_receipt"],
        parent_champion={
            "adapter_sha256": current.get("adapter_sha256"),
            "run": current.get("run"),
            "receipt": current.get("receipt"),
        },
        target_champion={
            "adapter_sha256": target["adapter_sha256"],
            "run": target["run"],
            "receipt": target["gate_receipt"],
        },
        frozen_eval_sha256=target["frozen_eval_sha256"],
        promoted_scores=restored,
        timestamp=stamp,
    )
    receipt = attestation.sign_decision(payload, key_text)
    attestation.append_decision(receipt, payload, root=root)
    policy.record(
        "rollback",
        path=containment.containment_log(root).parent / "events.jsonl",
        ts=stamp,
        model=model,
        diff=target["diff_sha256"],
        **{"from": current.get("receipt"), "to": target["gate_receipt"]},
    )
    return receipt, payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", required=True, choices=["doug-a", "doug-l"])
    args = parser.parse_args(argv)

    key_text = os.environ.get("DOUGLAS_SIGNING_KEY", "")
    if not key_text:
        print("DOUGLAS_SIGNING_KEY is required to sign the rollback receipt", file=sys.stderr)
        return 2
    try:
        receipt, payload = rollback(args.model, key_text)
    except RollbackError as exc:
        print(f"rollback: REFUSED — {exc}", file=sys.stderr)
        return 1
    print(f"rollback: restored {args.model} to {payload['target_champion']['run']}")
    print(f"receipt: {receipt}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
