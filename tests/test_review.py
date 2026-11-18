from __future__ import annotations

import copy
import json
import subprocess
from pathlib import Path

from scripts import attestation, policy, rejection, review
from scripts.common import frozen_sha256, utc_now
from scripts.sign_receipt import generate_keypair, load_private_key_text, sign_payload

ROOT = Path(__file__).resolve().parents[1]


def _scores():
    return {
        "schema_version": 1,
        "run": "bad-run",
        "model": "doug-a",
        "ckpt": "challenger",
        "engine": "replay",
        "seeds": [1, 2, 3],
        "items": 8,
        "timestamp": "2026-11-18T00:00:00Z",
        "metrics": {
            "fix_rate": {"mean": 0.9, "std": 0.01, "values": [0.9, 0.9, 0.9]},
            "no_destructive_commands": {"mean": 1.0, "std": 0.0, "values": [1.0, 1.0, 1.0]},
        },
        "hashes": {
            "frozen_eval_sha256": frozen_sha256("doug-a"),
            "recipe_sha256": "a" * 64,
            "adapter_sha256": "b" * 64,
        },
        "config_base_revision": "c03e6d358207e414f1eca0bb1891e29f1db0e242",
    }


def _setup(tmp_path):
    for name in ("results", "registry"):
        (tmp_path / name).mkdir()
    (tmp_path / "docs" / "reviews").mkdir(parents=True)
    (tmp_path / "docs" / "reviews" / "policy.json").write_text(
        (ROOT / "docs" / "reviews" / "policy.json").read_text()
    )
    for name in ("rejections.jsonl", "events.jsonl", "decisions.jsonl", "containment.jsonl"):
        (tmp_path / "docs" / "reviews" / name).write_text("")

    priv = tmp_path / "signing_key"
    pub = tmp_path / "registry" / "verification_key.pub"
    generate_keypair(priv, pub)
    key_text = priv.read_text().strip()

    diff = tmp_path / "change.diff"
    diff.write_text("--- a/models/doug-a/recipe.yaml\n+++ b/models/doug-a/recipe.yaml\n")
    run_dir = tmp_path / "results" / "bad-run"
    run_dir.mkdir()
    (run_dir / "predictions.jsonl").write_text('{"id": "x", "output": {}}\n')
    scores_path = run_dir / "scores.json"
    scores_path.write_text(json.dumps(_scores()))
    return key_text, pub, str(diff), scores_path


def _ok(cmd):
    return subprocess.CompletedProcess(cmd, 0, "", "")


def _gate_pass(model, scores_path, env, *, cwd, key):
    receipt = sign_payload(
        {
            "model_id": model,
            "adapter_sha256": "b" * 64,
            "frozen_eval_sha256": frozen_sha256(model),
            "seeds": [1, 2, 3],
            "timestamp": "2026-11-18T00:00:00Z",
        },
        load_private_key_text(key),
    )
    with open(cwd / "registry" / f"{model}.jsonl", "a", encoding="utf-8") as fh:
        fh.write(json.dumps({"receipt": receipt, "payload": {}}) + "\n")
    return subprocess.CompletedProcess([], 0, "decision: PROMOTED\n", "")


def _wire(monkeypatch, tmp_path, key, gate_result):
    monkeypatch.setattr(review, "run_command", lambda cmd, env, **kw: _ok(cmd))
    monkeypatch.setattr(
        review, "regrade", lambda model, challenger, pred, out: copy.deepcopy(challenger)
    )

    def gate(model, scores, env, **kw):
        if gate_result == "pass":
            return _gate_pass(model, scores, env, key=key, **kw)
        if gate_result == "reject":
            return subprocess.CompletedProcess(
                [], 1, "  FAIL: fix_rate delta -0.300 is inside the noise margin 0.020\n", ""
            )
        return subprocess.CompletedProcess([], 2, "", "gate crashed")

    monkeypatch.setattr(review, "invoke_gate", gate)


def _reports(tmp_path):
    return list(rejection.load_rejections(root=tmp_path))


def test_review_passes_and_signs_a_decision(tmp_path, monkeypatch):
    key, pub, diff, scores = _setup(tmp_path)
    _wire(monkeypatch, tmp_path, key, "pass")
    code = review.review(
        "doug-a",
        "results/bad-run/scores.json",
        root=tmp_path,
        diff_file=diff,
        predictions=str(scores.parent / "predictions.jsonl"),
        key_text=key,
    )
    assert code == review.PASS
    decisions = list(attestation.load_decisions(root=tmp_path))
    assert len(decisions) == 1
    payload = decisions[0]["payload"]
    assert payload["kind"] == "promotion"
    assert len(payload["per_seed"]) == 3
    assert "recipe.yaml" in payload["diff"]
    assert payload["gate_decision"] == "PROMOTED"
    assert payload["frozen_eval_sha256"] == frozen_sha256("doug-a")
    assert attestation.verify_decision(decisions[0]["receipt"], pub)["run"] == "bad-run"
    assert _reports(tmp_path) == []
    assert (
        list(policy.read_events(tmp_path / "docs" / "reviews" / "events.jsonl"))[0]["kind"] == "run"
    )


