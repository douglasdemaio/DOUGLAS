from __future__ import annotations

import socket

import pytest

from scripts import containment


def test_repo_and_artifact_paths_are_allowed(tmp_path):
    containment.assert_writable(tmp_path / "models" / "doug-a" / "recipe.yaml", root=tmp_path)
    containment.assert_writable(tmp_path / "results" / "run" / "scores.json", root=tmp_path)
    containment.assert_writable(tmp_path / "_hub" / "evals", root=tmp_path)


def test_extra_artifact_root_from_environment(tmp_path):
    artifact = tmp_path.parent / "artifact-store"
    containment.assert_writable(
        artifact / "scores.json", root=tmp_path, env={"DOUGLAS_ARTIFACT_DIR": str(artifact)}
    )


def test_outside_write_is_logged_and_halted(tmp_path):
    outside = tmp_path.parent / "outside-douglas.txt"
    with pytest.raises(containment.ContainmentViolation, match="outside"):
        containment.assert_writable(outside, root=tmp_path)
    logged = containment.violations(root=tmp_path)
    assert len(logged) == 1
    assert logged[0]["kind"] == "write_outside_roots"
    assert str(outside) in logged[0]["detail"]


def test_symlink_escape_is_blocked(tmp_path):
    outside = tmp_path.parent / "escape-target.txt"
    link = tmp_path / "results" / "escape"
    link.parent.mkdir(parents=True, exist_ok=True)
    link.symlink_to(outside)
    with pytest.raises(containment.ContainmentViolation):
        containment.assert_writable(link, root=tmp_path)
    assert len(containment.violations(root=tmp_path)) == 1


def test_scrub_env_drops_secrets_and_disables_network():
    base = {
        "PATH": "/usr/bin",
        "HF_TOKEN": "secret-token",
        "DOUGLAS_SIGNING_KEY": "secret-key",
        "HOME": "/home/douglas",
        "HF_HUB_OFFLINE": "0",
    }
    env = containment.scrub_env(base=base)
    assert env["PATH"] == "/usr/bin"
    assert env["HOME"] == "/home/douglas"
    assert "HF_TOKEN" not in env
    assert "DOUGLAS_SIGNING_KEY" not in env
    assert env["HTTP_PROXY"] == "http://127.0.0.1:1"
    assert env["HF_HUB_OFFLINE"] == "1"


def test_explicitly_kept_key_is_not_dropped():
    env = containment.scrub_env(base={"DOUGLAS_SIGNING_KEY": "key"}, keep={"DOUGLAS_SIGNING_KEY"})
    assert env["DOUGLAS_SIGNING_KEY"] == "key"


def test_network_call_is_logged_and_blocked(tmp_path):
    original = containment.block_network(root=tmp_path)
    try:
        with pytest.raises(containment.ContainmentViolation, match="network"):
            socket.create_connection(("1.1.1.1", 80), timeout=1)
    finally:
        containment.restore_network(original)
    logged = containment.violations(root=tmp_path)
    assert len(logged) == 1
    assert logged[0]["kind"] == "network_attempt"
