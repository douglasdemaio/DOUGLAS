from __future__ import annotations

from scripts.common import MODELS, load_config, load_recipe


def test_configs_are_complete():
    for model in MODELS:
        config = load_config(model)
        assert config["model_id"] == model
        assert len(config["base"]["revision"]) == 40
        assert config["lora"]["r"] > 0
        assert config["budget"]["gpu_hours_per_run"] > 0
        assert config["budget"]["gpu_hours_per_run"] <= config["budget"]["gpu_hours_per_day"]
        assert config["budget"]["gpu_hours_per_day"] <= config["budget"]["gpu_hours_per_week"]
        assert config["metrics"]["noise_margin"] >= 0
        assert config["metrics"]["primary"]
        assert config["metrics"]["guarded"]
        for spec in config["metrics"]["guarded"].values():
            assert spec["direction"] in {"higher", "lower"}


def test_recipes_point_at_existing_data(repo_root):
    for model in MODELS:
        recipe = load_recipe(model)
        paths = [s["path"] for s in recipe["sft"]["sources"]]
        paths += [s["path"] for s in recipe["dpo"]["sources"]]
        for path in paths:
            assert (repo_root / path).exists(), path


def test_doug_a_guards_are_safety_first():
    config = load_config("doug-a")
    guard = config["metrics"]["guarded"]["no_destructive_commands"]
    assert guard["floor"] == 1.0
    assert guard["tolerance"] == 0.0


def test_baseline_covers_both_models(repo_root):
    import json

    baseline = json.loads((repo_root / "baseline.json").read_text())
    assert set(baseline["models"]) == set(MODELS)
