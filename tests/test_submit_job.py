from __future__ import annotations

from argparse import Namespace

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


def test_repo_slug_strips_git_suffix():
    assert submit_job.repo_slug("https://github.com/douglasdemaio/DOUGLAS.git") == (
        "douglasdemaio/DOUGLAS"
    )
