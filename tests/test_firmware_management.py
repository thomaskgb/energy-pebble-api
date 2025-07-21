#!/usr/bin/env python3
"""
Test script for firmware management system
"""

import requests
import json
import io
from pathlib import Path
import time

# Configuration
BASE_URL = "http://localhost:8000"
ADMIN_USER = "thomas"

def test_firmware_upload():
    """Test firmware upload endpoint"""
    print("Testing firmware upload...")
    
    # Create a dummy firmware file
    dummy_firmware = b"ESP32_FIRMWARE_BINARY_DATA" + b"\x00" * 1000  # 1KB dummy file
    
    files = {
        'firmware_file': ('esp32_v1.3.0.bin', io.BytesIO(dummy_firmware), 'application/octet-stream')
    }
    
    data = {
        'version': 'v1.3.0',
        'is_stable': True,
        'force_update': False,
        'release_notes': 'Test firmware upload from script',
        'min_version': 'v1.0.0'
    }
    
    headers = {
        'Authorization': f'Bearer {ADMIN_USER}'
    }
    
    try:
        response = requests.post(f"{BASE_URL}/api/firmware/upload", files=files, data=data, headers=headers)
        print(f"Upload response: {response.status_code}")
        if response.status_code == 200:
            result = response.json()
            print(f"Success: {result['message']}")
            print(f"Version: {result['version']}")
            print(f"Checksum: {result['checksum']}")
            return result['version']
        else:
            print(f"Error: {response.text}")
            return None
    except Exception as e:
        print(f"Upload failed: {e}")
        return None

def test_list_firmware():
    """Test listing firmware versions"""
    print("\nTesting firmware list...")
    
    headers = {
        'Authorization': f'Bearer {ADMIN_USER}'
    }
    
    try:
        response = requests.get(f"{BASE_URL}/api/firmware/versions", headers=headers)
        print(f"List response: {response.status_code}")
        if response.status_code == 200:
            result = response.json()
            print(f"Total versions: {result['total']}")
            for version in result['versions']:
                print(f"  - {version['version']}: {version['filename']} ({version['file_size']} bytes)")
        else:
            print(f"Error: {response.text}")
    except Exception as e:
        print(f"List failed: {e}")

def test_ota_check():
    """Test OTA check for a device"""
    print("\nTesting OTA check...")
    
    try:
        response = requests.get(f"{BASE_URL}/api/ota/check/test-device-1?current_version=v1.0.0")
        print(f"OTA check response: {response.status_code}")
        if response.status_code == 200:
            result = response.json()
            print(f"Update available: {result['update_available']}")
            if result['update_available']:
                print(f"New version: {result['version']}")
                print(f"Download URL: {result['download_url']}")
        else:
            print(f"Error: {response.text}")
    except Exception as e:
        print(f"OTA check failed: {e}")

def test_firmware_download(filename):
    """Test firmware download"""
    print(f"\nTesting firmware download: {filename}")
    
    try:
        response = requests.get(f"{BASE_URL}/firmware/{filename}")
        print(f"Download response: {response.status_code}")
        if response.status_code == 200:
            print(f"Content-Type: {response.headers.get('content-type')}")
            print(f"Content-Length: {response.headers.get('content-length')}")
            print(f"Firmware-Version: {response.headers.get('x-firmware-version')}")
            print(f"Downloaded {len(response.content)} bytes")
        else:
            print(f"Error: {response.text}")
    except Exception as e:
        print(f"Download failed: {e}")

def test_ota_statistics():
    """Test OTA statistics endpoint"""
    print("\nTesting OTA statistics...")
    
    headers = {
        'Authorization': f'Bearer {ADMIN_USER}'
    }
    
    try:
        response = requests.get(f"{BASE_URL}/api/firmware/ota-stats", headers=headers)
        print(f"Stats response: {response.status_code}")
        if response.status_code == 200:
            result = response.json()
            print(f"Total checks: {result['total_checks']}")
            print(f"Successful updates: {result['successful_updates']}")
            print(f"Failed updates: {result['failed_updates']}")
            print(f"Success rate: {result['success_rate']:.1f}%")
        else:
            print(f"Error: {response.text}")
    except Exception as e:
        print(f"Stats failed: {e}")

def main():
    print("=== Firmware Management Test ===")
    
    # Test upload
    version = test_firmware_upload()
    
    # Test listing
    test_list_firmware()
    
    # Test OTA check
    test_ota_check()
    
    # Test download if we uploaded a file
    if version:
        filename = f"esp32_{version}.bin"
        test_firmware_download(filename)
    
    # Test statistics
    test_ota_statistics()
    
    print("\n=== Test Complete ===")

if __name__ == "__main__":
    main()