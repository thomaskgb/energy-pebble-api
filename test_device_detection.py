#!/usr/bin/env python3
"""
Test script for device detection functionality.
Simulates different energy dots making requests to the API.
"""

import requests
import time
import random

def simulate_device_request(device_name, user_agent):
    """Simulate a device making a request to the color-code API."""
    try:
        headers = {
            'User-Agent': user_agent,
            'X-Device-ID': f'test-{device_name}'  # Optional new-style device ID
        }
        
        response = requests.get('https://energypebble.tdlx.nl/api/color-code', headers=headers, timeout=5)
        print(f"✅ {device_name}: {response.status_code} - {len(response.text)} bytes")
        return response.status_code == 200
    except Exception as e:
        print(f"❌ {device_name}: Error - {e}")
        return False

def test_device_detection():
    """Test device detection with multiple simulated devices."""
    print("🔴 Testing Energy Pebble Device Detection")
    print("=" * 50)
    
    # Simulate different types of energy dots
    devices = [
        ("Kitchen Dot", "ESP32-HTTPClient/1.0"),
        ("Living Room Dot", "ESP32-HTTPClient/1.0"),
        ("Bedroom Dot", "ESP8266-HTTPClient/1.0"),
        ("Office Dot", "ESP32-HTTPClient/1.2"),
        ("Garage Dot", "ESPHome/2023.12.0"),
    ]
    
    print("Simulating device requests...")
    successful_requests = 0
    
    for device_name, user_agent in devices:
        # Make multiple requests per device to simulate real usage
        for i in range(3):
            success = simulate_device_request(device_name, user_agent)
            if success:
                successful_requests += 1
            
            # Small delay between requests
            time.sleep(0.5)
    
    print(f"\n📊 Results: {successful_requests}/{len(devices) * 3} requests successful")
    
    # Test device detection API
    print("\n🔍 Testing device detection API...")
    try:
        response = requests.get('https://energypebble.tdlx.nl/api/devices', timeout=5)
        if response.status_code == 200:
            data = response.json()
            print(f"✅ Device API: Found {data['total_devices']} devices")
            print(f"   - Claimed: {data['claimed_devices']}")
            print(f"   - Unclaimed: {data['unclaimed_devices']}")
            
            for device in data['devices']:
                print(f"   📱 Device: {device['fingerprint'][:8]}... "
                      f"({device['request_count']} requests, {device['status']})")
        else:
            print(f"❌ Device API: HTTP {response.status_code}")
    except Exception as e:
        print(f"❌ Device API: Error - {e}")

if __name__ == "__main__":
    test_device_detection()