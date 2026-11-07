from __future__ import annotations

from scripts import contamination


def _write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_identical_text_is_dirty(tmp_path, monkeypatch):
    train = tmp_path / "data"
    frozen = tmp_path / "frozen"
    leak = (
        "the quick brown fox jumps over the lazy dog while the tired driver waits at the depot gate"
    )
    _write(train / "seed.jsonl", '{"text": "' + leak + '"}\n')
    _write(frozen / "items.jsonl", '{"text": "' + leak + '"}\n')
    monkeypatch.setattr(contamination, "data_dir", lambda model: train)
    monkeypatch.setattr(contamination, "frozen_dir", lambda model: frozen)

    result = contamination.check("doug-a")
    assert result["clean"] is False
    assert result["exact_leaks"]
    assert result["max_containment"] > 0


def test_unrelated_text_is_clean(tmp_path, monkeypatch):
    train = tmp_path / "data"
    frozen = tmp_path / "frozen"
    _write(
        train / "seed.jsonl",
        '{"text": "a dispatcher books a refrigerated load for a bakery chain"}\n',
    )
    _write(frozen / "items.jsonl", '{"text": "the parser rejects an empty configuration file"}\n')
    monkeypatch.setattr(contamination, "data_dir", lambda model: train)
    monkeypatch.setattr(contamination, "frozen_dir", lambda model: frozen)

    result = contamination.check("doug-a")
    assert result["clean"] is True
    assert result["max_containment"] == 0


def test_real_repository_sets_are_clean():
    for model in ("doug-a", "doug-l"):
        result = contamination.check(model)
        assert result["clean"], result["reasons"]
