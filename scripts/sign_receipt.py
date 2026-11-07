"""Compact JWS (EdDSA / Ed25519) receipts for the DOUGLAS registry.

Private key file: one line, base64url of the 32-byte Ed25519 seed.
Public key file:  one line, base64url of the 32-byte public key.

    python -m scripts.sign_receipt keygen --priv ~/.config/douglas/signing_key \
        --pub registry/verification_key.pub
    python -m scripts.sign_receipt sign --payload payload.json --key ~/.config/douglas/signing_key
    python -m scripts.sign_receipt verify --receipt receipt.jws \
        --pub registry/verification_key.pub
"""

from __future__ import annotations

import argparse
import base64
import json
import secrets
import sys
from pathlib import Path

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

from scripts.common import atomic_write, canonical_json, load_json

HEADER_TYP = "JWS"


# --------------------------------------------------------------------------- #
# encoding helpers
# --------------------------------------------------------------------------- #
def b64u_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def b64u_decode(text: str) -> bytes:
    pad = "=" * (-len(text) % 4)
    return base64.urlsafe_b64decode(text + pad)


def key_id(public_bytes: bytes) -> str:
    import hashlib

    return "ed25519-" + hashlib.sha256(public_bytes).hexdigest()[:16]


# --------------------------------------------------------------------------- #
# keys
# --------------------------------------------------------------------------- #
def generate_keypair(priv_path: Path | str, pub_path: Path | str) -> str:
    priv_path = Path(priv_path)
    pub_path = Path(pub_path)
    seed = secrets.token_bytes(32)
    private = Ed25519PrivateKey.from_private_bytes(seed)
    public = private.public_key().public_bytes_raw()
    priv_path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write(priv_path, b64u_encode(seed) + "\n")
    priv_path.chmod(0o600)
    atomic_write(pub_path, b64u_encode(public) + "\n")
    return b64u_encode(public)


def load_private_key_text(text: str) -> Ed25519PrivateKey:
    raw = b64u_decode(text.strip())
    if len(raw) != 32:
        raise ValueError("expected a 32-byte Ed25519 seed")
    return Ed25519PrivateKey.from_private_bytes(raw)


def load_private_key(path: Path | str) -> Ed25519PrivateKey:
    return load_private_key_text(Path(path).read_text(encoding="utf-8"))


def load_public_key(path: Path | str) -> Ed25519PublicKey:
    raw = b64u_decode(Path(path).read_text(encoding="utf-8").strip())
    if len(raw) != 32:
        raise ValueError(f"{path}: expected a 32-byte Ed25519 public key")
    return Ed25519PublicKey.from_public_bytes(raw)


def public_key_b64(path: Path | str) -> str:
    return Path(path).read_text(encoding="utf-8").strip()


# --------------------------------------------------------------------------- #
# sign / verify
# --------------------------------------------------------------------------- #
def sign_payload(payload: dict, private: Ed25519PrivateKey) -> str:
    public_bytes = private.public_key().public_bytes_raw()
    header = {"alg": "EdDSA", "typ": HEADER_TYP, "kid": key_id(public_bytes)}
    signing_input = (
        b64u_encode(canonical_json(header)) + "." + b64u_encode(canonical_json(payload))
    ).encode("ascii")
    signature = private.sign(signing_input)
    return signing_input.decode("ascii") + "." + b64u_encode(signature)


def verify_receipt(receipt: str, public: Ed25519PublicKey) -> dict:
    try:
        header_b64, payload_b64, signature_b64 = receipt.strip().split(".")
    except ValueError as exc:
        raise ValueError("receipt is not a compact JWS") from exc
    signing_input = f"{header_b64}.{payload_b64}".encode("ascii")
    try:
        public.verify(b64u_decode(signature_b64), signing_input)
    except InvalidSignature as exc:
        raise ValueError("receipt signature is invalid") from exc
    header = json.loads(b64u_decode(header_b64))
    if header.get("alg") != "EdDSA":
        raise ValueError(f"unexpected JWS alg {header.get('alg')!r}")
    return json.loads(b64u_decode(payload_b64))


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    p_keygen = sub.add_parser("keygen", help="generate an Ed25519 key pair")
    p_keygen.add_argument("--priv", required=True)
    p_keygen.add_argument("--pub", required=True)

    p_sign = sub.add_parser("sign", help="sign a JSON payload")
    p_sign.add_argument("--payload", required=True)
    p_sign.add_argument("--key", required=True)
    p_sign.add_argument("--out")

    p_verify = sub.add_parser("verify", help="verify a compact JWS receipt")
    p_verify.add_argument("--receipt", required=True)
    p_verify.add_argument("--pub", required=True)

    args = parser.parse_args(argv)

    if args.command == "keygen":
        pub = generate_keypair(args.priv, args.pub)
        print(pub)
        return 0

    if args.command == "sign":
        payload = load_json(args.payload)
        receipt = sign_payload(payload, load_private_key(args.key))
        if args.out:
            atomic_write(args.out, receipt + "\n")
        else:
            print(receipt)
        return 0

    payload = verify_receipt(
        Path(args.receipt).read_text(encoding="utf-8"),
        load_public_key(args.pub),
    )
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
