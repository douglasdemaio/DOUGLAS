"""Shared helpers for the DOUGLAS loop.

Everything here is CPU-only and standard-library except for PyYAML.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from collections.abc import Iterable, Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parent.parent
MODELS = ("doug-a", "doug-l")


# --------------------------------------------------------------------------- #
# paths
# --------------------------------------------------------------------------- #
def model_dir(model: str) -> Path:
    _check_model(model)
    return ROOT / "models" / model


def data_dir(model: str) -> Path:
    _check_model(model)
    return ROOT / "data" / model


def eval_dir(model: str) -> Path:
    _check_model(model)
    return ROOT / "evals" / model


def frozen_dir(model: str) -> Path:
    return eval_dir(model) / "frozen"


def registry_dir() -> Path:
    return ROOT / "registry"


def ledger_path() -> Path:
    return ROOT / "experiments" / "ledger.jsonl"


def _check_model(model: str) -> None:
    if model not in MODELS:
        raise ValueError(f"unknown model {model!r}; expected one of {MODELS}")


# --------------------------------------------------------------------------- #
# time
# --------------------------------------------------------------------------- #
def utc_now() -> datetime:
    return datetime.now(UTC)


def utc_now_iso() -> str:
    return utc_now().replace(microsecond=0).isoformat().replace("+00:00", "Z")


def parse_ts(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


# --------------------------------------------------------------------------- #
# serialisation
# --------------------------------------------------------------------------- #
def canonical_json(obj: Any) -> bytes:
    """Canonical JSON used for hashing and JWS payloads."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def pretty_json(obj: Any) -> str:
    return json.dumps(obj, indent=2, sort_keys=True) + "\n"


def load_yaml(path: Path | str) -> dict:
    with open(path, encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    if not isinstance(data, dict):
        raise ValueError(f"{path}: expected a YAML mapping")
    return data


def load_json(path: Path | str) -> Any:
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def atomic_write(path: Path | str, text: str) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=path.name, dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def write_json(path: Path | str, obj: Any) -> None:
    atomic_write(path, pretty_json(obj))


def read_jsonl(path: Path | str) -> Iterator[dict]:
    path = Path(path)
    if not path.exists():
        return
    with open(path, encoding="utf-8") as fh:
        for lineno, line in enumerate(fh, 1):
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError as exc:  # pragma: no cover - defensive
                raise ValueError(f"{path}:{lineno}: invalid JSON: {exc}") from exc


def append_jsonl(path: Path | str, record: dict) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(record, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(line + "\n")


# --------------------------------------------------------------------------- #
# hashing
# --------------------------------------------------------------------------- #
def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path | str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def sha256_obj(obj: Any) -> str:
    return sha256_bytes(canonical_json(obj))


def tree_sha256(path: Path | str, ignore: Iterable[str] = ()) -> str:
    """Hash a directory tree: relative path + NUL + content, in sorted order."""
    path = Path(path)
    ignored = set(ignore)
    h = hashlib.sha256()
    for file in sorted(path.rglob("*")):
        if not file.is_file():
            continue
        rel = file.relative_to(path).as_posix()
        if rel in ignored or any(rel.startswith(i) for i in ignored):
            continue
        h.update(rel.encode())
        h.update(b"\0")
        h.update(file.read_bytes())
        h.update(b"\0")
    return h.hexdigest()


def frozen_sha256(model: str) -> str:
    """Hash of the frozen eval set, excluding the manifest itself."""
    return tree_sha256(frozen_dir(model), ignore={"manifest.json"})


def verify_frozen_manifest(model: str) -> list[str]:
    """Return a list of manifest/hash problems; empty means intact."""
    frozen = frozen_dir(model)
    manifest_path = frozen / "manifest.json"
    if not manifest_path.exists():
        return [f"{model}: frozen/manifest.json is missing"]
    manifest = load_json(manifest_path)
    problems = []
    listed = manifest.get("files", {})
    for rel, expected in listed.items():
        path = frozen / rel
        if not path.exists():
            problems.append(f"{model}: frozen file missing: {rel}")
        elif sha256_file(path) != expected:
            problems.append(f"{model}: frozen file modified: {rel}")
    for path in frozen.rglob("*"):
        if path.is_file() and path.name != "manifest.json":
            rel = path.relative_to(frozen).as_posix()
            if rel not in listed:
                problems.append(f"{model}: unlisted frozen file: {rel}")
    return problems


def recipe_sha256(model: str) -> str:
    return sha256_file(model_dir(model) / "recipe.yaml")


def config_path(model: str) -> Path:
    return model_dir(model) / "config.yaml"


def load_config(model: str) -> dict:
    return load_yaml(config_path(model))


def load_recipe(model: str) -> dict:
    return load_yaml(model_dir(model) / "recipe.yaml")


# --------------------------------------------------------------------------- #
# ledger
# --------------------------------------------------------------------------- #
def append_ledger(record: dict) -> None:
    record = {"ts": utc_now_iso(), **record}
    append_jsonl(ledger_path(), record)


def latest_jobs(model: str | None = None) -> dict[str, dict]:
    """Latest state per job id, keyed by job id."""
    jobs: dict[str, dict] = {}
    for rec in read_jsonl(ledger_path()):
        if rec.get("kind") != "job":
            continue
        if model and rec.get("model") != model:
            continue
        job_id = rec.get("job_id")
        if job_id:
            jobs[job_id] = rec
    return jobs
