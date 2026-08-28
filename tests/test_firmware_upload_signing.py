"""Integration tests for signed firmware upload + OTA serving.

Drives the real FastAPI handlers through TestClient with an isolated temp DB and
firmware dir, and signing enforced. Offline — no network, no hardware.

Run: python tests/test_firmware_upload_signing.py   (or via pytest)
"""
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

import firmware_signing as fs

ADMIN = {"Remote-User": "thomas", "Remote-Groups": "admins"}
FW_BYTES = os.urandom(50000)


def _client_and_key():
    """Build a TestClient over an isolated DB + firmware dir with signing on."""
    priv = Ed25519PrivateKey.generate()
    os.environ[fs.PUBKEY_ENV] = fs.public_key_to_hex(priv.public_key())

    import main
    tmp = Path(tempfile.mkdtemp())
    main.DB_PATH = tmp / "test.db"
    fw_dir = tmp / "firmware"
    fw_dir.mkdir()
    main.get_firmware_storage_path = lambda: fw_dir
    main.init_database()

    # Drop the placeholder seed rows (dummy checksums, no real binaries) so the
    # fixture has a deterministic, real firmware set to reason about.
    import sqlite3
    with sqlite3.connect(main.DB_PATH) as conn:
        conn.execute("DELETE FROM firmware_versions")
        conn.commit()

    from fastapi.testclient import TestClient
    return TestClient(main.app), priv, main


def _upload(client, version, sig, sha=None):
    data = {"version": version, "product_name": "energy_pebble", "is_stable": "true"}
    if sig is not None:
        data["signature"] = sig
    if sha is not None:
        data["sha256_checksum"] = sha
    return client.post(
        "/api/firmware/upload",
        headers=ADMIN,
        files={"firmware_file": ("energy_pebble_test.bin", FW_BYTES, "application/octet-stream")},
        data=data,
    )


def test_signed_upload_accepted_and_checksum_recomputed():
    client, priv, main = _client_and_key()
    sig = fs.sign_bytes(priv, FW_BYTES)
    r = _upload(client, "v9.9.1", sig)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["signed"] is True and body["signature_verified"] is True
    # stored checksum is the server-computed one over the real bytes
    import hashlib
    expected = "sha256:" + hashlib.sha256(FW_BYTES).hexdigest()
    assert body["checksum"] == expected


def test_unsigned_rejected_when_key_configured():
    client, priv, main = _client_and_key()
    r = _upload(client, "v9.9.2", sig=None)
    assert r.status_code == 400
    assert "signature is required" in r.text.lower()


def test_bad_signature_rejected():
    client, priv, main = _client_and_key()
    other = Ed25519PrivateKey.generate()
    wrong_sig = fs.sign_bytes(other, FW_BYTES)  # valid sig, wrong key
    r = _upload(client, "v9.9.3", wrong_sig)
    assert r.status_code == 400
    assert "invalid firmware signature" in r.text.lower()


def test_supplied_checksum_mismatch_rejected():
    client, priv, main = _client_and_key()
    sig = fs.sign_bytes(priv, FW_BYTES)
    r = _upload(client, "v9.9.4", sig, sha="sha256:" + "de" * 32)
    assert r.status_code == 400
    assert "sha256 mismatch" in r.text.lower()


def test_ota_check_serves_signature():
    client, priv, main = _client_and_key()
    sig = fs.sign_bytes(priv, FW_BYTES)
    assert _upload(client, "v9.9.5", sig).status_code == 200
    r = client.get(
        "/api/ota/check",
        headers={"X-Device-ID": "904fb0453ab4", "X-Current-Version": "v1.0.0"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["update_available"] is True
    assert body["signature"] == sig
    assert body["signature_alg"] == "ed25519"
    # and the served signature verifies against the served binary
    fw = client.get(f"/firmware/{body['download_url'].rsplit('/', 1)[-1]}")
    assert fw.status_code == 200
    assert fs.verify_bytes(priv.public_key(), fw.content, body["signature"]) is True


if __name__ == "__main__":
    passed = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"  PASS {name}")
            passed += 1
    print(f"\n{passed} tests passed")
