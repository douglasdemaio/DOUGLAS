from __future__ import annotations

from scripts.common import MODELS, frozen_sha256, verify_frozen_manifest


def test_manifests_are_intact():
    for model in MODELS:
        assert verify_frozen_manifest(model) == []


def test_frozen_hash_is_stable():
    for model in MODELS:
        first = frozen_sha256(model)
        second = frozen_sha256(model)
        assert first == second
        assert len(first) == 64


def test_manifest_lists_every_frozen_file(repo_root):
    import json

    for model in MODELS:
        frozen = repo_root / "evals" / model / "frozen"
        manifest = json.loads((frozen / "manifest.json").read_text())
        on_disk = {
            path.relative_to(frozen).as_posix()
            for path in frozen.rglob("*")
            if path.is_file() and path.name != "manifest.json"
        }
        assert set(manifest["files"]) == on_disk
