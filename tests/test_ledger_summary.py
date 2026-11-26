"""Tests for the bounded ledger summary used by the workflow agent."""

from __future__ import annotations

import json

from scripts import ledger


def _write_ledger(path, records) -> None:
    path.write_text("\n".join(json.dumps(record, sort_keys=True) for record in records) + "\n")


def test_summary_is_bounded_and_keeps_recent_evidence(monkeypatch, tmp_path):
    path = tmp_path / "ledger.jsonl"
    records = [
        {
            "ts": "2026-11-01T00:00:00Z",
            "kind": "plan",
            "model": "doug-a",
            "concern": "baseline",
            "hypothesis": "x" * 5000,
        },
        {
            "ts": "2026-11-02T00:00:00Z",
            "kind": "job",
            "model": "doug-a",
            "concern": "recipe:filter",
            "status": "done",
            "job_id": "older-job",
        },
        {
            "ts": "2026-11-03T00:00:00Z",
            "kind": "plan",
            "model": "doug-l",
            "concern": "data:dedupe",
        },
        {
            "ts": "2026-11-04T00:00:00Z",
            "kind": "job",
            "model": "doug-a",
            "concern": "recipe:filter",
            "status": "failed",
            "job_id": "newest-job",
        },
    ]
    _write_ledger(path, records)
    monkeypatch.setattr(ledger, "ledger_path", lambda: path)

    out = ledger.summary(limit=2, max_bytes=1500)

    assert len(out.encode()) <= 1500
    assert "ledger entries: 4" in out
    assert "seen concerns (doug-a): baseline, recipe:filter" in out
    assert "seen concerns (doug-l): data:dedupe" in out
    assert "newest-job" in out
    assert "older-job" not in out
    assert "x" * 5000 not in out


def test_summary_cli_uses_the_bounded_view(monkeypatch, tmp_path, capsys):
    path = tmp_path / "ledger.jsonl"
    _write_ledger(path, [{"ts": "2026-11-04T00:00:00Z", "kind": "plan", "model": "doug-a"}])
    monkeypatch.setattr(ledger, "ledger_path", lambda: path)

    assert ledger.main(["summary", "--limit", "1"]) == 0
    out = capsys.readouterr().out

    assert "ledger entries: 1" in out
    assert "recent entries (last 1):" in out
