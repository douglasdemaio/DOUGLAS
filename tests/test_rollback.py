from __future__ import annotations

import json

import pytest

from scripts import attestation, rollback
from scripts.common import read_jsonl, write_json
from scripts.sign_receipt import generate_keypair, load_private_key, sign_payload


def _gate_receipt(key, adapter, ts):
    return sign_payload(
        {
            "model_id": "doug-a",
            "adapter_sha256": adapter,
            "frozen_eval_sha256": "c" * 64,
            "seeds": [1, 2, 3],
            "timestamp": ts,
        },
        key,
    )


def _promotion(tmp_path, key_text, key, run, diff, adapter, ts, receipt):
    payload = attestation.build_payload(
        model_id="doug-a",
        run=run,
        diff_sha256=diff,
        diff=f"change {run}",
        per_seed=[{"seed": 1, "fix_rate": 0.9}, {"seed": 2, "fix_rate": 0.8}],
        metrics={"fix_rate": {"mean": 0.85, "std": 0.05}},
        adapter_sha256=adapter,
        gate_decision="PROMOTED",
        gate_receipt=receipt,
        parent_champion=None,
        frozen_eval_sha256="c" * 64,
        promoted_scores={
            "model": "doug-a",
            "run": run,
            "seeds": [1, 2, 3],
            "metrics": {"fix_rate": {"mean": 0.85, "std": 0.05}},
        },
        timestamp=ts,
    )
    decision = attestation.sign_decision(payload, key_text)
    attestation.append_decision(decision, payload, root=tmp_path)
    return decision


def _setup(tmp_path):
    priv = tmp_path / "key"
    pub = tmp_path / "key.pub"
    generate_keypair(priv, pub)
    key_text = priv.read_text().strip()
    key = load_private_key(priv)
    (tmp_path / "registry").mkdir()
    (tmp_path / "experiments").mkdir()
    write_json(tmp_path / "baseline.json", {"models": {}})

    old_receipt = _gate_receipt(key, "old-adapter", "2026-11-01T00:00:00Z")
    new_receipt = _gate_receipt(key, "new-adapter", "2026-11-02T00:00:00Z")
    registry = tmp_path / "registry" / "doug-a.jsonl"
    registry.write_text(
        "".join(
            json.dumps({"receipt": r, "payload": {}}) + "\n" for r in (old_receipt, new_receipt)
        ),
        encoding="utf-8",
    )
    _promotion(tmp_path, key_text, key, "run-old", "a" * 64, "old-adapter",
               "2026-11-01T00:00:01Z", old_receipt)
    _promotion(tmp_path, key_text, key, "run-new", "b" * 64, "new-adapter",
               "2026-11-02T00:00:01Z", new_receipt)
    write_json(
        rollback.champion_path("doug-a", tmp_path),
        {"model": "doug-a", "run": "run-new", "adapter_sha256": "new-adapter",
         "promoted_at": "2026-11-02T00:00:01Z", "receipt": new_receipt},
    )
    return key_text, pub, old_receipt, new_receipt


def test_rollback_restores_previous_signed_champion(tmp_path):
    key_text, pub, old_receipt, new_receipt = _setup(tmp_path)
    receipt, payload = rollback.rollback(
        "doug-a", key_text, root=tmp_path, pub_path=pub, ts="2026-11-03T00:00:00Z"
    )

    champion = json.loads(rollback.champion_path("doug-a", tmp_path).read_text())
    assert champion["run"] == "run-old"
    assert champion["receipt"] == old_receipt
    baseline = json.loads((tmp_path / "baseline.json").read_text())
    assert baseline["models"]["doug-a"]["champion"] == "old-adapter"
    ledger = list(read_jsonl(tmp_path / "experiments" / "ledger.jsonl"))
    assert ledger[-1]["kind"] == "rollback"
    assert ledger[-1]["to"] == old_receipt
    assert attestation.verify_decision(receipt, pub)["kind"] == "rollback"
    events = list(read_jsonl(tmp_path / "reviews" / "events.jsonl"))
    assert events[-1]["kind"] == "rollback"


def test_rollback_refuses_without_an_earlier_verified_promotion(tmp_path):
    priv = tmp_path / "key"
    pub = tmp_path / "key.pub"
    generate_keypair(priv, pub)
    write_json(
        rollback.champion_path("doug-a", tmp_path),
        {"model": "doug-a", "receipt": "unsigned", "promoted_at": "2026-11-02T00:00:01Z"},
    )
    with pytest.raises(rollback.RollbackError):
        rollback.rollback("doug-a", priv.read_text().strip(), root=tmp_path, pub_path=pub)


def test_rollback_refuses_a_tampered_earlier_attestation(tmp_path):
    key_text, pub, old_receipt, new_receipt = _setup(tmp_path)
    path = attestation.decisions_path(tmp_path)
    entries = [json.loads(line) for line in path.read_text().splitlines()]
    header, body, signature = entries[0]["receipt"].split(".")
    entries[0]["receipt"] = f"{header}.{body}.{signature[:-2]}AA"
    path.write_text("".join(json.dumps(e) + "\n" for e in entries))

    with pytest.raises(rollback.RollbackError):
        rollback.rollback("doug-a", key_text, root=tmp_path, pub_path=pub)
