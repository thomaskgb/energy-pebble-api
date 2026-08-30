#!/usr/bin/env python3
"""
Unit tests for the waitlist: the public signup endpoint behind the /insights
call to action, and the admin views that read it.

The endpoint is public and unauthenticated, so the tests that matter are the
ones about abuse and disclosure: a bad address is rejected, a flood is
throttled, signing up twice is indistinguishable from signing up once (so the
endpoint cannot be used to check whether an address is on the list), and only
an admin can read the list back.

Runs offline (no live server, no Elia calls):
    ENERGY_PEBBLE_DATA_DIR=$(mktemp -d) pytest tests/test_waitlist.py
"""

import os
import sqlite3
import sys
import tempfile
from pathlib import Path

import pytest

os.environ.setdefault("ENERGY_PEBBLE_DATA_DIR", tempfile.mkdtemp(prefix="pebble-test-"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient  # noqa: E402
import main  # noqa: E402

client = TestClient(main.app)

ADMIN = {"Remote-User": "boss", "Remote-Groups": "admins"}
USER = {"Remote-User": "nele", "Remote-Groups": "users"}


@pytest.fixture(autouse=True)
def clean_waitlist():
    """Each test starts with an empty list and a fresh rate-limit budget."""
    main._waitlist_hits.clear()
    with sqlite3.connect(main.DB_PATH) as conn:
        conn.execute("DELETE FROM waitlist")
        conn.commit()
    yield


def signup(email, **kwargs):
    return client.post("/api/waitlist", json={"email": email, **kwargs})


# --- signing up ---------------------------------------------------------------

def test_a_valid_address_is_stored():
    assert signup("nele@example.be").status_code == 200
    entries = client.get("/api/admin/waitlist", headers=ADMIN).json()["entries"]
    assert [e["email"] for e in entries] == ["nele@example.be"]


def test_addresses_are_normalized_to_lowercase():
    """Otherwise Nele@Example.be and nele@example.be are two people."""
    signup("Nele@Example.BE")
    entries = client.get("/api/admin/waitlist", headers=ADMIN).json()["entries"]
    assert entries[0]["email"] == "nele@example.be"


def test_signing_up_twice_is_not_an_error_and_stores_one_row():
    """The response must not reveal that an address is already on the list."""
    first = signup("nele@example.be")
    second = signup("nele@example.be")
    assert first.status_code == second.status_code == 200
    assert first.json() == second.json()
    assert client.get("/api/admin/waitlist", headers=ADMIN).json()["total"] == 1


@pytest.mark.parametrize("bad", ["", "   ", "nope", "nope.be", "@example.be",
                                 "two@@example.be", "spaces in@example.be",
                                 "trailing@dot.", "a@b"])
def test_malformed_addresses_are_rejected(bad):
    assert signup(bad).status_code == 400


def test_an_over_long_address_is_rejected():
    assert signup("x" * 250 + "@example.be").status_code == 400


def test_the_reading_language_is_recorded():
    """So we know which language to write back in."""
    signup("fr@example.be", language="fr")
    entries = client.get("/api/admin/waitlist", headers=ADMIN).json()["entries"]
    assert entries[0]["language"] == "fr"


def test_an_unknown_language_is_stored_as_nothing_rather_than_rejected():
    signup("de@example.be", language="de")
    entries = client.get("/api/admin/waitlist", headers=ADMIN).json()["entries"]
    assert entries[0]["language"] is None


def test_signups_from_one_address_are_rate_limited():
    codes = [signup(f"person{i}@example.be").status_code for i in range(10)]
    assert codes[:main.WAITLIST_MAX_PER_IP_PER_HOUR] == [200] * main.WAITLIST_MAX_PER_IP_PER_HOUR
    assert set(codes[main.WAITLIST_MAX_PER_IP_PER_HOUR:]) == {429}


# --- reading the list ---------------------------------------------------------

def test_the_list_is_not_public():
    assert client.get("/api/admin/waitlist").status_code == 401
    assert client.get("/api/admin/waitlist", headers=USER).status_code == 403


def test_the_export_is_not_public():
    assert client.get("/api/admin/waitlist.csv").status_code == 401
    assert client.get("/api/admin/waitlist.csv", headers=USER).status_code == 403


def test_the_list_counts_by_language():
    signup("a@example.be", language="nl")
    signup("b@example.be", language="nl")
    signup("c@example.be", language="fr")
    signup("d@example.be")
    body = client.get("/api/admin/waitlist", headers=ADMIN).json()
    assert body["total"] == 4
    assert body["by_language"] == {"nl": 2, "fr": 1, "unknown": 1}


def test_the_export_is_csv_with_a_header_row():
    signup("nele@example.be", language="nl")
    response = client.get("/api/admin/waitlist.csv", headers=ADMIN)
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    assert "attachment" in response.headers["content-disposition"]
    lines = response.text.strip().splitlines()
    assert lines[0] == "email,language,created_at"
    assert lines[1].startswith("nele@example.be,nl,")


# --- deletion: the promise the signup form makes ------------------------------

def test_an_address_can_be_deleted():
    signup("nele@example.be")
    entry_id = client.get("/api/admin/waitlist", headers=ADMIN).json()["entries"][0]["id"]
    assert client.delete(f"/api/admin/waitlist/{entry_id}", headers=ADMIN).status_code == 200
    assert client.get("/api/admin/waitlist", headers=ADMIN).json()["total"] == 0


def test_deleting_something_that_is_not_there_is_a_404():
    assert client.delete("/api/admin/waitlist/9999", headers=ADMIN).status_code == 404


def test_deletion_is_not_public():
    signup("nele@example.be")
    entry_id = client.get("/api/admin/waitlist", headers=ADMIN).json()["entries"][0]["id"]
    assert client.delete(f"/api/admin/waitlist/{entry_id}").status_code == 401
    assert client.delete(f"/api/admin/waitlist/{entry_id}", headers=USER).status_code == 403
    assert client.get("/api/admin/waitlist", headers=ADMIN).json()["total"] == 1


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
