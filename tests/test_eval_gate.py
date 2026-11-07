from __future__ import annotations

import json
from pathlib import Path

import jsonschema

from scripts import eval as douglas_eval
from scripts import gate
from scripts.eval import load_grader

ROOT = Path(__file__).resolve().parents[1]


def _write_predictions(model: str, path: Path) -> None:
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
    path.write_text("".join(json.dumps(r) + "\n" for r in records), encoding="utf-8")


def _evaluate(model: str, tmp_path: Path) -> Path:
    predictions = tmp_path / f"{model}-predictions.jsonl"
    _write_predictions(model, predictions)
    out = tmp_path / f"{model}-run"
    code = douglas_eval.main(
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
            f"test-{model}",
        ]
    )
    assert code == 0
    return out / "scores.json"


def test_eval_replay_writes_valid_scores(tmp_path):
    schema = json.loads((ROOT / "schemas" / "scores.schema.json").read_text())
    for model, primary in (("doug-a", "fix_rate"), ("doug-l", "task_success")):
        scores_path = _evaluate(model, tmp_path)
        scores = json.loads(scores_path.read_text())
        jsonschema.validate(scores, schema)
        assert scores["metrics"][primary]["mean"] == 1.0
        assert scores["metrics"][primary]["std"] == 0.0
        assert len(scores["seeds"]) == 3
        assert (scores_path.parent / "failures.md").exists()


def test_gate_accepts_bootstrap_and_rejects_weak_challenger(tmp_path):
    scores_path = _evaluate("doug-a", tmp_path)

    assert gate.main(["--model", "doug-a", "--challenger", str(scores_path), "--dry-run"]) == 0

    scores = json.loads(scores_path.read_text())
    scores["metrics"]["fix_rate"]["mean"] = 0.01
    scores["metrics"]["fix_rate"]["std"] = 0.0
    weak = tmp_path / "weak-scores.json"
    weak.write_text(json.dumps(scores))
    assert gate.main(["--model", "doug-a", "--challenger", str(weak), "--dry-run"]) == 1


def test_gate_rejects_too_few_seeds(tmp_path):
    scores_path = _evaluate("doug-a", tmp_path)
    scores = json.loads(scores_path.read_text())
    scores["seeds"] = [1, 2]
    tampered = tmp_path / "two-seeds.json"
    tampered.write_text(json.dumps(scores))
    assert gate.main(["--model", "doug-a", "--challenger", str(tampered), "--dry-run"]) == 1
