"""Containment guard for the DOUGLAS review loop.

Writes are confined to the repository and its artifact store (results/,
_hub/ and $DOUGLAS_ARTIFACT_DIR). Subprocesses get a minimal environment,
network calls fail unless explicitly allowed, and every violation is appended
to docs/reviews/containment.jsonl before the process halts.

    python -m scripts.containment check --path results/run/scores.json
    python -m scripts.containment log
"""

from __future__ import annotations

import argparse
import os
import socket
import sys
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from scripts.common import ROOT, append_jsonl, read_jsonl, utc_now_iso

ARTIFACT_DIRS = ("results", "_hub")
SECRET_KEYS = frozenset(
    {
        "HF_TOKEN",
        "DOUGLAS_SIGNING_KEY",
        "MODEL_ENDPOINT_TOKEN",
        "ANTHROPIC_API_KEY",
        "GH_TOKEN",
        "GITHUB_TOKEN",
        "HUGGING_FACE_HUB_TOKEN",
    }
)
ALLOWED_ENV = frozenset({"PATH", "HOME", "LANG", "LC_ALL", "PYTHON", "VIRTUAL_ENV", "TMPDIR", "CI"})
PROXY_OFF = {
    "HTTP_PROXY": "http://127.0.0.1:1",
    "HTTPS_PROXY": "http://127.0.0.1:1",
    "http_proxy": "http://127.0.0.1:1",
    "https_proxy": "http://127.0.0.1:1",
    "ALL_PROXY": "http://127.0.0.1:1",
    "all_proxy": "http://127.0.0.1:1",
    "NO_PROXY": "",
    "no_proxy": "",
    "HF_HUB_OFFLINE": "1",
    "TRANSFORMERS_OFFLINE": "1",
}


class ContainmentViolation(RuntimeError):
    """An attempted write, read or network call outside the allowed limits."""


def containment_log(root: Path = ROOT) -> Path:
    return Path(root) / "docs" / "reviews" / "containment.jsonl"


def record_violation(kind: str, detail: str, *, root: Path = ROOT) -> dict[str, Any]:
    event = {"ts": utc_now_iso(), "kind": kind, "detail": detail}
    append_jsonl(containment_log(root), event)
    return event


def violations(root: Path = ROOT) -> list[dict[str, Any]]:
    return list(read_jsonl(containment_log(root)))


def artifact_roots(root: Path = ROOT, env: dict[str, str] | None = None) -> list[Path]:
    base = Path(root).resolve()
    roots = [base, *(base / name for name in ARTIFACT_DIRS)]
    environ = os.environ if env is None else env
    extra = environ.get("DOUGLAS_ARTIFACT_DIR")
    if extra:
        roots.append(Path(extra).resolve())
    return roots


def assert_writable(
    path: Path | str, *, root: Path = ROOT, env: dict[str, str] | None = None
) -> Path:
    """Resolve symlinks and require the target to be inside an allowed root."""
    target = Path(path).resolve()
    for allowed in artifact_roots(root, env):
        if target == allowed or allowed in target.parents:
            return target
    detail = f"write outside repository and artifact store: {target}"
    record_violation("write_outside_roots", detail, root=root)
    raise ContainmentViolation(detail)


def scrub_env(
    *, keep: Iterable[str] = (), base: dict[str, str] | None = None, allow_network: bool = False
) -> dict[str, str]:
    """Keep only generic environment variables plus explicitly allowed keys.

    Secrets are dropped by default. `keep` is for the one privileged call
    (the gate needs DOUGLAS_SIGNING_KEY); its value is never printed.
    """
    environ = os.environ if base is None else base
    extra = set(keep)
    env = {k: v for k, v in environ.items() if k in ALLOWED_ENV or k in extra}
    if not allow_network:
        env.update(PROXY_OFF)
    return env


def block_network(*, root: Path = ROOT):
    """Disable outbound sockets in this process. Returns the original connect."""
    original = socket.socket.connect

    def guarded(self, address):  # noqa: ANN001 - socket signature
        detail = f"network attempt blocked: {address!r}"
        record_violation("network_attempt", detail, root=root)
        raise ContainmentViolation(detail)

    socket.socket.connect = guarded
    return original


def restore_network(original) -> None:  # noqa: ANN001 - socket signature
    socket.socket.connect = original


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    p_check = sub.add_parser("check")
    p_check.add_argument("--path", required=True)
    sub.add_parser("log")
    args = parser.parse_args(argv)

    if args.command == "check":
        try:
            target = assert_writable(args.path)
        except ContainmentViolation as exc:
            print(f"containment: REJECT — {exc}")
            return 1
        print(f"containment: OK — {target}")
        return 0

    for event in violations():
        print(f"{event['ts']} {event['kind']}: {event['detail']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
