#!/usr/bin/env python3
"""
Unit tests for OTA update selection (get_latest_firmware_for_device).

Regression cover for the bug where a device running v1.0.0 was told "you're
running the latest firmware" while v1.2.0 sat in the table: the query took a
single row ordered by release_date and only then asked whether it was newer,
so one ineligible row hid every eligible one behind it.

Runs offline (no live server, no hardware):
    ENERGY_PEBBLE_DATA_DIR=$(mktemp -d) pytest tests/test_ota_check.py
"""

import os
import sqlite3
import sys
import tempfile
from pathlib import Path

import pytest

# Point main.py at a throwaway data dir before importing it (it initializes
# the database at import time).
os.environ.setdefault("ENERGY_PEBBLE_DATA_DIR", tempfile.mkdtemp(prefix="pebble-ota-test-"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import main  # noqa: E402

DEVICE = "b8f862d86868"
SIGNATURE = "c2lnbmF0dXJlLXBsYWNlaG9sZGVy"  # any non-empty base64; never verified here


@pytest.fixture(autouse=True)
def firmware_storage(tmp_path, monkeypatch):
    """Isolate the firmware table and give every row a real file on disk."""
    with sqlite3.connect(main.DB_PATH) as conn:
        conn.execute("DELETE FROM firmware_versions")
        conn.commit()

    storage = tmp_path / "firmware"
    storage.mkdir()
    monkeypatch.setattr(main, "get_firmware_storage_path", lambda: storage)
    # Default to a server that holds a verification key, matching production.
    monkeypatch.setenv(main.firmware_signing.PUBKEY_ENV, "ab" * 32)
    return storage


def add_firmware(version, release_date, *, md5="d41d8cd98f00b204e9800998ecf8427e",
                 signature=SIGNATURE, signature_alg="ed25519", is_stable=True,
                 min_version=None, target_devices=None, on_disk=True):
    filename = f"energy_pebble_{version}.bin"
    if on_disk:
        (main.get_firmware_storage_path() / filename).write_bytes(b"firmware")
    with sqlite3.connect(main.DB_PATH) as conn:
        conn.execute(
            """
            INSERT INTO firmware_versions
                (version, filename, checksum, md5_checksum, signature, signature_alg,
                 file_size, release_date, is_stable, force_update, min_version, target_devices)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?)
            """,
            (version, filename, f"sha256:{'a' * 64}", md5, signature, signature_alg,
             1024, release_date, is_stable, min_version, target_devices),
        )
        conn.commit()


def offered(current_version, device_id=DEVICE):
    result = main.get_latest_firmware_for_device(device_id, current_version)
    return result["version"] if result else None


# --------------------------------------------------------------- the reported bug

def test_tied_release_dates_offer_the_highest_version():
    """The three seeded rows share one release_date; v1.0.0 must not win."""
    for version in ("v1.0.0", "v1.1.0", "v1.2.0"):
        add_firmware(version, "2025-11-12 10:28:12")

    assert offered("v1.0.0") == "v1.2.0"
    assert offered("v0.0.1") == "v1.2.0"
    assert offered("v1.1.0") == "v1.2.0"


def test_device_on_newest_version_gets_nothing():
    for version in ("v1.0.0", "v1.1.0", "v1.2.0"):
        add_firmware(version, "2025-11-12 10:28:12")

    assert offered("v1.2.0") is None
    assert offered("v3.0.0") is None


def test_newer_version_released_earlier_is_still_offered():
    """A backfilled or re-dated row must not mask a higher version."""
    add_firmware("v3.0.0", "2025-01-01 00:00:00")
    add_firmware("v2.0.5", "2026-08-30 12:00:00")

    assert offered("v2.0.5") == "v3.0.0"


def test_version_ordering_is_numeric_not_lexicographic():
    add_firmware("v2.9.0", "2026-01-01 00:00:00")
    add_firmware("v2.10.0", "2026-01-01 00:00:00")

    assert offered("v2.0.0") == "v2.10.0"


# ------------------------------------------------------- uninstallable candidates

def test_placeholder_row_without_md5_is_skipped():
    """The seeded rows carry no md5; the device aborts the flash without one."""
    add_firmware("v1.2.0", "2025-11-12 10:28:12", md5=None)
    add_firmware("v1.1.0", "2025-11-12 10:28:12")

    assert offered("v1.0.0") == "v1.1.0"


def test_unsigned_row_is_skipped_when_server_holds_a_key():
    add_firmware("v1.2.0", "2025-11-12 10:28:12", signature=None, signature_alg=None)
    add_firmware("v1.1.0", "2025-11-12 10:28:12")

    assert offered("v1.0.0") == "v1.1.0"


def test_unsigned_row_is_allowed_when_no_key_is_configured(monkeypatch):
    monkeypatch.delenv(main.firmware_signing.PUBKEY_ENV, raising=False)
    add_firmware("v1.2.0", "2025-11-12 10:28:12", signature=None, signature_alg=None)

    assert offered("v1.0.0") == "v1.2.0"


def test_unknown_signature_algorithm_is_skipped():
    add_firmware("v1.2.0", "2025-11-12 10:28:12", signature_alg="rsa-pss")
    add_firmware("v1.1.0", "2025-11-12 10:28:12")

    assert offered("v1.0.0") == "v1.1.0"


def test_row_whose_binary_is_missing_is_skipped():
    """Offering it would hand the device a /firmware/... URL that 404s."""
    add_firmware("v1.2.0", "2025-11-12 10:28:12", on_disk=False)
    add_firmware("v1.1.0", "2025-11-12 10:28:12")

    assert offered("v1.0.0") == "v1.1.0"


def test_no_installable_candidate_returns_none():
    add_firmware("v1.2.0", "2025-11-12 10:28:12", on_disk=False)

    assert offered("v1.0.0") is None


# ------------------------------------------------------------- existing filters

def test_unstable_release_is_not_offered():
    add_firmware("v1.2.0", "2025-11-12 10:28:12", is_stable=False)
    add_firmware("v1.1.0", "2025-11-12 10:28:12")

    assert offered("v1.0.0") == "v1.1.0"


def test_min_version_gate_skips_only_the_gated_row():
    add_firmware("v1.2.0", "2025-11-12 10:28:12", min_version="v1.1.0")
    add_firmware("v1.1.0", "2025-11-12 10:28:12")

    # Too old for v1.2.0, but v1.1.0 is still a valid step up.
    assert offered("v1.0.0") == "v1.1.0"
    assert offered("v1.1.0") == "v1.2.0"


def test_targeted_release_reaches_only_its_device():
    add_firmware("v1.2.0", "2025-11-12 10:28:12", target_devices=f'["{DEVICE}"]')

    assert offered("v1.0.0") == "v1.2.0"
    assert offered("v1.0.0", device_id="aabbccddeeff") is None


# ------------------------------------------------------------- database seeding

def test_fresh_database_has_no_firmware_rows(tmp_path, monkeypatch):
    """A new deployment must not invent releases it has no binaries for."""
    monkeypatch.setattr(main, "DB_PATH", tmp_path / "fresh.db")
    main.init_database()

    with sqlite3.connect(main.DB_PATH) as conn:
        rows = conn.execute("SELECT version FROM firmware_versions").fetchall()

    assert rows == []


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
