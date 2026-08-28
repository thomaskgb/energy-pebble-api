"""
Tests for the self-service device claim flow used by the setup page
(/setup/): secret minting, claiming with secret / same-network proof,
and the status poll.

Runs in-process against the FastAPI app with a throwaway device id;
cleans up the rows it creates. Authelia is simulated via Remote-User
headers, as Traefik would inject them.
"""
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import main  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

client = TestClient(main.app)

DEVICE_ID = "aaaabbbbcccc"  # reserved test id, cleaned up after each test
ADMIN = {"Remote-User": "thomas", "Remote-Groups": "admins"}
USER = {"Remote-User": "claimtest-user1", "Remote-Groups": "users"}
OTHER_USER = {"Remote-User": "claimtest-user2", "Remote-Groups": "users"}
DEVICE_IP = "203.0.113.9"


def cleanup():
    with sqlite3.connect(main.DB_PATH) as conn:
        cur = conn.cursor()
        cur.execute("SELECT id FROM devices WHERE device_id=?", (DEVICE_ID,))
        row = cur.fetchone()
        if row:
            cur.execute("DELETE FROM user_devices WHERE device_id=?", (row[0],))
        cur.execute("DELETE FROM devices WHERE device_id=?", (DEVICE_ID,))
        cur.execute("DELETE FROM device_secrets WHERE device_id=?", (DEVICE_ID,))
        conn.commit()


def test_claim_requires_auth():
    r = client.post("/api/user/devices/claim", json={"device_id": DEVICE_ID})
    assert r.status_code == 401


def test_claim_rejects_bad_device_id():
    r = client.post("/api/user/devices/claim",
                    json={"device_id": "not-a-mac"}, headers=USER)
    assert r.status_code == 400


def test_secret_mint_requires_admin():
    r = client.post(f"/api/admin/devices/{DEVICE_ID}/secret", headers=USER)
    assert r.status_code == 403


def test_full_claim_flow():
    cleanup()
    try:
        # No proof at all: device never seen, no secret -> refused
        r = client.post("/api/user/devices/claim",
                        json={"device_id": DEVICE_ID}, headers=USER)
        assert r.status_code == 403

        # Admin mints the sticker secret
        r = client.post(f"/api/admin/devices/{DEVICE_ID}/secret", headers=ADMIN)
        assert r.status_code == 200
        body = r.json()
        secret = body["secret"]
        assert DEVICE_ID in body["qr_url"] and secret in body["qr_url"]

        # Wrong secret -> refused
        r = client.post("/api/user/devices/claim",
                        json={"device_id": DEVICE_ID, "secret": "wrong"},
                        headers=USER)
        assert r.status_code == 403

        # Correct secret claims BEFORE the device ever phoned home
        r = client.post("/api/user/devices/claim",
                        json={"device_id": DEVICE_ID, "secret": secret,
                              "nickname": "Kitchen"},
                        headers=USER)
        assert r.status_code == 200
        assert r.json()["proof"] == "secret"

        # Placeholder row must NOT read as online
        r = client.get(f"/api/user/devices/{DEVICE_ID}/status", headers=USER)
        assert r.status_code == 200
        assert r.json()["online"] is False
        assert r.json()["claimed_by_you"] is True

        # Someone else with the same secret cannot take it over
        r = client.post("/api/user/devices/claim",
                        json={"device_id": DEVICE_ID, "secret": secret},
                        headers=OTHER_USER)
        assert r.status_code == 409

        # Device phones home -> online
        main.log_device_request(DEVICE_IP, "ESPHome", DEVICE_ID)
        r = client.get(f"/api/user/devices/{DEVICE_ID}/status", headers=USER)
        assert r.json()["online"] is True

        # Same-network claim (no secret) is accepted for the owner
        r = client.post("/api/user/devices/claim",
                        json={"device_id": DEVICE_ID},
                        headers={**USER, "x-real-ip": DEVICE_IP})
        assert r.status_code == 200
        assert r.json()["proof"] == "same_network"
    finally:
        cleanup()


def test_status_never_seen():
    cleanup()
    r = client.get(f"/api/user/devices/{DEVICE_ID}/status", headers=USER)
    assert r.status_code == 200
    assert r.json()["status"] == "never_seen"
    assert r.json()["online"] is False
