from __future__ import annotations

import sys
from argparse import Namespace
from types import SimpleNamespace

from scripts import submit_job


def _args(**kwargs):
    base = {"model": "doug-a", "stage": "sft", "init_adapter": None, "max_steps": None}
    base.update(kwargs)
    return Namespace(**base)


def test_build_command_fetches_pinned_tarball_without_git(monkeypatch):
    monkeypatch.setattr(submit_job, "current_sha", lambda: "abc123")
    script = submit_job.build_command(_args(), {}, "me/douglas-doug-a")[2]

    assert "codeload.github.com/douglasdemaio/DOUGLAS/tar.gz/abc123" in script
    assert "git " not in script
    assert "python3 -m scripts.train_remote --model doug-a --stage sft" in script
    assert "--output-repo me/douglas-doug-a" in script


def test_build_command_passes_dpo_adapter(monkeypatch):
    monkeypatch.setattr(submit_job, "current_sha", lambda: "abc123")
    script = submit_job.build_command(
        _args(stage="dpo", init_adapter="me/other", max_steps=10), {}, "me/douglas-doug-a"
    )[2]

    assert "--init-adapter me/other" in script
    assert "--max-steps 10" in script


def test_build_command_predicts_with_the_adapter(monkeypatch):
    monkeypatch.setattr(submit_job, "current_sha", lambda: "abc123")
    script = submit_job.build_command(
        _args(stage="predict", run="doug-a-predict-x"), {}, "me/douglas-doug-a"
    )[2]

    assert (
        "python3 -m scripts.predict_remote --model doug-a --adapter me/douglas-doug-a"
        " --run doug-a-predict-x"
    ) in script
    assert "train_remote" not in script


def test_build_command_installs_the_pinned_test_runner_for_doug_a_predict(monkeypatch):
    monkeypatch.setattr(submit_job, "current_sha", lambda: "abc123")
    script = submit_job.build_command(
        _args(stage="predict", run="doug-a-predict-x"), {}, "me/douglas-doug-a"
    )[2]

    assert f"python3 -m pip install -q '{submit_job.eval_test_runner()}'" in script
    assert submit_job.eval_test_runner().startswith("pytest==")


def test_build_command_leaves_the_training_stages_alone(monkeypatch):
    monkeypatch.setattr(submit_job, "current_sha", lambda: "abc123")
    script = submit_job.build_command(_args(stage="sft"), {}, "me/douglas-doug-a")[2]

    assert "pytest==" not in script


def test_repo_slug_strips_git_suffix():
    assert submit_job.repo_slug("https://github.com/douglasdemaio/DOUGLAS.git") == (
        "douglasdemaio/DOUGLAS"
    )


def test_main_records_the_reasoner_model(monkeypatch):
    records = []
    job = SimpleNamespace(id="job-123", url="https://example.invalid/job-123")
    fake_hub = SimpleNamespace(run_job=lambda **kwargs: job)

    monkeypatch.setitem(sys.modules, "huggingface_hub", fake_hub)
    monkeypatch.setenv("HF_TOKEN", "placeholder")
    monkeypatch.setattr(
        submit_job,
        "load_config",
        lambda model: {"budget": {"gpu_hours_per_run": 1, "flavor": "cpu"}},
    )
    monkeypatch.setattr(submit_job, "load_recipe", lambda model: None)
    monkeypatch.setattr(submit_job, "budget_check", lambda model, hours: (True, ""))
    monkeypatch.setattr(submit_job, "recipe_sha256", lambda model: "recipe-sha")
    monkeypatch.setattr(submit_job, "current_sha", lambda: "abc123")
    monkeypatch.setattr(submit_job, "namespace", lambda: "douglasdemaio")
    monkeypatch.setattr(submit_job, "append_ledger", records.append)

    rc = submit_job.main(
        [
            "--model",
            "doug-a",
            "--stage",
            "sft",
            "--reasoner-model",
            "openai/gpt-oss-120b",
        ]
    )

    assert rc == 0
    assert len(records) == 1
    assert records[0]["reasoner_model"] == "openai/gpt-oss-120b"
