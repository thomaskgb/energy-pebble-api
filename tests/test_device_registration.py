"""
Tests for the passive registration path: which callers get a devices row.

A device announces itself with an X-Device-ID header on an ordinary
/api/color-code call, and that is enough to create a record. That door used
to accept any string, so a test script sending "test-Kitchen Pebble" filled
the admin console with devices that were never built. And two pebbles in one
household collided on the fingerprint, so the second one vanished.
"""
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import main  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

client = TestClient(main.app)

# Reserved ids, cleaned up after every test.
ONE = "ddddeeee0001"
TWO = "ddddeeee0002"
SHARED_AGENT = "ESP32-HTTPClient/1.0"


def cleanup():
    with sqlite3.connect(main.DB_PATH) as conn:
        cur = conn.cursor()
        cur.execute("DELETE FROM devices WHERE device_id IN (?, ?)", (ONE, TWO))
        conn.commit()


def setup_function():
    cleanup()


def teardown_function():
    cleanup()


def announce(device_id, user_agent=SHARED_AGENT):
    return client.get("/api/color-code",
                      headers={"X-Device-ID": device_id, "User-Agent": user_agent})


def registered_ids():
    with sqlite3.connect(main.DB_PATH) as conn:
        return {row[0] for row in
                conn.execute("SELECT device_id FROM devices").fetchall()}


def test_normalise_accepts_only_efuse_shaped_ids():
    assert main.normalise_device_id("AA00CC00EE01") == "aa00cc00ee01"
    assert main.normalise_device_id("  aa00cc00ee01 ") == "aa00cc00ee01"
    assert main.normalise_device_id("test-Kitchen Pebble") is None
    assert main.normalise_device_id("aa00cc00ee0") is None      # 11 chars
    assert main.normalise_device_id("aa00cc00ee012") is None    # 13 chars
    assert main.normalise_device_id("zz00cc00ee01") is None     # not hex
    assert main.normalise_device_id("") is None
    assert main.normalise_device_id(None) is None


def test_junk_device_id_creates_no_record():
    """The bug that put "test-Kitchen Pebble" on the admin page."""
    before = registered_ids()
    for junk in ("test-Kitchen Pebble", "aa00cc00ee0", "zz00cc00ee01"):
        assert announce(junk).status_code == 200
    assert registered_ids() == before


def test_real_device_id_creates_a_record():
    assert announce(ONE).status_code == 200
    assert ONE in registered_ids()
    assert main.generate_mac_from_device_id(ONE) != "00:00:00:00:00:00"


def test_uppercase_id_folds_into_the_same_record():
    announce(ONE)
    announce(ONE.upper())
    with sqlite3.connect(main.DB_PATH) as conn:
        rows = conn.execute(
            "SELECT request_count FROM devices WHERE device_id=?", (ONE,)
        ).fetchall()
    assert rows == [(2,)]


def test_two_devices_on_one_network_both_register():
    """
    Same IP, same user agent, same hour: the three inputs the fingerprint used
    to be built from. The second device's INSERT was dropped by INSERT OR
    IGNORE on the UNIQUE fingerprint and it never appeared anywhere.
    """
    announce(ONE)
    announce(TWO)
    assert {ONE, TWO} <= registered_ids()

    with sqlite3.connect(main.DB_PATH) as conn:
        fingerprints = {row[0] for row in conn.execute(
            "SELECT device_fingerprint FROM devices WHERE device_id IN (?, ?)",
            (ONE, TWO)).fetchall()}
    assert len(fingerprints) == 2
