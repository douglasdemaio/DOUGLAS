"""Deterministic visual-quality metrics for H3-DO feature traces.

The grader works on compact numeric traces committed to or returned by a
predictor. It never reads video bytes or executes model output.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import Any

from .speed_metrics import finite_float, score_timings

REQUIRED_PREDICTION_KEYS = ("id", "seed", "frames", "alignment", "audio", "timings", "errors")


def clamp01(value: float) -> float:
    if not math.isfinite(value):
        return 0.0
    return max(0.0, min(1.0, value))


def mean(values: Sequence[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def frame_metrics(frames: Any) -> dict[str, float]:
    """Score frame validity, flicker, and hash-based temporal consistency."""
    if not isinstance(frames, Sequence) or isinstance(frames, (str, bytes)):
        return {
            "artifact_rate": 1.0,
            "flicker": 1.0,
            "temporal_consistency": 0.0,
            "valid_frame_ratio": 0.0,
        }

    valid = [frame for frame in frames if isinstance(frame, Mapping) and frame.get("valid") is True]
    artifact_rate = 1.0 - len(valid) / len(frames) if frames else 1.0

    lumas = [finite_float(frame.get("mean_luma")) for frame in valid]
    flicker = mean([abs(b - a) for a, b in zip(lumas, lumas[1:], strict=False)])

    hashes = [str(frame.get("hash", "")) for frame in valid]
    distances: list[float] = []
    for left, right in zip(hashes, hashes[1:], strict=False):
        if not left or not right or len(left) != len(right):
            distances.append(1.0)
            continue
        try:
            xor = int(left, 16) ^ int(right, 16)
        except ValueError:
            distances.append(1.0)
            continue
        bit_count = len(left) * 4
        distances.append(xor.bit_count() / bit_count if bit_count else 1.0)

    consistency = clamp01(1.0 - mean(distances)) if distances else 0.0
    return {
        "artifact_rate": clamp01(artifact_rate),
        "flicker": clamp01(flicker),
        "temporal_consistency": consistency,
        "valid_frame_ratio": 1.0 - clamp01(artifact_rate),
    }


def audio_metrics(audio: Any, target_duration_seconds: float, tolerance: float) -> float:
    """Return 1.0 for valid stereo audio with the expected duration."""
    if not isinstance(audio, Mapping) or audio.get("valid") is not True:
        return 0.0
    duration = finite_float(audio.get("duration_seconds"), -1.0)
    duration_ok = abs(duration - target_duration_seconds) <= tolerance
    channels_ok = audio.get("channels") == 2
    sample_rate_ok = audio.get("sample_rate_hz") == 32000
    return 1.0 if duration_ok and channels_ok and sample_rate_ok else 0.0


def score_item(
    prediction: Any, item: Mapping[str, Any], manifest: Mapping[str, Any]
) -> dict[str, float]:
    """Score one prediction against one manifest item."""
    zero = {
        "format_valid": 0.0,
        "success_rate": 0.0,
        "prompt_alignment": 0.0,
        "artifact_rate": 1.0,
        "flicker": 1.0,
        "temporal_consistency": 0.0,
        "valid_frame_ratio": 0.0,
        "audio_video_sync": 0.0,
        "wall_seconds": 0.0,
        "gpu_seconds": 0.0,
        "peak_vram_gb": 0.0,
        "output_seconds_per_gpu_second": 0.0,
        "timings_valid": 0.0,
    }
    if not isinstance(prediction, Mapping):
        return zero

    format_ok = all(key in prediction for key in REQUIRED_PREDICTION_KEYS)
    format_ok = format_ok and prediction.get("id") == item.get("id")
    format_ok = format_ok and isinstance(prediction.get("seed"), int)
    format_ok = format_ok and isinstance(prediction.get("frames"), list)
    format_ok = format_ok and isinstance(prediction.get("audio"), Mapping)
    format_ok = format_ok and isinstance(prediction.get("timings"), Mapping)
    format_ok = format_ok and isinstance(prediction.get("errors"), list)
    if not format_ok:
        return zero

    duration = finite_float(
        item.get("duration_seconds"), finite_float(manifest.get("duration_seconds"), 4.0)
    )
    tolerance = finite_float(manifest.get("audio_sync_tolerance_seconds"), 0.25)
    artifact_tolerance = finite_float(manifest.get("artifact_tolerance"), 0.05)

    quality = frame_metrics(prediction["frames"])
    speed = score_timings(prediction["timings"], duration)
    errors = prediction.get("errors") or []

    success = (
        not errors
        and quality["artifact_rate"] <= artifact_tolerance
        and speed["timings_valid"] == 1.0
    )

    result = {
        "format_valid": 1.0,
        "success_rate": 1.0 if success else 0.0,
        "prompt_alignment": clamp01(finite_float(prediction.get("alignment"))),
        **quality,
        "audio_video_sync": audio_metrics(prediction["audio"], duration, tolerance),
        **speed,
    }
    if result["audio_video_sync"] != 1.0:
        result["success_rate"] = 0.0
    return result
