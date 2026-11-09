from __future__ import annotations

import pytest

from scripts import train_remote


class _FlakyTrainer:
    def __init__(self, failures: int):
        self.failures = failures
        self.calls = 0

    def push_to_hub(self):
        self.calls += 1
        if self.calls <= self.failures:
            raise RuntimeError("429 Too Many Requests")


def test_push_with_retries_backs_off_then_succeeds(monkeypatch):
    sleeps: list[int] = []
    monkeypatch.setattr(train_remote.time, "sleep", sleeps.append)
    trainer = _FlakyTrainer(failures=2)

    train_remote.push_with_retries(trainer)

    assert trainer.calls == 3
    assert sleeps == [15, 30]


def test_push_with_retries_raises_after_last_attempt(monkeypatch):
    monkeypatch.setattr(train_remote.time, "sleep", lambda _: None)
    trainer = _FlakyTrainer(failures=4)

    with pytest.raises(RuntimeError, match="429"):
        train_remote.push_with_retries(trainer)
    assert trainer.calls == 4
