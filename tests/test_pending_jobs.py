from __future__ import annotations

import sys
import types

from scripts import pending_jobs


def _fake_hub(monkeypatch, stage: str, total_secs: float | None):
    info = types.SimpleNamespace(
        status=types.SimpleNamespace(stage=stage),
        durations=types.SimpleNamespace(total_secs=total_secs),
    )
    module = types.ModuleType("huggingface_hub")
    module.inspect_job = lambda **kwargs: info
    monkeypatch.setitem(sys.modules, "huggingface_hub", module)


def test_refresh_charges_actual_runtime_of_a_failed_job(monkeypatch):
    appended = []
    monkeypatch.setattr(pending_jobs, "append_ledger", appended.append)
    monkeypatch.setenv("HF_TOKEN", "test")
    _fake_hub(monkeypatch, "ERROR", 5.0)

    record = {
        "kind": "job",
        "model": "doug-a",
        "job_id": "j1",
        "status": "pending",
        "gpu_hours_est": 6.0,
    }
    refreshed = pending_jobs.refresh(record)

    assert refreshed["status"] == "failed"
    assert refreshed["gpu_hours"] == 0.0014
    assert refreshed["finished_at"]
    assert appended[-1]["gpu_hours"] == 0.0014


def test_refresh_keeps_estimate_while_running(monkeypatch):
    appended = []
    monkeypatch.setattr(pending_jobs, "append_ledger", appended.append)
    monkeypatch.setenv("HF_TOKEN", "test")
    _fake_hub(monkeypatch, "RUNNING", None)

    record = {
        "kind": "job",
        "model": "doug-a",
        "job_id": "j1",
        "status": "pending",
        "gpu_hours_est": 6.0,
    }
    refreshed = pending_jobs.refresh(record)

    assert refreshed["status"] == "running"
    assert "gpu_hours" not in refreshed
    assert refreshed["finished_at"] is None
