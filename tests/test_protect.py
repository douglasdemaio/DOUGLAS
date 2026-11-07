from __future__ import annotations

from scripts import protect


def test_frozen_eval_is_protected():
    assert protect.is_protected("evals/doug-a/frozen/incidents/dug-a-0001/meta.json")
    assert protect.is_protected("evals/doug-l/frozen/items.jsonl")


def test_gate_and_signing_are_protected():
    assert protect.is_protected("scripts/gate.py")
    assert protect.is_protected("scripts/sign_receipt.py")
    assert protect.is_protected("registry/verification_key.pub")
    assert protect.is_protected("requirements.lock")


def test_recipe_and_harness_are_not_protected():
    assert not protect.is_protected("models/doug-a/recipe.yaml")
    assert not protect.is_protected("evals/doug-a/harness/grader.py")
    assert not protect.is_protected("data/doug-a/seed/sft.jsonl")


def test_check_reports_protected_paths():
    ok, problems = protect.check("HEAD", ["models/doug-a/recipe.yaml"])
    assert ok
    ok, problems = protect.check("HEAD", ["evals/doug-a/frozen/items.jsonl"])
    assert not ok
    assert any("frozen" in p for p in problems)
