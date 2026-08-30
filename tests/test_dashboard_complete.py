#!/usr/bin/env python3
"""
Complete dashboard functionality test
"""

import requests
import json

def test_complete_dashboard():
    """Test all dashboard components and functionality."""
    
    print("🧪 Complete Dashboard Functionality Test")
    print("=" * 50)
    
    # Simulate Authelia headers
    headers = {
        'Remote-User': 'thomas@tdlx.nl',
        'Remote-Name': 'Thomas',
        'Remote-Email': 'thomas@tdlx.nl', 
        'Remote-Groups': 'admins,users'
    }
    
    session = requests.Session()
    
    # Test 1: Check base.css accessibility via Caddy
    print("\n1️⃣ Testing base.css accessibility")
    try:
        # Try to access base.css through Docker container
        response = session.get('http://localhost:8001/base.css')
        if response.status_code == 200:
            print("✅ base.css accessible via web server")
            if '.btn {' in response.text:
                print("   Contains button styles ✓")
            if '--accent:' in response.text:
                print("   Contains design tokens ✓")
        else:
            print(f"❌ base.css not accessible: {response.status_code}")
    except Exception as e:
        print(f"❌ Error accessing base.css: {e}")
    
    # Test 2: Check dashboard.html accessibility
    print("\n2️⃣ Testing dashboard.html accessibility")
    try:
        response = session.get('http://localhost:8001/dashboard')
        if response.status_code == 200:
            print("✅ dashboard.html accessible")
            if 'base.css' in response.text:
                print("   Links to base.css ✓")
            if 'loadUserData' in response.text:
                print("   Contains authentication JavaScript ✓")
        else:
            print(f"❌ dashboard.html not accessible: {response.status_code}")
    except Exception as e:
        print(f"❌ Error accessing dashboard.html: {e}")
    
    # Test 3: API endpoints functionality
    print("\n3️⃣ Testing API endpoints")
    
    # Test /api/verify
    try:
        response = session.get('http://localhost:8000/api/verify', headers=headers)
        if response.status_code == 200:
            data = response.json()
            print(f"✅ /api/verify: user={data.get('user')}, admin={data.get('is_admin')}")
        else:
            print(f"❌ /api/verify failed: {response.status_code}")
    except Exception as e:
        print(f"❌ /api/verify error: {e}")
    
    # Test /api/user/devices
    try:
        response = session.get('http://localhost:8000/api/user/devices', headers=headers)
        if response.status_code == 200:
            data = response.json()
            print(f"✅ /api/user/devices: claimed={len(data.get('claimed', []))}, detected={len(data.get('detected', []))}")
        else:
            print(f"❌ /api/user/devices failed: {response.status_code}")
    except Exception as e:
        print(f"❌ /api/user/devices error: {e}")
    
    # Test 4: Check docker container status
    print("\n4️⃣ Testing Docker containers")
    import subprocess
    try:
        result = subprocess.run(['docker', 'compose', 'ps', '--format', 'json'], 
                              capture_output=True, text=True)
        if result.returncode == 0:
            containers = json.loads(result.stdout)
            for container in containers:
                service = container.get('Service', 'unknown')
                state = container.get('State', 'unknown')
                health = container.get('Health', 'no health check')
                print(f"   {service}: {state} ({health})")
        else:
            print("❌ Failed to get container status")
    except Exception as e:
        print(f"❌ Error checking containers: {e}")
    
    print("\n📋 SUMMARY")
    print("=" * 50)
    print("Dashboard functionality test complete.")
    print("\nIf all tests pass, the dashboard should work properly.")
    print("If base.css test fails, check Docker volume mounts.")
    print("If API tests fail, check authentication headers in production.")

if __name__ == "__main__":
    test_complete_dashboard()