from __future__ import annotations

from scripts.eval_queue import classify


def _job(stage, status, at, **extra):
    return {"stage": stage, "status": status, "submitted_at": at, "job_id": f"{stage}{at}", **extra}


def test_trained_job_without_predict_is_awaiting():
    state = classify([_job("sft", "done", "2026-11-08T10")])
    assert state["awaiting_predict"]["job_id"] == "sft2026-11-08T10"


def test_failed_predict_does_not_cover_a_trained_job():
    jobs = [_job("sft", "done", "2026-11-08T10"), _job("predict", "failed", "2026-11-08T11")]
    assert classify(jobs)["awaiting_predict"] is not None


def test_active_or_done_predict_covers_a_trained_job():
    for status in ("running", "done"):
        jobs = [_job("sft", "done", "2026-11-08T10"), _job("predict", status, "2026-11-08T11")]
        assert classify(jobs)["awaiting_predict"] is None


def test_retrain_after_predict_is_awaiting_again():
    jobs = [
        _job("sft", "done", "2026-11-08T10"),
        _job("predict", "done", "2026-11-08T11", run="r1"),
        _job("sft", "done", "2026-11-09T10"),
    ]
    state = classify(jobs)
    assert state["awaiting_predict"]["submitted_at"] == "2026-11-09T10"
    assert [j["run"] for j in state["scored"]] == ["r1"]


def test_failed_training_is_not_awaiting():
    assert classify([_job("sft", "failed", "2026-11-08T10")])["awaiting_predict"] is None
