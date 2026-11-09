from __future__ import annotations

from scripts.eval import load_grader

a_grader = load_grader("doug-a")
l_grader = load_grader("doug-l")


def test_gold_patch_passes_and_bad_patch_fails():
    item = a_grader.list_items()[0]
    gold = a_grader.grade_item(item, a_grader.gold_prediction(item))
    assert gold["fixed"] == 1.0
    assert gold["root_cause_correct"] == 1.0
    assert gold["no_destructive_commands"] == 1.0

    bad = a_grader.grade_item(item, a_grader.bad_prediction(item))
    assert bad["fixed"] == 0.0


def test_destructive_commands_are_flagged():
    item = a_grader.list_items()[0]
    prediction = a_grader.gold_prediction(item)
    prediction["commands"] = ["rm -rf /", "git push origin main"]
    result = a_grader.grade_item(item, prediction)
    assert result["no_destructive_commands"] == 0.0
    assert len(result["destructive_commands"]) == 2


def test_doug_l_gold_and_bad():
    item = l_grader.list_items()[0]
    gold = l_grader.grade_item(item, l_grader.gold_prediction(item))
    assert gold["task_success"] == 1.0
    assert gold["cost_gap_vs_solver"] <= 0.01

    bad = l_grader.grade_item(item, l_grader.bad_prediction(item))
    assert bad["task_success"] == 0.0


def test_doug_l_grader_scores_malformed_model_output_instead_of_crashing():
    import importlib.util
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location(
        "grader_doug_l_malformed", root / "evals" / "doug-l" / "harness" / "grader.py"
    )
    grader = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(grader)
    item = grader.list_items()[0]

    for prediction in (
        {},
        {"extraction": {"order_id": "x"}, "solver_calls": [], "plan": {"vehicle_id": "v"}},
        {"extraction": dict(item["order"]), "plan": {"vehicle_id": item["fleet"][0]["vehicle_id"]}},
    ):
        result = grader.grade_item(item, prediction)
        assert result["task_success"] == 0.0
