#!/usr/bin/env python3
"""
Unit tests for the Elia day-ahead price cache: repeated requests must not
result in repeated calls to griddata.elia.be.

Runs offline (no live server, no Elia calls):
    ENERGY_PEBBLE_DATA_DIR=$(mktemp -d) pytest tests/test_elia_cache.py
"""

import asyncio
import os
import sys
import tempfile
from pathlib import Path

import pytest
from fastapi import HTTPException

# Point main.py at a throwaway data dir before importing it (it initializes
# the database at import time).
os.environ.setdefault("ENERGY_PEBBLE_DATA_DIR", tempfile.mkdtemp(prefix="pebble-test-"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import main  # noqa: E402


def full_day(date_str: str):
    """A complete day of quarter-hourly entries, as Elia returns it."""
    return [
        {"dateTime": f"{date_str}T{h:02d}:{m:02d}:00Z", "price": 50.0, "isVisible": True}
        for h in range(24)
        for m in (0, 15, 30, 45)
    ]


@pytest.fixture(autouse=True)
def clean_cache():
    main.elia_cache.clear()
    main.elia_cache_locks.clear()
    if main.elia_cache_file.exists():
        main.elia_cache_file.unlink()
    yield
    main.elia_cache.clear()
    main.elia_cache_locks.clear()


@pytest.fixture
def upstream(monkeypatch):
    """Counting stand-in for the real Elia fetch."""
    calls = []

    async def fake_fetch(date_str):
        calls.append(date_str)
        if fake_fetch.error:
            raise fake_fetch.error
        return fake_fetch.payload(date_str)

    fake_fetch.calls = calls
    fake_fetch.error = None
    fake_fetch.payload = full_day
    monkeypatch.setattr(main, "fetch_data_from_elia", fake_fetch)
    return fake_fetch


def test_second_request_is_served_from_cache(upstream):
    first = asyncio.run(main.fetch_data("2025-04-14"))
    second = asyncio.run(main.fetch_data("2025-04-14"))

    assert first == second
    assert upstream.calls == ["2025-04-14"]


def test_each_date_is_cached_separately(upstream):
    asyncio.run(main.fetch_data("2025-04-14"))
    asyncio.run(main.fetch_data("2025-04-15"))
    asyncio.run(main.fetch_data("2025-04-14"))

    assert upstream.calls == ["2025-04-14", "2025-04-15"]


def test_concurrent_requests_trigger_one_fetch(upstream):
    async def burst():
        return await asyncio.gather(*(main.fetch_data("2025-04-14") for _ in range(10)))

    results = asyncio.run(burst())

    assert all(r == results[0] for r in results)
    assert upstream.calls == ["2025-04-14"]


def test_expired_entry_is_refetched(upstream):
    asyncio.run(main.fetch_data("2025-04-14"))
    main.elia_cache["2025-04-14"]["fetched_at"] -= main.ELIA_CACHE_TTL_SECONDS + 1

    asyncio.run(main.fetch_data("2025-04-14"))

    assert upstream.calls == ["2025-04-14", "2025-04-14"]


def test_partial_day_is_retried_sooner_than_a_full_day(upstream):
    upstream.payload = lambda date_str: full_day(date_str)[:20]
    asyncio.run(main.fetch_data("2025-04-14"))

    # Past the retry window but well within the full-day TTL.
    main.elia_cache["2025-04-14"]["fetched_at"] -= main.ELIA_CACHE_RETRY_SECONDS + 1
    asyncio.run(main.fetch_data("2025-04-14"))

    assert upstream.calls == ["2025-04-14", "2025-04-14"]


def test_stale_cache_covers_an_elia_outage(upstream):
    fresh = asyncio.run(main.fetch_data("2025-04-14"))
    main.elia_cache["2025-04-14"]["fetched_at"] -= main.ELIA_CACHE_TTL_SECONDS + 1
    upstream.error = HTTPException(status_code=503, detail="Elia is down")

    assert asyncio.run(main.fetch_data("2025-04-14")) == fresh


def test_outage_without_a_cached_day_still_raises(upstream):
    upstream.error = HTTPException(status_code=503, detail="Elia is down")

    with pytest.raises(HTTPException):
        asyncio.run(main.fetch_data("2025-04-14"))


def test_cache_survives_a_restart(upstream):
    asyncio.run(main.fetch_data("2025-04-14"))

    # Simulate a fresh process: in-memory state gone, disk state intact.
    main.elia_cache.clear()
    main.elia_cache_locks.clear()
    main.load_elia_cache()

    asyncio.run(main.fetch_data("2025-04-14"))
    assert upstream.calls == ["2025-04-14"]


def test_cache_is_bounded(upstream):
    for day in range(1, main.ELIA_CACHE_MAX_DAYS + 6):
        asyncio.run(main.fetch_data(f"2025-05-{day:02d}"))

    assert len(main.elia_cache) == main.ELIA_CACHE_MAX_DAYS
