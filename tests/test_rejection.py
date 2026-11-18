from __future__ import annotations

import json

import pytest

from scripts import rejection

FAILURES = [
    {
        "check": "primary_metric",
        "evidence": "fix_rate 0.510 vs champion 0.875 (required delta > 0.020)",
        "why": "A weaker challenger would regress the incident-fix rate.",
        "fix": "Re-run with >=3 seeds and show mean +/- std above the noise margin.",
        "root_cause": "inside the noise margin",
    }
]


def _report(**kwargs):
    return rejection.build_report(
        model="doug-a", run="bad-run", diff_sha256="a" * 64, failures=FAILURES, **kwargs
    )


def test_report_has_the_four_required_sections(tmp_path):
    report = _report()
    for section in rejection.SECTIONS:
        assert report[section]
    text = rejection.render_markdown(report)
    for heading in (
        "## What failed",
        "## Why it matters",
        "## What would make it acceptable",
        "## Root cause",
    ):
        assert heading in text
    assert "fix_rate 0.510" in text


def test_missing_root_cause_is_never_guessed(tmp_path):
    failures = [{k: v for k, v in FAILURES[0].items() if k != "root_cause"}]
    report = rejection.build_report(
        model="doug-a", run="bad-run", diff_sha256="a" * 64, failures=failures
    )
    assert report["root_cause"] == rejection.UNKNOWN_CAUSE


def test_conflicting_diagnoses_fall_back_to_unknown(tmp_path):
    failures = FAILURES + [{**FAILURES[0], "root_cause": "flaky seed"}]
    report = rejection.build_report(
        model="doug-a", run="bad-run", diff_sha256="a" * 64, failures=failures
    )
    assert report["root_cause"] == rejection.UNKNOWN_CAUSE


def test_validate_rejects_empty_sections():
    report = _report()
    report["why_it_matters"] = []
    assert any("why_it_matters" in p for p in rejection.validate_report(report))


def test_write_report_appends_and_never_rewrites(tmp_path):
    report = _report()
    path, report_id = rejection.write_report(report, root=tmp_path)
    assert path.endswith(f"{report_id}.md")
    assert report_id in (tmp_path / "reviews" / "reports" / f"{report_id}.md").read_text()
    log = tmp_path / "reviews" / "rejections.jsonl"
    first = [json.loads(line) for line in log.read_text().splitlines()]
    assert first == [report]

    second = _report(ts="2026-11-19T00:00:00Z")
    second_path, _ = rejection.write_report(second, root=tmp_path)
    assert second_path != path
    entries = [json.loads(line) for line in log.read_text().splitlines()]
    assert entries == [report, second]


def test_find_rejections_by_diff(tmp_path):
    report = _report()
    rejection.write_report(report, root=tmp_path)
    assert rejection.find_rejections("a" * 64, root=tmp_path)[0]["id"] == report["id"]
    assert rejection.find_rejections("b" * 64, root=tmp_path) == []


def test_rejection_requires_all_failure_fields():
    with pytest.raises(ValueError, match="missing"):
        rejection.build_report(
            model="doug-a", run="r", diff_sha256="a" * 64, failures=[{"check": "x"}]
        )
