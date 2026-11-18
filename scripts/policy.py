"""Run-rate, PR and cooldown policy for the DOUGLAS review loop.

All state lives in append-only docs/reviews/events.jsonl. Missing or unreadable
state means "no run": the policy fails closed.

    python -m scripts.policy check --model doug-a --diff <sha256>
    python -m scripts.policy record --kind pr_open --branch douglas/...
"""

from __future__ import annotations

import argparse
import sys
from datetime import timedelta
from pathlib import Path
from typing import Any

from scripts.common import (
    ROOT,
    append_jsonl,
    load_json,
    parse_ts,
    read_jsonl,
    utc_now,
    utc_now_iso,
)

POLICY_PATH = ROOT / "docs" / "reviews" / "policy.json"
EVENTS_PATH = ROOT / "docs" / "reviews" / "events.jsonl"
KINDS = {"run", "pr_open", "pr_closed", "rejection", "rollback", "network_allowed"}


class PolicyError(RuntimeError):
    """Raised when policy state is missing or corrupt."""


def load_policy(path: Path | None = None) -> dict[str, Any]:
    path = path or POLICY_PATH
    try:
        data = load_json(path)
    except (OSError, ValueError) as exc:
        raise PolicyError(f"cannot load policy {path}: {exc}") from exc
    required = (
        "max_runs_per_day",
        "max_open_prs",
        "cooldown_hours_after_rejection",
        "cooldown_hours_after_rollback",
    )
    for key in required:
        value = data.get(key)
        if not isinstance(value, (int, float)) or isinstance(value, bool) or value < 0:
            raise PolicyError(f"{path}: {key} must be a non-negative number")
    return data


def read_events(path: Path | None = None) -> list[dict[str, Any]]:
    path = path or EVENTS_PATH
    try:
        return list(read_jsonl(path))
    except ValueError as exc:
        raise PolicyError(f"cannot read events {path}: {exc}") from exc


def record(kind: str, *, path: Path | None = None, ts: str | None = None, **fields: Any) -> dict:
    if kind not in KINDS:
        raise ValueError(f"unknown event kind {kind!r}; expected one of {sorted(KINDS)}")
    if "diff" in fields:
        fields["diff_sha256"] = fields.pop("diff")
    event = {"ts": ts or utc_now_iso(), "kind": kind, **fields}
    append_jsonl(path or EVENTS_PATH, event)
    return event


def _open_branches(events: list[dict[str, Any]]) -> set[str]:
    branches: set[str] = set()
    for event in events:
        branch = event.get("branch")
        if not branch:
            continue
        if event.get("kind") == "pr_open":
            branches.add(str(branch))
        elif event.get("kind") == "pr_closed":
            branches.discard(str(branch))
    return branches


def check_start(
    model: str,
    diff_sha256: str,
    *,
    addresses: str | None = None,
    now: str | None = None,
    policy: dict[str, Any] | None = None,
    policy_path: Path | None = None,
    events_path: Path | None = None,
) -> tuple[bool, list[str]]:
    """Return (allowed, reasons). Any unreadable state rejects the run."""
    try:
        rules = policy or load_policy(policy_path)
        events = read_events(events_path)
    except PolicyError as exc:
        return False, [f"policy state unavailable: {exc}"]

    current = parse_ts(now) if now else utc_now()
    day_start = current.replace(hour=0, minute=0, second=0, microsecond=0)
    problems: list[str] = []

    runs_today = 0
    for event in events:
        if event.get("kind") != "run":
            continue
        try:
            stamp = parse_ts(event["ts"])
        except (KeyError, ValueError):
            problems.append("run event has an invalid timestamp")
            continue
        if stamp >= day_start:
            runs_today += 1
    if runs_today >= rules["max_runs_per_day"]:
        problems.append(f"daily run cap reached: {runs_today} >= {rules['max_runs_per_day']}")

    open_prs = _open_branches(events)
    if len(open_prs) >= rules["max_open_prs"]:
        problems.append(f"too many open PRs: {len(open_prs)} >= {rules['max_open_prs']}")

    cooldowns = {
        "rejection": rules["cooldown_hours_after_rejection"],
        "rollback": rules["cooldown_hours_after_rollback"],
    }
    for event in events:
        kind = event.get("kind")
        if kind not in cooldowns:
            continue
        try:
            elapsed = current - parse_ts(event["ts"])
        except (KeyError, ValueError):
            problems.append(f"{kind} event has an invalid timestamp")
            continue
        if elapsed < timedelta(hours=float(cooldowns[kind])):
            problems.append(
                f"{kind} cooldown active ({(current - parse_ts(event['ts'])).total_seconds() / 3600:.1f}h ago)"
            )

    prior = [
        event
        for event in events
        if event.get("kind") == "rejection" and event.get("diff_sha256") == diff_sha256
    ]
    if prior:
        ids = [str(event.get("report") or event.get("id") or "unknown") for event in prior]
        if not addresses or addresses not in ids:
            problems.append(
                f"this diff was already rejected ({', '.join(ids)}); "
                "resubmit only as a new run that names the report in --addresses"
            )

    return (not problems), problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    p_check = sub.add_parser("check")
    p_check.add_argument("--model", required=True)
    p_check.add_argument("--diff", required=True)
    p_check.add_argument("--addresses")
    p_record = sub.add_parser("record")
    p_record.add_argument("--kind", required=True, choices=sorted(KINDS))
    p_record.add_argument("--model")
    p_record.add_argument("--diff")
    p_record.add_argument("--branch")
    p_record.add_argument("--report")
    args = parser.parse_args(argv)

    if args.command == "check":
        ok, reasons = check_start(args.model, args.diff, addresses=args.addresses)
        print("policy: OK" if ok else "policy: REJECT")
        for reason in reasons:
            print(f"  - {reason}")
        return 0 if ok else 1

    fields = {
        key: getattr(args, key)
        for key in ("model", "diff", "branch", "report")
        if getattr(args, key)
    }
    event = record(args.kind, **fields)
    print(f"recorded {event['kind']} at {event['ts']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
