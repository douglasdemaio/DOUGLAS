"""Self-tests for the gatekeeper: known-bad changes and tampered receipts.

These tests exercise the real gate and signing code without modifying either.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from scripts import attestation, common, gate, protect
from scripts import eval as douglas_eval
from scripts.eval import load_grader
from scripts.sign_receipt import generate_keypair, load_private_key, sign_payload

ROOT = Path(__file__).resolve().parents[1]


def _good_scores(model: str, tmp_path: Path) -> Path:
    grader = load_grader(model)
    if model == "doug-a":
        records = [
            {"id": Path(item).name, "output": grader.gold_prediction(item)}
            for item in grader.list_items()
        ]
    else:
        records = [
            {"id": item["id"], "output": grader.gold_prediction(item)}
            for item in grader.list_items()
        ]
    predictions = tmp_path / f"{model}-predictions.jsonl"
    predictions.write_text("".join(json.dumps(r) + "\n" for r in records), encoding="utf-8")
    out = tmp_path / f"{model}-run"
    assert (
        douglas_eval.main(
            [
                "--model",
                model,
                "--ckpt",
                "challenger",
                "--seeds",
                "3",
                "--engine",
                "replay",
                "--predictions",
                str(predictions),
                "--out",
                str(out),
                "--run",
                f"gatekeeper-{model}",
            ]
        )
        == 0
    )
    return out / "scores.json"


def _copy_with(scores_path: Path, name: str, mutate) -> Path:
    scores = json.loads(scores_path.read_text())
    mutate(scores)
    target = scores_path.parent / name
    target.write_text(json.dumps(scores), encoding="utf-8")
    return target


def test_gate_rejects_known_bad_changes(tmp_path):
    good = _good_scores("doug-a", tmp_path)
    assert gate.main(["--model", "doug-a", "--challenger", str(good), "--dry-run"]) == 0

    bad = [
        _copy_with(
            good, "weak.json", lambda s: s["metrics"]["fix_rate"].update(mean=0.01, std=0.0)
        ),
        _copy_with(good, "two-seeds.json", lambda s: s.update(seeds=[1, 2])),
        _copy_with(good, "frozen.json", lambda s: s["hashes"].update(frozen_eval_sha256="0" * 64)),
        _copy_with(
            good,
            "destructive.json",
            lambda s: s["metrics"]["no_destructive_commands"].update(mean=0.5, std=0.0),
        ),
        _copy_with(good, "wrong-model.json", lambda s: s.update(model="doug-l")),
    ]
    for path in bad:
        assert gate.main(["--model", "doug-a", "--challenger", str(path), "--dry-run"]) == 1, (
            path.name
        )


def test_gate_rejects_dirty_contamination(tmp_path, monkeypatch):
    scores = _good_scores("doug-a", tmp_path)
    monkeypatch.setattr(
        gate, "contamination_check", lambda model: {"clean": False, "problems": ["x"]}
    )
    assert gate.main(["--model", "doug-a", "--challenger", str(scores), "--dry-run"]) == 1


def _gate_receipt(key):
    return sign_payload(
        {
            "model_id": "doug-a",
            "adapter_sha256": "a" * 64,
            "frozen_eval_sha256": "b" * 64,
            "seeds": [1, 2, 3],
            "timestamp": "2026-11-18T00:00:00Z",
        },
        key,
    )


def test_tampered_receipts_are_rejected(tmp_path):
    priv = tmp_path / "key"
    pub = tmp_path / "key.pub"
    other_priv = tmp_path / "other"
    other_pub = tmp_path / "other.pub"
    generate_keypair(priv, pub)
    generate_keypair(other_priv, other_pub)
    receipt = _gate_receipt(load_private_key(priv))
    assert attestation.verify_gate_receipt(receipt, pub)["model_id"] == "doug-a"

    header, body, signature = receipt.split(".", 2)
    forged_body = "eyJtb2RlbF9pZCI6ImRvdWctYSIsInNjb3JlIjowLjk5fQ"
    with pytest.raises(ValueError, match="signature"):
        attestation.verify_gate_receipt(f"{header}.{forged_body}.{signature}", pub)
    with pytest.raises(ValueError, match="signature"):
        attestation.verify_gate_receipt(receipt, other_pub)
    with pytest.raises(ValueError):
        attestation.verify_gate_receipt(f"{header}.{body}", pub)
    with pytest.raises(ValueError, match="missing"):
        attestation.verify_gate_receipt(sign_payload({}, load_private_key(priv)), pub)


def test_gatekeeper_paths_are_protected_but_review_code_is_editable():
    for path in (
        "scripts/gate.py",
        "scripts/sign_receipt.py",
        "scripts/protect.py",
        "registry/verification_key.pub",
        "evals/doug-a/frozen/manifest.json",
        "evals/doug-l/frozen/items.jsonl",
        "evals/doug-a/frozen/thresholds.json",
        ".github/workflows/gate.yml",
        ".github/workflows/douglas-improvement.md",
    ):
        assert protect.is_protected(path), path
    for path in ("scripts/review.py", "scripts/rejection.py", "scripts/attestation.py"):
        assert not protect.is_protected(path), path


def test_frozen_suite_has_not_changed():
    for model in ("doug-a", "doug-l"):
        assert common.verify_frozen_manifest(model) == []
    recorded = json.loads(
        (ROOT / "results" / "doug-a-predict-pytest-20261110T065922Z" / "scores.json").read_text()
    )
    assert recorded["hashes"]["frozen_eval_sha256"] == common.frozen_sha256("doug-a")


def test_frozen_modification_is_detected(tmp_path, monkeypatch):
    source = common.frozen_dir("doug-a")
    copied = tmp_path / "frozen"
    shutil.copytree(source, copied)
    (copied / "thresholds.json").write_text('{"changed": true}')
    monkeypatch.setattr(common, "frozen_dir", lambda model: copied)
    assert common.verify_frozen_manifest("doug-a")
