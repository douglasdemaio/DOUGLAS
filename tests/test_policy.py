from __future__ import annotations

import json

from scripts import policy


def _policy_file(tmp_path, **overrides):
    rules = {
        "schema_version": 1,
        "max_runs_per_day": 1,
        "max_open_prs": 1,
        "cooldown_hours_after_rejection": 24,
        "cooldown_hours_after_rollback": 24,
    }
    rules.update(overrides)
    path = tmp_path / "policy.json"
    path.write_text(json.dumps(rules))
    return path


def test_first_run_allowed(tmp_path):
    rules = _policy_file(tmp_path)
    ok, reasons = policy.check_start(
        "doug-a", "a" * 64, now="2026-11-18T12:00:00Z", policy_path=rules,
        events_path=tmp_path / "events.jsonl",
    )
    assert ok, reasons


def test_daily_cap_and_open_pr_are_enforced(tmp_path):
    rules = _policy_file(tmp_path)
    events = tmp_path / "events.jsonl"
    policy.record("run", path=events, ts="2026-11-18T08:00:00Z", model="doug-a", diff="b" * 64)
    policy.record(
        "pr_open", path=events, ts="2026-11-18T09:00:00Z", branch="douglas/one"
    )
    ok, reasons = policy.check_start(
        "doug-a", "a" * 64, now="2026-11-18T12:00:00Z", policy_path=rules, events_path=events
    )
    assert not ok
    assert any("run cap" in r for r in reasons)
    assert any("open PRs" in r for r in reasons)


def test_closed_pr_frees_the_slot(tmp_path):
    rules = _policy_file(tmp_path)
    events = tmp_path / "events.jsonl"
    policy.record("pr_open", path=events, branch="douglas/one")
    policy.record("pr_closed", path=events, branch="douglas/one")
    ok, reasons = policy.check_start(
        "doug-a", "a" * 64, policy_path=rules, events_path=events
    )
    assert ok, reasons


def test_cooldown_after_rejection_and_rollback(tmp_path):
    rules = _policy_file(tmp_path)
    events = tmp_path / "events.jsonl"
    policy.record("rejection", path=events, ts="2026-11-18T06:00:00Z", model="doug-a")
    policy.record("rollback", path=events, ts="2026-11-18T10:00:00Z", model="doug-l")
    ok, reasons = policy.check_start(
        "doug-a", "a" * 64, now="2026-11-18T12:00:00Z", policy_path=rules, events_path=events
    )
    assert not ok
    assert any("rejection cooldown" in r for r in reasons)
    assert any("rollback cooldown" in r for r in reasons)

    ok, reasons = policy.check_start(
        "doug-a", "a" * 64, now="2026-11-20T12:00:00Z", policy_path=rules, events_path=events
    )
    assert ok, reasons


def test_rejected_diff_needs_a_report_reference(tmp_path):
    rules = _policy_file(tmp_path)
    events = tmp_path / "events.jsonl"
    policy.record(
        "rejection", path=events, ts="2026-11-18T06:00:00Z", model="doug-a",
        diff="a" * 64, report="rejection-1",
    )
    now = "2026-11-20T12:00:00Z"
    ok, reasons = policy.check_start(
        "doug-a", "a" * 64, now=now, policy_path=rules, events_path=events
    )
    assert not ok
    assert any("already rejected" in r for r in reasons)

    ok, reasons = policy.check_start(
        "doug-a", "a" * 64, now=now, addresses="rejection-1",
        policy_path=rules, events_path=events,
    )
    assert ok, reasons


def test_unreadable_state_fails_closed(tmp_path):
    missing_rules = tmp_path / "missing.json"
    ok, reasons = policy.check_start(
        "doug-a", "a" * 64, policy_path=missing_rules, events_path=tmp_path / "events.jsonl"
    )
    assert not ok and reasons

    rules = _policy_file(tmp_path)
    events = tmp_path / "events.jsonl"
    events.write_text("{not json}\n")
    ok, reasons = policy.check_start(
        "doug-a", "a" * 64, policy_path=rules, events_path=events
    )
    assert not ok
    assert any("unavailable" in r for r in reasons)