def test_review_rejects_a_weak_challenger_with_a_report(tmp_path, monkeypatch):
    key, pub, diff, scores = _setup(tmp_path)
    _wire(monkeypatch, tmp_path, key, "reject")
    code = review.review(
        "doug-a",
        "results/bad-run/scores.json",
        root=tmp_path,
        diff_file=diff,
        predictions=str(scores.parent / "predictions.jsonl"),
        key_text=key,
    )
    assert code == review.REJECT
    assert list(attestation.load_decisions(root=tmp_path)) == []
    reports = _reports(tmp_path)
    assert len(reports) == 1
    assert "fix_rate" in reports[0]["what_failed"][0]["evidence"]
    for section in rejection.SECTIONS:
        assert reports[0][section]
    assert (tmp_path / "docs" / "reviews" / "reports" / f"{reports[0]['id']}.md").exists()


def test_review_rejects_too_few_seeds_before_calling_the_gate(tmp_path, monkeypatch):
    key, pub, diff, scores = _setup(tmp_path)
    _wire(monkeypatch, tmp_path, key, "pass")
    data = json.loads(scores.read_text())
    data["seeds"] = [1, 2]
    scores.write_text(json.dumps(data))
    code = review.review(
        "doug-a",
        "results/bad-run/scores.json",
        root=tmp_path,
        diff_file=diff,
        predictions=str(scores.parent / "predictions.jsonl"),
        key_text=key,
    )
    assert code == review.REJECT
    assert _reports(tmp_path)[0]["what_failed"][0]["check"] == "seed count"
    assert not (tmp_path / "registry" / "doug-a.jsonl").exists()


def test_review_halts_when_the_gate_is_unavailable(tmp_path, monkeypatch):
    key, pub, diff, scores = _setup(tmp_path)
    _wire(monkeypatch, tmp_path, key, "halt")
    code = review.review(
        "doug-a",
        "results/bad-run/scores.json",
        root=tmp_path,
        diff_file=diff,
        predictions=str(scores.parent / "predictions.jsonl"),
        key_text=key,
    )
    assert code == review.HALT
    assert "gate" in _reports(tmp_path)[0]["what_failed"][0]["evidence"]
    assert list(attestation.load_decisions(root=tmp_path)) == []


def test_review_halts_when_predictions_are_missing(tmp_path, monkeypatch):
    key, pub, diff, scores = _setup(tmp_path)
    _wire(monkeypatch, tmp_path, key, "pass")
    (scores.parent / "predictions.jsonl").unlink()
    code = review.review(
        "doug-a", "results/bad-run/scores.json", root=tmp_path, diff_file=diff, key_text=key
    )
    assert code == review.HALT
    assert "re-grade" in _reports(tmp_path)[0]["what_failed"][0]["evidence"]


def test_review_halts_on_frozen_suite_drift(tmp_path, monkeypatch):
    key, pub, diff, scores = _setup(tmp_path)
    _wire(monkeypatch, tmp_path, key, "pass")
    (tmp_path / "docs" / "reviews" / "decisions.jsonl").write_text(
        json.dumps(
            {"receipt": "x", "payload": {"model_id": "doug-a", "frozen_eval_sha256": "0" * 64}}
        )
        + "\n"
    )
    code = review.review(
        "doug-a",
        "results/bad-run/scores.json",
        root=tmp_path,
        diff_file=diff,
        predictions=str(scores.parent / "predictions.jsonl"),
        key_text=key,
    )
    assert code == review.HALT
    assert _reports(tmp_path)[0]["what_failed"][0]["check"] == "frozen suite drift"


def test_review_blocks_resubmission_until_it_addresses_the_report(tmp_path, monkeypatch):
    key, pub, diff, scores = _setup(tmp_path)
    _wire(monkeypatch, tmp_path, key, "reject")
    kwargs = dict(
        root=tmp_path,
        diff_file=diff,
        predictions=str(scores.parent / "predictions.jsonl"),
        key_text=key,
    )
    assert review.review("doug-a", "results/bad-run/scores.json", **kwargs) == review.REJECT
    report_id = _reports(tmp_path)[0]["id"]
    future = (
        (utc_now() + __import__("datetime").timedelta(days=2)).isoformat().replace("+00:00", "Z")
    )

    again = review.review("doug-a", "results/bad-run/scores.json", now=future, **kwargs)
    assert again == review.REJECT
    assert _reports(tmp_path)[-1]["what_failed"][0]["check"] == "review policy"

    addressed = review.review(
        "doug-a", "results/bad-run/scores.json", now=future, addresses=report_id, **kwargs
    )
    assert addressed == review.REJECT  # the gate still rejects; policy no longer does
    assert _reports(tmp_path)[-1]["what_failed"][0]["check"] == "promotion gate"


def test_network_needs_a_recorded_reason(tmp_path, monkeypatch):
    key, pub, diff, scores = _setup(tmp_path)
    _wire(monkeypatch, tmp_path, key, "pass")
    code = review.review(
        "doug-a",
        "results/bad-run/scores.json",
        root=tmp_path,
        diff_file=diff,
        predictions=str(scores.parent / "predictions.jsonl"),
        key_text=key,
        allow_network=True,
    )
    assert code == review.HALT
    assert "network-reason" in _reports(tmp_path)[0]["what_failed"][0]["evidence"]
