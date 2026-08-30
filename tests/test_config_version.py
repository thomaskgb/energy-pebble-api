#!/usr/bin/env python3
"""
Tests for /api/device/config-version: the tiny settings-change probe that
firmware polls every 30 seconds to decide whether to refetch colors.

Runs offline (no live server, no Elia calls):
    ENERGY_PEBBLE_DATA_DIR=$(mktemp -d) pytest tests/test_config_version.py
"""

import os
import sqlite3
import sys
import tempfile
from pathlib import Path

import pytest

# Point main.py at a throwaway data dir before importing it (it initializes
# the database at import time).
os.environ.setdefault("ENERGY_PEBBLE_DATA_DIR", tempfile.mkdtemp(prefix="pebble-test-"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient  # noqa: E402
import main  # noqa: E402

client = TestClient(main.app)


@pytest.fixture(autouse=True)
def clean_settings():
    yield
    with sqlite3.connect(main.DB_PATH) as conn:
        conn.execute("DELETE FROM user_settings")
        conn.execute("DELETE FROM user_devices")
        conn.execute("DELETE FROM devices")
        conn.execute("DELETE FROM home_settings")
        conn.execute("DELETE FROM homes")
        conn.commit()


def _headers(user):
    return {"Remote-User": user}


def _make_claimed_device(user, device_id, ip="9.9.9.9"):
    """Insert a device assigned to the user's default home."""
    home_id = main.get_or_create_default_home(user)
    with sqlite3.connect(main.DB_PATH) as conn:
        conn.execute(
            "INSERT INTO devices (client_ip, device_fingerprint, device_id, home_id) VALUES (?, ?, ?, ?)",
            (ip, f"fp-{device_id}", device_id, home_id))
        conn.commit()
    return home_id


def _version(device_id=None, header=None):
    params = {"device_id": device_id} if device_id else {}
    headers = {"X-Device-ID": header} if header else {}
    resp = client.get("/api/device/config-version", params=params, headers=headers)
    assert resp.status_code == 200
    return resp.json()


def test_unknown_device_gets_stable_default_version():
    a = _version("aaaaaaaaaaaa")
    b = _version("aaaaaaaaaaaa")
    no_id = _version()
    assert a["personalized"] is False
    assert a["version"] == b["version"] == no_id["version"]


def test_version_changes_when_settings_saved():
    _make_claimed_device("gina", "101112131415")
    before = _version("101112131415")
    assert before["personalized"] is True

    client.put("/api/user/settings", headers=_headers("gina"), json={"has_solar": True})
    after = _version("101112131415")
    assert after["version"] != before["version"]

    # unchanged settings -> unchanged version (no spurious refetches)
    assert _version("101112131415")["version"] == after["version"]


def test_no_op_save_keeps_version():
    _make_claimed_device("gina", "101112131415")
    client.put("/api/user/settings", headers=_headers("gina"), json={"has_battery": True})
    before = _version("101112131415")
    client.put("/api/user/settings", headers=_headers("gina"), json={"has_battery": True})
    assert _version("101112131415")["version"] == before["version"]


def test_x_device_id_header_matches_query_param():
    _make_claimed_device("gina", "101112131415")
    client.put("/api/user/settings", headers=_headers("gina"), json={"has_solar": True})
    assert _version(header="101112131415") == _version("101112131415")


def test_other_users_device_unaffected_by_save():
    _make_claimed_device("gina", "101112131415")
    _make_claimed_device("erin", "161718192021", ip="8.8.8.8")
    erin_before = _version("161718192021")
    client.put("/api/user/settings", headers=_headers("gina"), json={"has_solar": True})
    assert _version("161718192021")["version"] == erin_before["version"]
