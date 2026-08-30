"""Firmware signing and verification (Ed25519).

Trust model
-----------
The private signing key lives OFFLINE (a release manager's machine or a CI
secret) and never touches the server. The server and every device hold only the
PUBLIC key. A release is signed at build time; the server verifies the signature
on upload and re-serves it; the device verifies it again against its embedded
public key before flashing.

The point of this is defence in depth: even an attacker who obtains admin on the
API (see security finding C1) cannot push firmware a device will accept, because
they cannot produce a valid Ed25519 signature without the offline private key.

Signature scope
---------------
The signature is computed over the raw firmware binary bytes. Verifiers must
recompute over the exact bytes they will flash (or, on the server, the exact
bytes written to disk), never over an uploader-supplied hash.

CLI
---
    python firmware_signing.py keygen [--out-dir DIR]
        Generate a fresh keypair. Writes firmware_signing_private.pem (keep
        offline!) and prints the public key in the format the server/device
        expect.

    python firmware_signing.py sign FIRMWARE.bin --key PRIVATE.pem
        Print the base64 Ed25519 signature for a firmware binary. Use this in
        the release/CI step and pass the result to /api/firmware/upload as the
        `signature` form field.

    python firmware_signing.py verify FIRMWARE.bin --sig SIG --pubkey HEX
        Verify a signature locally (for debugging).
"""
from __future__ import annotations

import argparse
import base64
import os
import sys
from pathlib import Path
from typing import Optional

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

SIGNATURE_ALG = "ed25519"

# Env var holding the public key (64 hex chars = 32 raw bytes) used by the
# server to verify uploads. When unset, the server falls back to checksum-only
# integrity and logs a warning; this keeps existing deployments working until a
# key is provisioned and the release pipeline starts signing.
PUBKEY_ENV = "FIRMWARE_SIGNING_PUBKEY"


def _read_bytes(path: Path) -> bytes:
    with open(path, "rb") as f:
        return f.read()


def public_key_from_hex(hex_key: str) -> Ed25519PublicKey:
    """Load an Ed25519 public key from a 64-char hex string (raw 32 bytes)."""
    raw = bytes.fromhex(hex_key.strip())
    if len(raw) != 32:
        raise ValueError(
            f"Ed25519 public key must be 32 bytes (64 hex chars), got {len(raw)}"
        )
    return Ed25519PublicKey.from_public_bytes(raw)


def public_key_to_hex(pub: Ed25519PublicKey) -> str:
    raw = pub.public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    return raw.hex()


def load_server_public_key() -> Optional[Ed25519PublicKey]:
    """Load the verification key from the environment, or None if unconfigured."""
    hex_key = os.environ.get(PUBKEY_ENV, "").strip()
    if not hex_key:
        return None
    return public_key_from_hex(hex_key)


def sign_bytes(private_key: Ed25519PrivateKey, data: bytes) -> str:
    """Return a base64-encoded Ed25519 signature over `data`."""
    return base64.b64encode(private_key.sign(data)).decode("ascii")


def verify_bytes(public_key: Ed25519PublicKey, data: bytes, signature_b64: str) -> bool:
    """Verify a base64 Ed25519 signature over `data`. Never raises."""
    try:
        public_key.verify(base64.b64decode(signature_b64), data)
        return True
    except (InvalidSignature, ValueError, TypeError):
        return False


def verify_file(public_key: Ed25519PublicKey, path: Path, signature_b64: str) -> bool:
    return verify_bytes(public_key, _read_bytes(path), signature_b64)


# --------------------------------------------------------------------------- CLI


def _cmd_keygen(args: argparse.Namespace) -> int:
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    priv_path = out_dir / "firmware_signing_private.pem"
    if priv_path.exists() and not args.force:
        print(f"Refusing to overwrite existing {priv_path} (use --force)", file=sys.stderr)
        return 1

    private_key = Ed25519PrivateKey.generate()
    pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    with open(priv_path, "wb") as f:
        f.write(pem)
    os.chmod(priv_path, 0o600)

    pub_hex = public_key_to_hex(private_key.public_key())
    print(f"Private key written to: {priv_path}  (KEEP THIS OFFLINE, do not commit)")
    print()
    print("Public key (32-byte hex). Set on the server and embed in firmware:")
    print(f"  {PUBKEY_ENV}={pub_hex}")
    return 0


def _load_private_key(path: Path) -> Ed25519PrivateKey:
    key = serialization.load_pem_private_key(_read_bytes(path), password=None)
    if not isinstance(key, Ed25519PrivateKey):
        raise ValueError("Provided key is not an Ed25519 private key")
    return key


def _cmd_sign(args: argparse.Namespace) -> int:
    private_key = _load_private_key(Path(args.key))
    sig = sign_bytes(private_key, _read_bytes(Path(args.firmware)))
    print(sig)
    return 0


def _cmd_verify(args: argparse.Namespace) -> int:
    pub = public_key_from_hex(args.pubkey)
    ok = verify_file(pub, Path(args.firmware), args.sig)
    print("OK" if ok else "INVALID")
    return 0 if ok else 2


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Ed25519 firmware signing utility")
    sub = parser.add_subparsers(dest="command", required=True)

    p_keygen = sub.add_parser("keygen", help="Generate a signing keypair")
    p_keygen.add_argument("--out-dir", default=".", help="Directory to write the private key")
    p_keygen.add_argument("--force", action="store_true", help="Overwrite an existing key")
    p_keygen.set_defaults(func=_cmd_keygen)

    p_sign = sub.add_parser("sign", help="Sign a firmware binary")
    p_sign.add_argument("firmware", help="Path to the .bin file")
    p_sign.add_argument("--key", required=True, help="Path to the PEM private key")
    p_sign.set_defaults(func=_cmd_sign)

    p_verify = sub.add_parser("verify", help="Verify a firmware signature")
    p_verify.add_argument("firmware", help="Path to the .bin file")
    p_verify.add_argument("--sig", required=True, help="Base64 signature")
    p_verify.add_argument("--pubkey", required=True, help="Public key (64 hex chars)")
    p_verify.set_defaults(func=_cmd_verify)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
