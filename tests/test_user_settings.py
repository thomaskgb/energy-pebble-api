#!/usr/bin/env python3
"""
Unit tests for per-user settings: storage, validation, signal-source
transforms, and device resolution.

Runs offline (no live server, no Elia calls):
    ENERGY_PEBBLE_DATA_DIR=$(mktemp -d) pytest tests/test_user_settings.py
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
        conn.execute("DELETE FROM api_tokens")
        conn.commit()


def test_user_token_flow_for_home_assistant():
    # Personal token authenticates as the user, without admin rights
    token, token_id = main.create_user_api_token("erin", "Home Assistant")
    info = main.validate_api_token(token)
    assert info["user_id"] == "erin"
    assert info["is_admin"] is False

    headers = {"Authorization": f"Bearer {token}"}
    assert client.get("/api/ha/me", headers=headers).json()["user_id"] == "erin"

    # Device picker lists only erin's claimed devices
    with sqlite3.connect(main.DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute("INSERT INTO devices (client_ip, device_fingerprint, device_id) VALUES ('1.2.3.4','fp-ha','ddeeff001122')")
        cursor.execute("INSERT INTO user_devices (user_id, device_id, nickname) VALUES ('erin', ?, 'living room')", (cursor.lastrowid,))
        conn.commit()
    devices = client.get("/api/ha/devices", headers=headers).json()["devices"]
    assert devices == [{"device_id": "ddeeff001122", "nickname": "living room",
                        "last_seen": devices[0]["last_seen"]}]

    # Tokens cannot mint tokens; invalid and legacy-system tokens are rejected on /api/ha
    assert client.post("/api/user/tokens", json={}, headers=headers).status_code == 403
    assert client.get("/api/ha/me", headers={"Authorization": "Bearer nonsense"}).status_code in (401, 403)
    system_token, _ = main.create_api_token("ci-token", "admin")
    assert main.validate_api_token(system_token)["is_admin"] is True
    assert client.get("/api/ha/me", headers={"Authorization": f"Bearer {system_token}"}).status_code == 403


def test_user_token_management_endpoints():
    # Via the (dev-shim / Authelia) authenticated dashboard path
    headers = {"Remote-User": "frank"}
    created = client.post("/api/user/tokens", json={"token_name": "HA"}, headers=headers)
    assert created.status_code == 200
    body = created.json()
    assert body["token_name"] == "HA" and body["token"]

    listed = client.get("/api/user/tokens", headers=headers).json()["tokens"]
    assert [t["token_name"] for t in listed] == ["HA"]

    # Revoke: gone from the list, token no longer valid
    assert client.delete(f"/api/user/tokens/{body['id']}", headers=headers).status_code == 200
    assert client.get("/api/user/tokens", headers=headers).json()["tokens"] == []
    assert main.validate_api_token(body["token"]) is None
    # Cannot revoke someone else's token
    assert client.delete(f"/api/user/tokens/{body['id']}", headers={"Remote-User": "mallory"}).status_code == 404


def test_defaults_for_unknown_user():
    settings = main.get_user_settings("nobody")
    assert settings == main.DEFAULT_USER_SETTINGS
    assert main.derive_signal_source(settings) == "price"


def test_derive_signal_source():
    base = dict(main.DEFAULT_USER_SETTINGS)
    assert main.derive_signal_source({**base, "contract_type": "day_night", "has_solar": True}) == "day_night"
    assert main.derive_signal_source({**base, "contract_type": "fixed", "has_solar": True}) == "fixed"
    assert main.derive_signal_source({**base, "contract_type": "fixed"}) == "fixed"


def test_fixed_contract_is_neutral_except_solar():
    codes = _codes([
        ("2026-08-26T10:00:00Z", "R"),   # sunny hour
        ("2026-08-26T17:00:00Z", "G"),   # evening, no sun
    ])
    fixed = {**main.DEFAULT_USER_SETTINGS, "contract_type": "fixed"}
    boost = {"2026-08-26T10:00:00Z"}

    # No solar: nothing varies for a fixed household -> all neutral
    result = [e["color_code"] for e in main.apply_signal_source(codes, fixed, boost)]
    assert result == ["Y", "Y"]

    # With solar: production hours green, rest neutral
    result = [e["color_code"] for e in main.apply_signal_source(
        codes, {**fixed, "has_solar": True}, boost)]
    assert result == ["G", "Y"]


def test_day_night_battery_extends_solar_into_evening():
    settings = {**main.DEFAULT_USER_SETTINGS, "contract_type": "day_night",
                "has_solar": True, "has_battery": True}
    # Wed 2026-08-26 17:00 UTC = 19:00 Brussels: day tariff (Y), in bridge window
    codes = _codes([("2026-08-26T17:00:00Z", "R")])
    charged = {"2026-08-26T09:00:00Z", "2026-08-26T10:00:00Z", "2026-08-26T11:00:00Z"}
    assert main.apply_signal_source(codes, settings, charged)[0]["color_code"] == "G"
    # Grey day: battery empty, day tariff stays
    assert main.apply_signal_source(codes, settings, set())[0]["color_code"] == "Y"


def test_settings_roundtrip_partial_update():
    resp = client.put("/api/test/user/settings?user=alice",
                      json={"has_solar": True, "brightness": 40})
    assert resp.status_code == 200
    body = resp.json()
    assert body["settings"]["has_solar"] is True
    assert body["settings"]["brightness"] == 40
    assert body["derived_signal"] == "solar"
    # untouched fields stay at defaults
    assert body["settings"]["palette"] == "standard"

    resp = client.get("/api/test/user/settings?user=alice")
    assert resp.json()["derived_signal"] == "solar"

    # a second partial update must not clobber the first
    client.put("/api/test/user/settings?user=alice", json={"palette": "colorblind"})
    body = client.get("/api/test/user/settings?user=alice").json()
    assert body["derived_signal"] == "solar"
    assert body["settings"]["palette"] == "colorblind"


@pytest.mark.parametrize("payload", [
    {"contract_type": "moon_phase"},
    {"palette": "rainbow"},
    {"brightness": 0},
    {"brightness": 101},
    {"night_dim_start": "25:00"},
    {"night_dim_end": "9pm"},
])
def test_settings_validation_rejects(payload):
    resp = client.put("/api/test/user/settings?user=bob", json=payload)
    assert resp.status_code == 400


def _codes(hours_and_colors):
    return [{"hour": h, "color_code": c} for h, c in hours_and_colors]


def test_price_source_is_identity():
    codes = _codes([("2026-08-26T12:00:00Z", "R")])
    settings = dict(main.DEFAULT_USER_SETTINGS)
    assert main.apply_signal_source(codes, settings) == codes


def test_day_night_source():
    settings = {**main.DEFAULT_USER_SETTINGS, "contract_type": "day_night"}
    # Wed 2026-08-26 12:00 UTC = 14:00 Brussels (weekday day) -> Y
    # Wed 2026-08-26 21:00 UTC = 23:00 Brussels (night) -> G
    # Sat 2026-08-29 12:00 UTC (weekend) -> G
    codes = _codes([
        ("2026-08-26T12:00:00Z", "R"),
        ("2026-08-26T21:00:00Z", "R"),
        ("2026-08-29T12:00:00Z", "R"),
    ])
    result = [e["color_code"] for e in main.apply_signal_source(codes, settings)]
    assert result == ["Y", "G", "G"]


def test_day_night_with_solar_goes_green_in_production_hours():
    settings = {**main.DEFAULT_USER_SETTINGS, "contract_type": "day_night", "has_solar": True}
    codes = _codes([
        ("2026-08-26T10:00:00Z", "R"),   # Wed 12:00 Brussels: day tariff but sunny -> G
        ("2026-08-26T16:00:00Z", "R"),   # Wed 18:00 Brussels: day tariff, no sun -> Y
    ])
    boost = {"2026-08-26T10:00:00Z"}
    result = [e["color_code"] for e in main.apply_signal_source(codes, settings, boost)]
    assert result == ["G", "Y"]


def test_solar_source_shifts_only_in_window():
    settings = {**main.DEFAULT_USER_SETTINGS, "has_solar": True}
    # 10:00 UTC = 12:00 Brussels (in window): R->Y, Y->G, G->G
    # 20:00 UTC = 22:00 Brussels (outside): unchanged
    codes = _codes([
        ("2026-08-26T10:00:00Z", "R"),
        ("2026-08-26T10:00:00Z", "Y"),
        ("2026-08-26T10:00:00Z", "G"),
        ("2026-08-26T20:00:00Z", "R"),
    ])
    result = [e["color_code"] for e in main.apply_signal_source(codes, settings)]
    assert result == ["Y", "G", "G", "R"]


def test_solar_source_with_forecast_boost_set():
    settings = {**main.DEFAULT_USER_SETTINGS, "has_solar": True}
    codes = _codes([
        ("2026-08-26T06:00:00Z", "R"),   # boosted by forecast despite early hour
        ("2026-08-26T12:00:00Z", "R"),   # midday but NOT boosted (cloudy forecast)
    ])
    boost = {"2026-08-26T06:00:00Z"}
    result = [e["color_code"] for e in main.apply_signal_source(codes, settings, boost)]
    assert result == ["Y", "R"]


def test_compute_solar_boost_thresholds():
    radiation = {
        "2026-08-26T05:00:00Z": 20.0,    # below absolute floor
        "2026-08-26T09:00:00Z": 300.0,   # above both thresholds
        "2026-08-26T12:00:00Z": 800.0,   # peak
        "2026-08-26T17:00:00Z": 150.0,   # above floor, below 35% of peak (280)
    }
    boost = main.compute_solar_boost(radiation)
    assert boost["2026-08-26T05:00:00Z"] is False
    assert boost["2026-08-26T09:00:00Z"] is True
    assert boost["2026-08-26T12:00:00Z"] is True
    assert boost["2026-08-26T17:00:00Z"] is False
    assert main.compute_solar_boost({}) == {}


def test_has_battery_roundtrip():
    resp = client.put("/api/test/user/settings?user=dave", json={"has_battery": True})
    assert resp.status_code == 200
    assert resp.json()["settings"]["has_battery"] is True
    settings = client.get("/api/test/user/settings?user=dave").json()["settings"]
    assert settings["has_battery"] is True


def test_display_block():
    # Night dimming is on by default at a fixed 30%
    block = main.build_display_block(main.DEFAULT_USER_SETTINGS)
    assert block == {"palette": "standard", "brightness": 100,
                     "night_dim": {"from": "22:00", "to": "07:00", "brightness": 30}}

    settings = {**main.DEFAULT_USER_SETTINGS, "night_dim_enabled": False}
    assert main.build_display_block(settings)["night_dim"] is None

    settings = {**main.DEFAULT_USER_SETTINGS, "night_dim_enabled": True,
                "night_dim_start": "21:30", "night_dim_end": "06:00",
                "palette": "colorblind", "brightness": 25}
    block = main.build_display_block(settings)
    assert block["palette"] == "colorblind"
    assert block["brightness"] == 25
    assert block["night_dim"] == {"from": "21:30", "to": "06:00", "brightness": 30}


def test_battery_evening_bridge():
    # Wed 2026-08-26: 17:00 UTC = 19:00 Brussels (evening peak window)
    codes = _codes([
        ("2026-08-26T17:00:00Z", "R"),   # evening R
        ("2026-08-26T12:00:00Z", "R"),   # midday R, outside bridge window
    ])
    solar = {**main.DEFAULT_USER_SETTINGS, "has_solar": True}
    battery = {**solar, "has_battery": True}

    # Charged day: >= 3 boost hours before 17:00 local that same day
    charged_boost = {"2026-08-26T09:00:00Z", "2026-08-26T10:00:00Z", "2026-08-26T11:00:00Z"}
    result = [e["color_code"] for e in main.apply_signal_source(codes, battery, charged_boost)]
    assert result == ["Y", "R"]  # evening softened, midday untouched

    # Grey day (no charge): battery does nothing
    result = [e["color_code"] for e in main.apply_signal_source(codes, battery, set())]
    assert result == ["R", "R"]

    # No battery: no bridge even on a sunny day
    result = [e["color_code"] for e in main.apply_signal_source(codes, solar, charged_boost)]
    assert result == ["R", "R"]

    # No forecast (fixed-window fallback): assume charged
    result = [e["color_code"] for e in main.apply_signal_source(codes, battery, None)]
    assert result[0] == "Y"


def test_device_resolution():
    assert main.get_settings_for_device(None) == (None, None)
    assert main.get_settings_for_device("unknown-mac") == (None, None)

    with sqlite3.connect(main.DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO devices (client_ip, device_fingerprint, device_id)
            VALUES ('10.0.0.2', 'fp-1', 'aabbccddeeff')
        ''')
        device_row_id = cursor.lastrowid
        # detected but unclaimed -> no personalization
        conn.commit()
    assert main.get_settings_for_device("aabbccddeeff") == (None, None)

    with sqlite3.connect(main.DB_PATH) as conn:
        conn.execute('INSERT INTO user_devices (user_id, device_id, nickname) VALUES (?, ?, ?)',
                     ("carol", device_row_id, "kitchen"))
        conn.commit()
    main.save_user_settings("carol", main.UserSettingsUpdate(contract_type="day_night"))

    user_id, settings = main.get_settings_for_device("aabbccddeeff")
    assert user_id == "carol"
    assert settings["contract_type"] == "day_night"
    assert main.derive_signal_source(settings) == "day_night"
