from __future__ import annotations

import json

import pytest

from scripts import attestation
from scripts.sign_receipt import generate_keypair, load_private_key, sign_payload


def _payload(**overrides):
    values = {
        "model_id": "doug-a",
        "run": "run-1",
        "diff_sha256": "a" * 64,
        "diff": "--- a/recipe.yaml\n+++ b/recipe.yaml\n",
        "per_seed": [{"seed": 1, "fix_rate": 0.9}, {"seed": 2, "fix_rate": 0.8}],
        "metrics": {"fix_rate": {"mean": 0.85, "std": 0.05}},
        "adapter_sha256": "b" * 64,
        "gate_decision": "PROMOTED",
        "gate_receipt": None,
        "parent_champion": None,
        "frozen_eval_sha256": "c" * 64,
        "timestamp": "2026-11-18T00:00:00Z",
    }
    values.update(overrides)
    return attestation.build_payload(**values)


def test_payload_carries_the_full_decision_trace():
    payload = _payload()
    for field in attestation.REQUIRED_FIELDS:
        assert field in payload
    assert len(payload["per_seed"]) == 2
    assert payload["gate_decision"] == "PROMOTED"


def test_per_seed_results_are_required():
    with pytest.raises(ValueError, match="per_seed"):
        _payload(per_seed=[])


def test_sign_and_verify_decision(tmp_path):
    priv = tmp_path / "key"
    pub = tmp_path / "key.pub"
    generate_keypair(priv, pub)
    payload = _payload()
    receipt = attestation.sign_decision(payload, priv.read_text().strip())
    assert attestation.verify_decision(receipt, pub) == payload


def test_tampered_decision_is_rejected(tmp_path):
    priv = tmp_path / "key"
    pub = tmp_path / "key.pub"
    generate_keypair(priv, pub)
    receipt = attestation.sign_decision(_payload(), priv.read_text().strip())
    header, body, signature = receipt.split(".")
    forged = json.dumps({"kind": "promotion", "model_id": "doug-a"}).encode()
    import base64

    forged_body = base64.urlsafe_b64encode(forged).rstrip(b"=").decode()
    with pytest.raises(ValueError, match="signature"):
        attestation.verify_decision(f"{header}.{forged_body}.{signature}", pub)


def _gate_receipt(key, model="doug-a", adapter="d" * 64):
    return sign_payload(
        {
            "model_id": model,
            "adapter_sha256": adapter,
            "frozen_eval_sha256": "c" * 64,
            "seeds": [1, 2, 3],
            "timestamp": "2026-11-18T00:00:00Z",
        },
        key,
    )


def _setup_registry(tmp_path, key, pub):
    registry = tmp_path / "registry"
    registry.mkdir(exist_ok=True)
    receipt = _gate_receipt(key)
    (registry / "doug-a.jsonl").write_text(
        json.dumps({"receipt": receipt, "payload": {}}) + "\n", encoding="utf-8"
    )
    payload = _payload(gate_receipt=receipt)
    decision = attestation.sign_decision(payload, (tmp_path / "key").read_text().strip())
    attestation.append_decision(decision, payload, root=tmp_path)
    return receipt, decision


def test_verify_all_accepts_verified_registry_link(tmp_path):
    priv = tmp_path / "key"
    pub = tmp_path / "key.pub"
    generate_keypair(priv, pub)
    _setup_registry(tmp_path, load_private_key(priv), pub)
    assert attestation.verify_all(root=tmp_path, pub_path=pub) == []


def test_verify_all_flags_missing_registry_receipt_and_tampering(tmp_path):
    priv = tmp_path / "key"
    pub = tmp_path / "key.pub"
    generate_keypair(priv, pub)
    gate_receipt, decision = _setup_registry(tmp_path, load_private_key(priv), pub)
    problems = attestation.verify_all(root=tmp_path, pub_path=pub)
    assert problems == []

    (tmp_path / "registry" / "doug-a.jsonl").write_text("")
    assert any("not in registry" in p for p in attestation.verify_all(root=tmp_path, pub_path=pub))

    header, body, signature = decision.split(".")
    tampered = f"{header}.{body}.{signature[:-2]}AA"
    path = attestation.decisions_path(tmp_path)
    path.write_text(json.dumps({"receipt": tampered, "payload": {}}) + "\n")
    assert any("invalid" in p for p in attestation.verify_all(root=tmp_path, pub_path=pub))
