"""Unit tests for firmware_signing (offline, no server or hardware needed).

Run with pytest, or directly: python tests/test_firmware_signing.py
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

import firmware_signing as fs


FIRMWARE = b"\x00\x01ENERGY-PEBBLE-FIRMWARE\xffpadding" * 64


def _keypair():
    priv = Ed25519PrivateKey.generate()
    pub = priv.public_key()
    return priv, pub


def test_sign_verify_roundtrip():
    priv, pub = _keypair()
    sig = fs.sign_bytes(priv, FIRMWARE)
    assert fs.verify_bytes(pub, FIRMWARE, sig) is True


def test_tampered_firmware_fails():
    priv, pub = _keypair()
    sig = fs.sign_bytes(priv, FIRMWARE)
    tampered = FIRMWARE[:-1] + b"\x00"
    assert fs.verify_bytes(pub, tampered, sig) is False


def test_wrong_key_fails():
    priv, _ = _keypair()
    _, other_pub = _keypair()
    sig = fs.sign_bytes(priv, FIRMWARE)
    assert fs.verify_bytes(other_pub, FIRMWARE, sig) is False


def test_garbage_signature_never_raises():
    _, pub = _keypair()
    for bad in ["", "not-base64!!", "YWJj", "x" * 200]:
        assert fs.verify_bytes(pub, FIRMWARE, bad) is False


def test_public_key_hex_roundtrip():
    _, pub = _keypair()
    hex_key = fs.public_key_to_hex(pub)
    assert len(hex_key) == 64
    restored = fs.public_key_from_hex(hex_key)
    sig_priv, sig_pub = _keypair()
    sig = fs.sign_bytes(sig_priv, FIRMWARE)
    # restored key is a real Ed25519 key usable for verification
    assert fs.verify_bytes(sig_pub, FIRMWARE, sig) is True
    assert fs.public_key_to_hex(restored) == hex_key


def test_bad_hex_length_rejected():
    for bad in ["", "ab", "zz" * 32]:
        try:
            fs.public_key_from_hex(bad)
        except ValueError:
            continue
        raise AssertionError(f"expected ValueError for {bad!r}")


def test_load_server_public_key_env(monkeypatch=None):
    _, pub = _keypair()
    hex_key = fs.public_key_to_hex(pub)
    old = os.environ.get(fs.PUBKEY_ENV)
    try:
        os.environ.pop(fs.PUBKEY_ENV, None)
        assert fs.load_server_public_key() is None
        os.environ[fs.PUBKEY_ENV] = hex_key
        loaded = fs.load_server_public_key()
        assert loaded is not None
        assert fs.public_key_to_hex(loaded) == hex_key
    finally:
        if old is None:
            os.environ.pop(fs.PUBKEY_ENV, None)
        else:
            os.environ[fs.PUBKEY_ENV] = old


def test_verify_file(tmp_path=None):
    import tempfile
    priv, pub = _keypair()
    sig = fs.sign_bytes(priv, FIRMWARE)
    with tempfile.NamedTemporaryFile(suffix=".bin", delete=False) as f:
        f.write(FIRMWARE)
        path = Path(f.name)
    try:
        assert fs.verify_file(pub, path, sig) is True
    finally:
        path.unlink()


if __name__ == "__main__":
    passed = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"  PASS {name}")
            passed += 1
    print(f"\n{passed} tests passed")
