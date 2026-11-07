from __future__ import annotations

from scripts import scope


def test_bookkeeping_only_is_ok():
    ok, reason = scope.classify(
        ["experiments/ledger.jsonl", "results/run-1/scores.json", "docs/reports/x.md"]
    )
    assert ok, reason


def test_single_model_single_concern_is_ok():
    ok, reason = scope.classify(["models/doug-a/recipe.yaml", "experiments/ledger.jsonl"])
    assert ok, reason


def test_two_models_rejected():
    ok, reason = scope.classify(["models/doug-a/recipe.yaml", "models/doug-l/recipe.yaml"])
    assert not ok
    assert "more than one model" in reason


def test_two_concerns_rejected():
    ok, reason = scope.classify(["models/doug-a/recipe.yaml", "data/doug-a/seed/sft.jsonl"])
    assert not ok
    assert "more than one concern" in reason


def test_infra_only_is_ok():
    ok, reason = scope.classify(["scripts/eval.py", "tests/test_eval.py"])
    assert ok, reason


def test_concern_mixed_with_infra_rejected():
    ok, reason = scope.classify(["models/doug-a/recipe.yaml", "scripts/eval.py"])
    assert not ok
    assert "mixed" in reason


def test_unknown_path_rejected():
    ok, reason = scope.classify(["random/notes.txt"])
    assert not ok
