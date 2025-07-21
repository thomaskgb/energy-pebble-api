#!/usr/bin/env python3
"""
Test dashboard API functionality by simulating authenticated requests.
"""

import requests
import json

def test_dashboard_apis():
    """Test dashboard API endpoints with simulated authentication headers."""
    
    print("🧪 Testing Dashboard API Endpoints")
    print("=" * 50)
    
    # Simulate Authelia headers that would be added by the proxy
    headers = {
        'Remote-User': 'thomas@tdlx.nl',
        'Remote-Name': 'Thomas',
        'Remote-Email': 'thomas@tdlx.nl', 
        'Remote-Groups': 'admins,users'
    }
    
    session = requests.Session()
    
    # Test 1: API Verify endpoint (direct to API container)
    print("\n1️⃣ Testing /api/verify endpoint (direct)")
    try:
        response = session.get('http://localhost:8000/api/verify', headers=headers)
        
        if response.status_code == 200:
            data = response.json()
            print("✅ /api/verify successful:")
            print(f"   User: {data.get('user')}")
            print(f"   Display Name: {data.get('display_name')}")
            print(f"   Is Admin: {data.get('is_admin')}")
        else:
            print(f"❌ /api/verify failed: {response.status_code}")
            print(f"   Response: {response.text}")
    except Exception as e:
        print(f"❌ /api/verify error: {e}")
    
    # Test 2: User devices endpoint (direct to API container)
    print("\n2️⃣ Testing /api/user/devices endpoint (direct)")
    try:
        response = session.get('http://localhost:8000/api/user/devices', headers=headers)
        
        if response.status_code == 200:
            data = response.json()
            print("✅ /api/user/devices successful:")
            print(f"   Claimed devices: {len(data.get('claimed', []))}")
            print(f"   Detected devices: {len(data.get('detected', []))}")
            if data.get('claimed'):
                for device in data['claimed'][:3]:  # Show first 3
                    print(f"   - {device.get('name', 'Unknown')} ({device.get('nickname', 'No nickname')})")
        else:
            print(f"❌ /api/user/devices failed: {response.status_code}")
            print(f"   Response: {response.text}")
    except Exception as e:
        print(f"❌ /api/user/devices error: {e}")
    
    # Test 3: Admin devices endpoint (direct to API container)
    print("\n3️⃣ Testing /api/admin/devices endpoint (direct)")
    try:
        response = session.get('http://localhost:8000/api/admin/devices', headers=headers)
        
        if response.status_code == 200:
            data = response.json()
            print("✅ /api/admin/devices successful:")
            print(f"   Total devices: {data.get('total', 0)}")
            print(f"   Online devices: {data.get('online', 0)}")
            print(f"   Claimed devices: {data.get('claimed', 0)}")
        else:
            print(f"❌ /api/admin/devices failed: {response.status_code}")
            print(f"   Response: {response.text}")
    except Exception as e:
        print(f"❌ /api/admin/devices error: {e}")
    
    print("\n📋 SUMMARY")
    print("=" * 50)
    print("These tests simulate what happens when a user is authenticated.")
    print("If /api/verify and /api/user/devices work, the dashboard should load properly.")
    print("\nNext steps:")
    print("1. Verify the dashboard loads with 'credentials: include' in fetch calls")
    print("2. Check browser console for any remaining JavaScript errors") 
    print("3. Ensure dropdown navigation works smoothly")

if __name__ == "__main__":
    test_dashboard_apis()