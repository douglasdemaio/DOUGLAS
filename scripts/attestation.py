"""Signed decision attestations for DOUGLAS promotions and rollbacks.

The gate keeps signing its own compact JWS receipt in registry/<id>.jsonl.
This module signs a *separate* receipt carrying the full decision trace:
diff, per-seed results, gate decision, parent champion and timestamp. It is
appended to docs/reviews/decisions.jsonl. Only the key in $DOUGLAS_SIGNING_KEY can
sign; the public key in registry/verification_key.pub verifies both receipts.

    python -m scripts.attestation verify-all
    python -m scripts.attestation verify --receipt <path>
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from scripts.common import ROOT, append_jsonl, read_jsonl, utc_now_iso
from scripts.sign_receipt import (
    load_private_key_text,
    load_public_key,
    sign_payload,
    verify_receipt,
)

DECISIONS = ROOT / "docs" / "reviews" / "decisions.jsonl"
PUBLIC_KEY = ROOT / "registry" / "verification_key.pub"
REQUIRED_FIELDS = (
    "kind",
    "model_id",
    "run",
    "diff_sha256",
    "diff",
    "per_seed",
    "metrics",
    "adapter_sha256",
    "gate_decision",
    "gate_receipt",
    "parent_champion",
    "frozen_eval_sha256",
    "timestamp",
)


def decisions_path(root: Path = ROOT) -> Path:
    return Path(root) / "docs" / "reviews" / "decisions.jsonl"


def build_payload(
    *,
    model_id: str,
    run: str,
    diff_sha256: str,
    diff: str,
    per_seed: list[dict[str, Any]],
    metrics: dict[str, Any],
    adapter_sha256: str,
    gate_decision: str,
    gate_receipt: str | None,
    parent_champion: dict[str, Any] | None,
    frozen_eval_sha256: str,
    promoted_scores: dict[str, Any] | None = None,
    target_champion: dict[str, Any] | None = None,
    addresses: str | None = None,
    kind: str = "promotion",
    timestamp: str | None = None,
) -> dict[str, Any]:
    if kind not in {"promotion", "rollback"}:
        raise ValueError(f"unknown attestation kind {kind!r}")
    if not per_seed or any("seed" not in seed for seed in per_seed):
        raise ValueError("per_seed must be a non-empty list of per-seed results")
    payload = {
        "kind": kind,
        "model_id": model_id,
        "run": run,
        "diff_sha256": diff_sha256,
        "diff": diff,
        "per_seed": per_seed,
        "metrics": metrics,
        "adapter_sha256": adapter_sha256,
        "gate_decision": gate_decision,
        "gate_receipt": gate_receipt,
        "parent_champion": parent_champion,
        "frozen_eval_sha256": frozen_eval_sha256,
        "timestamp": timestamp or utc_now_iso(),
        "promoted_scores": promoted_scores,
        "target_champion": target_champion,
        "addresses": addresses,
    }
    for optional in ("promoted_scores", "target_champion", "addresses"):
        if payload.get(optional) is None:
            payload.pop(optional, None)
    return payload


def sign_decision(payload: dict[str, Any], key_text: str) -> str:
    return sign_payload(payload, load_private_key_text(key_text))


def verify_decision(receipt: str, pub_path: Path = PUBLIC_KEY) -> dict[str, Any]:
    payload = verify_receipt(receipt, load_public_key(pub_path))
    missing = [field for field in REQUIRED_FIELDS if field not in payload]
    if missing:
        raise ValueError(f"decision receipt is missing {missing}")
    return payload


def load_decisions(*, root: Path = ROOT) -> Iterator[dict[str, Any]]:
    yield from read_jsonl(decisions_path(root))


def append_decision(receipt: str, payload: dict[str, Any], *, root: Path = ROOT) -> Path:
    path = decisions_path(root)
    append_jsonl(path, {"receipt": receipt, "payload": payload})
    return path


def verify_gate_receipt(receipt: str, pub_path: Path = PUBLIC_KEY) -> dict[str, Any]:
    payload = verify_receipt(receipt, load_public_key(pub_path))
    for field in ("model_id", "adapter_sha256", "frozen_eval_sha256", "seeds", "timestamp"):
        if field not in payload:
            raise ValueError(f"gate receipt is missing {field!r}")
    return payload


def verify_all(*, root: Path = ROOT, pub_path: Path = PUBLIC_KEY) -> list[str]:
    """Verify every decision and its linked gate receipt. No network access."""
    problems: list[str] = []
    registries: dict[str, set[str]] = {}
    for entry in load_decisions(root=root):
        label = str(entry.get("payload", {}).get("run", "unknown"))
        try:
            payload = verify_decision(entry["receipt"], pub_path)
        except (KeyError, ValueError, OSError) as exc:
            problems.append(f"{label}: decision receipt invalid: {exc}")
            continue

        model = str(payload["model_id"])
        gate_receipt = payload.get("gate_receipt")
        if not gate_receipt:
            continue
        try:
            gate_payload = verify_gate_receipt(gate_receipt, pub_path)
        except (ValueError, OSError) as exc:
            problems.append(f"{label}: gate receipt invalid: {exc}")
            continue
        if gate_payload["model_id"] != model:
            problems.append(f"{label}: gate receipt is for {gate_payload['model_id']}, not {model}")
        if model not in registries:
            path = Path(root) / "registry" / f"{model}.jsonl"
            registries[model] = {
                str(record.get("receipt")) for record in read_jsonl(path) if record.get("receipt")
            }
        if gate_receipt not in registries[model]:
            problems.append(f"{label}: gate receipt is not in registry/{model}.jsonl")
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("verify-all")
    p_verify = sub.add_parser("verify")
    p_verify.add_argument("--receipt", required=True)
    p_verify.add_argument("--pub", default=str(PUBLIC_KEY))
    args = parser.parse_args(argv)

    if args.command == "verify":
        try:
            payload = verify_decision(
                Path(args.receipt).read_text(encoding="utf-8"), Path(args.pub)
            )
        except (OSError, ValueError) as exc:
            print(f"attestation: INVALID — {exc}")
            return 1
        print(f"attestation: OK — {payload['kind']} for {payload['model_id']} / {payload['run']}")
        return 0

    problems = verify_all()
    if problems:
        for problem in problems:
            print(f"  FAIL: {problem}")
        print(f"attestation: INVALID ({len(problems)} problem(s))")
        return 1
    print(f"attestation: OK ({len(list(load_decisions()))} decision(s))")
    return 0


if __name__ == "__main__":
    sys.exit(main())
