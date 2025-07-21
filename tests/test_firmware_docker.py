#!/usr/bin/env python3
"""
Test script for firmware management system using Docker
"""

import requests
import json
import io
import time

# Configuration
BASE_URL = "http://localhost:8000"
ADMIN_USER = "thomas"

def wait_for_server(max_attempts=30):
    """Wait for the server to be ready"""
    print("Waiting for server to be ready...")
    for i in range(max_attempts):
        try:
            response = requests.get(f"{BASE_URL}/api/json", timeout=2)
            if response.status_code == 200:
                print("Server is ready!")
                return True
        except requests.exceptions.RequestException:
            pass
        time.sleep(1)
        print(f"  Attempt {i+1}/{max_attempts}")
    
    print("Server not ready after maximum attempts")
    return False

def test_firmware_endpoints():
    """Test all firmware management endpoints"""
    print("\n=== Testing Firmware Management Endpoints ===")
    
    # Test list firmware versions (admin required)
    print("\n1. Testing firmware list (should require auth)...")
    response = requests.get(f"{BASE_URL}/api/firmware/versions")
    print(f"   Without auth: {response.status_code} - {response.text[:100]}")
    
    # Test with auth header
    headers = {'Authorization': f'Bearer {ADMIN_USER}'}
    response = requests.get(f"{BASE_URL}/api/firmware/versions", headers=headers)
    print(f"   With auth: {response.status_code}")
    if response.status_code == 200:
        result = response.json()
        print(f"   Found {result['total']} firmware versions")
        for version in result['versions'][:3]:  # Show first 3
            print(f"     - {version['version']}: {version['filename']}")
    
    # Test OTA check (should be public)
    print("\n2. Testing OTA check (should be public)...")
    response = requests.get(f"{BASE_URL}/api/ota/check/test-device-1?current_version=v1.0.0")
    print(f"   OTA check: {response.status_code}")
    if response.status_code == 200:
        result = response.json()
        print(f"   Update available: {result['update_available']}")
        if result.get('update_available'):
            print(f"   New version: {result['version']}")
    
    # Test firmware download (should be public)
    print("\n3. Testing firmware download (should be public)...")
    # First get a firmware filename from the list
    response = requests.get(f"{BASE_URL}/api/firmware/versions", headers=headers)
    if response.status_code == 200:
        versions = response.json()['versions']
        if versions:
            filename = versions[0]['filename']
            print(f"   Testing download of: {filename}")
            response = requests.get(f"{BASE_URL}/firmware/{filename}")
            print(f"   Download: {response.status_code}")
            if response.status_code == 200:
                print(f"   Downloaded {len(response.content)} bytes")
                print(f"   Content-Type: {response.headers.get('content-type')}")
    
    # Test OTA statistics (admin required)
    print("\n4. Testing OTA statistics (should require auth)...")
    response = requests.get(f"{BASE_URL}/api/firmware/ota-stats", headers=headers)
    print(f"   OTA stats: {response.status_code}")
    if response.status_code == 200:
        result = response.json()
        print(f"   Total checks: {result['total_checks']}")
        print(f"   Success rate: {result['success_rate']:.1f}%")

def main():
    if not wait_for_server():
        return
    
    test_firmware_endpoints()
    print("\n=== Test Complete ===")

if __name__ == "__main__":
    main()