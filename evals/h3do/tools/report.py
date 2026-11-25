"""Aggregation and Markdown reporting for H3-DO research runs."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any


def mean(values: Sequence[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def stdev(values: Sequence[float]) -> float:
    if len(values) < 2:
        return 0.0
    average = mean(values)
    return (sum((value - average) ** 2 for value in values) / (len(values) - 1)) ** 0.5


def aggregate(per_seed: Sequence[Mapping[str, Sequence[float]]]) -> dict[str, dict[str, Any]]:
    """Aggregate metric values across items within a seed, then across seeds."""
    names = sorted({name for seed in per_seed for name in seed})
    metrics: dict[str, dict[str, Any]] = {}
    for name in names:
        seed_means = [mean(list(seed[name])) for seed in per_seed if seed.get(name)]
        metrics[name] = {
            "mean": round(mean(seed_means), 4),
            "std": round(stdev(seed_means), 4),
            "values": [round(value, 4) for value in seed_means],
        }
    return metrics


def write_markdown(
    path: Path, scores: Mapping[str, Any], failures: Sequence[Mapping[str, Any]]
) -> None:
    lines = [
        f"# {scores['run']} — H3-DO baseline",
        "",
        f"Track: `{scores['track']}`  ",
        f"Model: `{scores['model']}`  ",
        f"Engine: `{scores['engine']}`  ",
        f"Seeds: {scores['seeds']}  ",
        f"Items: {scores['items']}",
        "",
        "## Metrics",
        "",
        "| metric | mean | std | per-seed |",
        "| --- | ---: | ---: | --- |",
    ]
    for name, entry in sorted(scores["metrics"].items()):
        values = ", ".join(str(value) for value in entry["values"])
        lines.append(f"| `{name}` | {entry['mean']} | {entry['std']} | {values} |")

    lines += ["", f"## Failures ({len(failures)})", ""]
    if not failures:
        lines.append("None.")
    else:
        for failure in failures:
            lines.append(f"- `{failure['id']}` seed {failure['seed']}: {failure['reason']}")

    lines += ["", "## Hashes", ""]
    for name, value in sorted(scores["hashes"].items()):
        lines.append(f"- `{name}`: `{value}`")
    lines.append("")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")
