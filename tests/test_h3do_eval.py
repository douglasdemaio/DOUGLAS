"""Offline tests for the H3-DO research harness."""

from __future__ import annotations

import copy
import json

import pytest

from evals.h3do.tools import baseline, quality_metrics, report, speed_metrics
from scripts.common import ROOT, load_json, read_jsonl

RESEARCH = ROOT / "evals" / "h3do" / "research"
MANIFEST = RESEARCH / "eval_manifest.json"
PREDICTIONS = RESEARCH / "synthetic_predictions.jsonl"


def fixture_predictions() -> list[dict]:
    return list(read_jsonl(PREDICTIONS))


def test_manifest_and_fixture_are_consistent() -> None:
    manifest = load_json(MANIFEST)
    prompts = list(read_jsonl(RESEARCH / "prompts.jsonl"))
    predictions = fixture_predictions()
    seeds = [1, 2, 3]

    assert baseline.validate_manifest(manifest, prompts, seeds) == []
    index = baseline.load_predictions(PREDICTIONS)
    assert set(index) == {(item["id"], seed) for item in manifest["items"] for seed in seeds}
    assert all(record["frames"] for record in predictions)


def test_quality_metrics_penalize_bad_traces() -> None:
    manifest = load_json(MANIFEST)
    item = manifest["items"][0]
    prediction = fixture_predictions()[0]

    good = quality_metrics.score_item(prediction, item, manifest)
    assert good["format_valid"] == 1.0
    assert good["success_rate"] == 1.0
    assert good["artifact_rate"] == 0.0
    assert good["audio_video_sync"] == 1.0

    bad = copy.deepcopy(prediction)
    bad["frames"][0]["valid"] = False
    bad["alignment"] = 2.0
    bad["audio"]["duration_seconds"] = 2.0
    bad["timings"]["gpu_seconds"] = 0
    bad["errors"] = ["decode failed"]
    scored = quality_metrics.score_item(bad, item, manifest)

    assert scored["format_valid"] == 1.0
    assert scored["success_rate"] == 0.0
    assert scored["prompt_alignment"] == 1.0
    assert scored["artifact_rate"] > 0.0
    assert scored["audio_video_sync"] == 0.0
    assert scored["timings_valid"] == 0.0

    malformed = dict(prediction)
    malformed.pop("audio")
    assert quality_metrics.score_item(malformed, item, manifest)["format_valid"] == 0.0


def test_speed_metrics_throughput_and_fallback() -> None:
    scored = speed_metrics.score_timings(
        {"wall_seconds": 120.0, "gpu_seconds": 100.0, "peak_vram_gb": 21.0},
        4.0,
    )
    assert scored["output_seconds_per_gpu_second"] == pytest.approx(0.04)
    assert scored["timings_valid"] == 1.0

    missing_gpu = speed_metrics.score_timings({"wall_seconds": 120.0}, 4.0)
    assert missing_gpu["gpu_seconds"] == 120.0
    assert missing_gpu["output_seconds_per_gpu_second"] == pytest.approx(4.0 / 120.0)


def test_report_aggregate_uses_sample_std() -> None:
    metrics = report.aggregate(
        [
            {"success_rate": [1.0, 0.8]},
            {"success_rate": [0.9, 0.7]},
            {"success_rate": [1.0, 0.9]},
        ]
    )
    assert metrics["success_rate"]["values"] == pytest.approx([0.9, 0.8, 0.95])
    assert metrics["success_rate"]["std"] > 0.0


def test_baseline_cli_writes_scores_offline(tmp_path) -> None:
    out_dir = tmp_path / "run"
    assert baseline.main(["--seeds", "3", "--out", str(out_dir)]) == 0

    scores = json.loads((out_dir / "scores.json").read_text(encoding="utf-8"))
    assert scores["track"] == "h3do"
    assert scores["engine"] == "replay"
    assert scores["seeds"] == [1, 2, 3]
    assert scores["failure_count"] == 0
    assert scores["metrics"]["success_rate"]["mean"] == 1.0
    assert scores["metrics"]["output_seconds_per_gpu_second"]["mean"] > 0.0
    assert (out_dir / "report.md").exists()


def test_baseline_requires_at_least_three_seeds(tmp_path) -> None:
    assert baseline.main(["--seeds", "2", "--out", str(tmp_path / "short")]) == 2
