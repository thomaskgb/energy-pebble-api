#!/usr/bin/env python3
"""
Test script for device detection functionality.
Simulates different pebbles making requests to the API.

Runs against a local server by default. It registers devices as a side effect
-- that is the whole point of it -- so it must not be pointed at production
casually: every run leaves rows on /admin/devices that look like pebbles in
the field. Set BASE_URL deliberately if you really mean to.

    python tests/test_device_detection.py
    BASE_URL=http://localhost:8000 python tests/test_device_detection.py
"""

import os
import sys
import time

import requests

BASE_URL = os.environ.get("BASE_URL", "http://localhost:8000").rstrip("/")

# Twelve hex characters, the shape of an ESP32 eFuse MAC. The server rejects
# anything else, so a label like "test-Kitchen" would exercise nothing.
DEVICES = [
    ("Kitchen Pebble", "aa00cc00ee01", "ESP32-HTTPClient/1.0"),
    ("Living Room Pebble", "aa00cc00ee02", "ESP32-HTTPClient/1.0"),
    ("Bedroom Pebble", "aa00cc00ee03", "ESP8266-HTTPClient/1.0"),
    ("Office Pebble", "aa00cc00ee04", "ESP32-HTTPClient/1.2"),
    ("Garage Pebble", "aa00cc00ee05", "ESPHome/2023.12.0"),
]


def simulate_device_request(device_name, device_id, user_agent):
    """Simulate a device making a request to the color-code API."""
    try:
        headers = {
            'User-Agent': user_agent,
            'X-Device-ID': device_id,
        }

        response = requests.get(f'{BASE_URL}/api/color-code', headers=headers, timeout=5)
        print(f"✅ {device_name}: {response.status_code} - {len(response.text)} bytes")
        return response.status_code == 200
    except Exception as e:
        print(f"❌ {device_name}: Error - {e}")
        return False


def test_device_detection():
    """Test device detection with multiple simulated devices."""
    print("🔴 Testing Energy Pebble Device Detection")
    print(f"   against {BASE_URL}")
    print("=" * 50)

    print("Simulating device requests...")
    successful_requests = 0

    for device_name, device_id, user_agent in DEVICES:
        # Make multiple requests per device to simulate real usage
        for i in range(3):
            success = simulate_device_request(device_name, device_id, user_agent)
            if success:
                successful_requests += 1

            # Small delay between requests
            time.sleep(0.5)

    expected = len(DEVICES) * 3
    print(f"\n📊 Results: {successful_requests}/{expected} requests successful")

    # Every device must appear. Kitchen and Living Room share a user agent and
    # an IP, which used to collide on the device fingerprint and lose one of
    # them silently, so this is the case worth watching.
    #
    # The listing is admin-only. Locally that is satisfied by LOCAL_DEV_USER;
    # without it the check is skipped rather than failed, because a missing
    # session says nothing about device detection.
    print("\n🔍 Checking that every device registered...")
    registered_ok = None
    try:
        response = requests.get(f'{BASE_URL}/api/admin/devices?limit=200', timeout=5)
        if response.status_code in (401, 403):
            print("⏭️  Skipped: no admin session "
                  "(start the server with LOCAL_DEV_USER=<name> to enable)")
        elif response.status_code == 200:
            reported = {d.get("device_id") for d in response.json()["devices"]}
            missing = [name for name, device_id, _ in DEVICES
                       if device_id not in reported]
            if missing:
                print(f"❌ Not registered: {', '.join(missing)}")
                registered_ok = False
            else:
                print(f"✅ All {len(DEVICES)} simulated devices registered")
                registered_ok = True
        else:
            print(f"❌ Device listing: HTTP {response.status_code}")
            registered_ok = False
    except Exception as e:
        print(f"❌ Device listing: Error - {e}")
        registered_ok = False

    return successful_requests == expected and registered_ok is not False


if __name__ == "__main__":
    sys.exit(0 if test_device_detection() else 1)
