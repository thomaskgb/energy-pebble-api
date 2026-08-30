#!/usr/bin/env python3
"""
Unit tests for device-record retention.

Device rows carry the only network-identifying data the project holds: an IP
address, a user agent, and a fingerprint derived from them. The privacy page
promises they are removed after a year of silence, so these tests exist to keep
that promise and the code from drifting apart.

Runs offline (no live server, no Elia calls):
    ENERGY_PEBBLE_DATA_DIR=$(mktemp -d) pytest tests/test_retention.py
"""

import os
import sqlite3
import sys
import tempfile
from datetime import timedelta
from pathlib import Path

import pytest
import pytz

os.environ.setdefault("ENERGY_PEBBLE_DATA_DIR", tempfile.mkdtemp(prefix="pebble-test-"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import main  # noqa: E402
from datetime import datetime  # noqa: E402


@pytest.fixture(autouse=True)
def clean_devices():
    with sqlite3.connect(main.DB_PATH) as conn:
        conn.execute("DELETE FROM user_devices")
        conn.execute("DELETE FROM devices")
        conn.commit()
    main._last_device_prune = 0.0
    yield


def add_device(fingerprint, days_ago, claimed_by=None):
    """Insert a device last seen `days_ago` days back, optionally claimed."""
    seen = datetime.now(pytz.UTC) - timedelta(days=days_ago)
    with sqlite3.connect(main.DB_PATH) as conn:
        cursor = conn.execute(
            "INSERT INTO devices (client_ip, device_fingerprint, user_agent, last_seen) "
            "VALUES (?, ?, ?, ?)",
            ("192.0.2.1", fingerprint, "ESP32HTTPClient", seen.strftime("%Y-%m-%d %H:%M:%S")),
        )
        device_row = cursor.lastrowid
        if claimed_by:
            conn.execute(
                "INSERT INTO user_devices (user_id, device_id, nickname) VALUES (?, ?, ?)",
                (claimed_by, device_row, "Kitchen"),
            )
        conn.commit()
    return device_row


def device_ids():
    with sqlite3.connect(main.DB_PATH) as conn:
        return {row[0] for row in conn.execute("SELECT id FROM devices").fetchall()}


def claim_count():
    with sqlite3.connect(main.DB_PATH) as conn:
        return conn.execute("SELECT COUNT(*) FROM user_devices").fetchone()[0]


def test_a_device_seen_recently_is_kept():
    kept = add_device("fresh", days_ago=5)
    assert main.prune_device_records() == 0
    assert device_ids() == {kept}


def test_a_device_unseen_for_over_a_year_is_removed():
    stale = add_device("stale", days_ago=main.DEVICE_RETENTION_DAYS + 10)
    assert main.prune_device_records() == 1
    assert stale not in device_ids()


def test_the_boundary_is_the_retention_window():
    """A day inside the window survives; a day outside it does not."""
    inside = add_device("inside", days_ago=main.DEVICE_RETENTION_DAYS - 1)
    outside = add_device("outside", days_ago=main.DEVICE_RETENTION_DAYS + 1)
    main.prune_device_records()
    remaining = device_ids()
    assert inside in remaining
    assert outside not in remaining


def test_removing_a_device_removes_its_claim_too():
    """Otherwise user_devices keeps a row pointing at a device that is gone."""
    add_device("stale", days_ago=main.DEVICE_RETENTION_DAYS + 10, claimed_by="nele")
    assert claim_count() == 1
    main.prune_device_records()
    assert claim_count() == 0


def test_a_live_device_keeps_its_claim():
    add_device("fresh", days_ago=1, claimed_by="nele")
    main.prune_device_records()
    assert claim_count() == 1


def test_pruning_an_empty_table_is_harmless():
    assert main.prune_device_records() == 0


def test_the_sweep_runs_at_most_once_a_day():
    add_device("stale", days_ago=main.DEVICE_RETENTION_DAYS + 10)
    main.maybe_prune_device_records()
    assert device_ids() == set()

    # A second stale device arriving right afterwards waits for the next window.
    survivor = add_device("stale2", days_ago=main.DEVICE_RETENTION_DAYS + 10)
    main.maybe_prune_device_records()
    assert survivor in device_ids()

    # ...and is collected once the interval has passed.
    main._last_device_prune -= main.DEVICE_PRUNE_INTERVAL_SECONDS + 1
    main.maybe_prune_device_records()
    assert survivor not in device_ids()


def test_a_failing_sweep_does_not_break_the_request_path():
    """log_device_request calls this; a retention problem must not 500 a pebble."""
    original = main.prune_device_records
    main.prune_device_records = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom"))
    try:
        main.maybe_prune_device_records()  # must not raise
    finally:
        main.prune_device_records = original


def test_the_retention_window_matches_what_the_privacy_page_says():
    """The promise and the code must move together.

    The privacy page tells people their device records are deleted after
    twelve months of silence. Shortening or lengthening the window here
    without rewriting that sentence turns it into a false statement, so this
    test fails until both have been changed.
    """
    assert main.DEVICE_RETENTION_DAYS == 365, (
        "retention changed: update privacy.keep.device in all three catalogs"
    )
    catalog = (Path(__file__).resolve().parent.parent / "static" / "i18n-strings.js")
    assert "twelve months without a single connection" in catalog.read_text(encoding="utf-8")


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
