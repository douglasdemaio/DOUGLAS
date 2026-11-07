"""Emit the workflow's baseline snapshot as JSON on stdout.

Reads only committed state: registry champion scores, the local job ledger and
budget accounting. No network access.
"""

from __future__ import annotations

import json
import sys

from scripts.budget import usage
from scripts.common import MODELS, load_json, registry_dir, utc_now_iso
from scripts.pending_jobs import pending


def champion_scores(model: str) -> dict | None:
    path = registry_dir() / f"{model}.champion.scores.json"
    if not path.exists():
        return None
    data = load_json(path)
    if not data or data.get("metrics") in (None, {}):
        return None
    return data


def snapshot() -> dict:
    return {
        "generated_at": utc_now_iso(),
        "models": {
            model: {
                "champion_scores": champion_scores(model),
                "pending_jobs": pending(model),
                "budget": usage(model),
            }
            for model in MODELS
        },
    }


def main() -> int:
    print(json.dumps(snapshot(), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
