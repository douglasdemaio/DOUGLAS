from __future__ import annotations

import json

import pytest

from scripts import eval as evalmod
from scripts import predict_remote


def test_predictions_replay_through_the_eval_loader(tmp_path):
    path = tmp_path / "predictions.jsonl"
    rows = [
        {"id": "dug-a-0001", "output": {"root_cause": "x", "patch": "", "commands": []}},
        {"id": "dug-a-0002", "output": {}, "parse_error": "not json", "raw": "sorry"},
    ]
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")

    predictions = evalmod.load_predictions(str(path))

    assert set(predictions) == {"dug-a-0001", "dug-a-0002"}
    assert predictions["dug-a-0002"] == {}
    predict = evalmod.replay_engine(predictions)
    assert predict({}, "dug-a-0001", 1) == rows[0]["output"]


def test_run_name_rejects_path_traversal():
    assert predict_remote.RUN_RE.match("doug-a-predict-20261109T120000Z")
    assert not predict_remote.RUN_RE.match("../etc/passwd")
    assert not predict_remote.RUN_RE.match("a/b")


@pytest.mark.parametrize("model", ["doug-a", "doug-l"])
def test_max_new_tokens_is_set_for_every_model(model):
    assert predict_remote.MAX_NEW_TOKENS[model] > 0
