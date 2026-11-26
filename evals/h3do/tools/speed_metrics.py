"""Speed and cost metrics for H3-DO feature traces.

These helpers are pure and take a compact timing record, not a video file:

    {"wall_seconds": 128.4, "gpu_seconds": 101.2, "peak_vram_gb": 20.4}

No field is fetched, executed, or decoded here.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any


def finite_float(value: Any, default: float = 0.0) -> float:
    """Return a finite float or ``default`` for missing/invalid values."""
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError):
        return default
    return result if math.isfinite(result) else default


def score_timings(timings: Any, target_duration_seconds: float) -> dict[str, float]:
    """Score timing data for one generated item."""
    if not isinstance(timings, Mapping):
        return {
            "wall_seconds": 0.0,
            "gpu_seconds": 0.0,
            "peak_vram_gb": 0.0,
            "output_seconds_per_gpu_second": 0.0,
            "timings_valid": 0.0,
        }

    wall = max(0.0, finite_float(timings.get("wall_seconds")))
    gpu = max(0.0, finite_float(timings.get("gpu_seconds"), wall))
    peak = max(0.0, finite_float(timings.get("peak_vram_gb")))
    duration = max(0.0, finite_float(target_duration_seconds))
    valid = wall > 0.0 and gpu > 0.0
    throughput = duration / gpu if valid else 0.0

    return {
        "wall_seconds": wall,
        "gpu_seconds": gpu,
        "peak_vram_gb": peak,
        "output_seconds_per_gpu_second": throughput,
        "timings_valid": 1.0 if valid else 0.0,
    }
