"""Shared pytest fixtures."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


@pytest.fixture
def repo_root() -> Path:
    return ROOT


def tamper_receipt(receipt: str) -> str:
    """Flip the first byte of a JWS signature so verification always fails.

    Replacing trailing base64 characters is unreliable: base64url's unused
    trailing bits can make two different strings decode to the same signature.
    """
    from scripts.sign_receipt import b64u_decode, b64u_encode

    header, body, signature = receipt.split(".")
    raw = bytearray(b64u_decode(signature))
    raw[0] ^= 0x01
    return f"{header}.{body}.{b64u_encode(bytes(raw))}"
