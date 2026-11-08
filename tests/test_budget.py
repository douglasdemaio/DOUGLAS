from __future__ import annotations

from scripts import budget
from scripts.common import utc_now


def _record(**kwargs):
    now = utc_now().replace(microsecond=0).isoformat().replace("+00:00", "Z")
    base = {
        "kind": "job",
        "model": "doug-a",
        "job_id": "j1",
        "status": "done",
        "gpu_hours_est": 2.0,
        "ts": now,
        "submitted_at": now,
    }
    base.update(kwargs)
    return base


def test_usage_sums_latest_per_job(monkeypatch):
    monkeypatch.setattr(
        budget,
        "latest_jobs",
        lambda model: {
            "j1": _record(gpu_hours=3.0),
            "j2": _record(job_id="j2", gpu_hours_est=1.5),
        },
    )
    info = budget.usage("doug-a")
    assert info["used"]["today"] == 4.5
    assert info["caps"]["gpu_hours_per_day"] == 12.0


def test_check_accepts_within_caps(monkeypatch):
    monkeypatch.setattr(budget, "latest_jobs", lambda model: {})
    ok, reason = budget.check("doug-a", 4.0)
    assert ok, reason


def test_check_rejects_over_run_cap(monkeypatch):
    monkeypatch.setattr(budget, "latest_jobs", lambda model: {})
    ok, reason = budget.check("doug-a", 99.0)
    assert not ok
    assert "per-run" in reason
