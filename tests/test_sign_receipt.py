from __future__ import annotations

import json

import pytest

from scripts.sign_receipt import (
    generate_keypair,
    load_private_key,
    load_public_key,
    sign_payload,
    verify_receipt,
)


def test_sign_and_verify(tmp_path):
    priv = tmp_path / "key"
    pub = tmp_path / "key.pub"
    generate_keypair(priv, pub)
    assert priv.stat().st_mode & 0o777 == 0o600

    payload = {"model_id": "doug-a", "seeds": [1, 2, 3], "score": 0.71}
    receipt = sign_payload(payload, load_private_key(priv))
    assert receipt.count(".") == 2
    assert verify_receipt(receipt, load_public_key(pub)) == payload


def test_tampered_payload_fails(tmp_path):
    priv = tmp_path / "key"
    pub = tmp_path / "key.pub"
    generate_keypair(priv, pub)
    receipt = sign_payload({"score": 0.1}, load_private_key(priv))
    header, payload, signature = receipt.split(".")
    forged = json.dumps({"score": 0.99}).encode()
    import base64

    forged_b64 = base64.urlsafe_b64encode(forged).rstrip(b"=").decode()
    tampered = f"{header}.{forged_b64}.{signature}"
    with pytest.raises(ValueError, match="signature"):
        verify_receipt(tampered, load_public_key(pub))


def test_canonical_payload_is_key_order_independent(tmp_path):
    priv = tmp_path / "key"
    generate_keypair(priv, tmp_path / "key.pub")
    key = load_private_key(priv)
    a = sign_payload({"b": 1, "a": 2}, key)
    b = sign_payload({"a": 2, "b": 1}, key)
    assert a == b


def test_wrong_key_fails(tmp_path):
    priv_a = tmp_path / "a"
    pub_a = tmp_path / "a.pub"
    priv_b = tmp_path / "b"
    pub_b = tmp_path / "b.pub"
    generate_keypair(priv_a, pub_a)
    generate_keypair(priv_b, pub_b)
    receipt = sign_payload({"x": 1}, load_private_key(priv_a))
    with pytest.raises(ValueError, match="signature"):
        verify_receipt(receipt, load_public_key(pub_b))
