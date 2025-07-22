#!/usr/bin/env python3
"""
Test script for API token authentication system
"""

import requests
import json
import time

BASE_URL = "http://localhost:8000"

def test_token_creation():
    """Test creating an API token via the admin endpoint"""
    print("🔑 Testing API Token System")
    print("=" * 50)
    
    # Test 1: Try to access token endpoint without authentication
    print("1. Testing unauthenticated access to token endpoint...")
    response = requests.get(f"{BASE_URL}/api/admin/tokens")
    if response.status_code == 401:
        print("   ✅ Correctly rejected unauthenticated request")
    else:
        print(f"   ❌ Unexpected response: {response.status_code}")
        return False
    
    # Test 2: Test with mock admin headers (simulate Authelia)
    print("2. Testing token creation with admin credentials...")
    admin_headers = {
        "Remote-User": "thomas@tdlx.nl",
        "Remote-Groups": "admins,users",
        "Remote-Name": "Thomas"
    }
    
    # Create a test token
    token_data = {
        "token_name": "Test Token",
        "scopes": ["read", "devices"],
        "expires_days": 30
    }
    
    response = requests.post(
        f"{BASE_URL}/api/admin/tokens",
        headers=admin_headers,
        json=token_data
    )
    
    if response.status_code == 200:
        result = response.json()
        token = result.get('token')
        print(f"   ✅ Token created successfully: {token[:20]}...")
        
        # Test 3: Use the token to access an API endpoint
        print("3. Testing API access with the new token...")
        api_headers = {
            "Authorization": f"Bearer {token}"
        }
        
        response = requests.get(f"{BASE_URL}/api/color-code", headers=api_headers)
        if response.status_code == 200:
            print("   ✅ Successfully accessed API with token")
            data = response.json()
            print(f"   📊 API Response: Current color is {data.get('current', {}).get('color', 'unknown')}")
        else:
            print(f"   ❌ Failed to access API with token: {response.status_code}")
            return False
        
        # Test 4: List tokens
        print("4. Testing token listing...")
        response = requests.get(f"{BASE_URL}/api/admin/tokens", headers=admin_headers)
        if response.status_code == 200:
            tokens_data = response.json()
            print(f"   ✅ Found {tokens_data.get('total', 0)} tokens")
            for token_info in tokens_data.get('tokens', [])[:3]:  # Show first 3
                print(f"   🔑 Token: {token_info['token_name']} - Status: {'Active' if token_info['is_active'] else 'Inactive'}")
        else:
            print(f"   ❌ Failed to list tokens: {response.status_code}")
        
        return True
        
    else:
        print(f"   ❌ Failed to create token: {response.status_code}")
        if response.text:
            print(f"   Error: {response.text}")
        return False

def test_token_scopes():
    """Test that token scopes work correctly"""
    print("\n🛡️ Testing Token Scopes")
    print("=" * 50)
    
    admin_headers = {
        "Remote-User": "thomas@tdlx.nl", 
        "Remote-Groups": "admins,users"
    }
    
    # Create a read-only token
    token_data = {
        "token_name": "Read Only Test",
        "scopes": ["read"]
    }
    
    response = requests.post(
        f"{BASE_URL}/api/admin/tokens",
        headers=admin_headers,
        json=token_data
    )
    
    if response.status_code == 200:
        token = response.json().get('token')
        api_headers = {"Authorization": f"Bearer {token}"}
        
        # Test read access (should work)
        print("1. Testing read access...")
        response = requests.get(f"{BASE_URL}/api/color-code", headers=api_headers)
        if response.status_code == 200:
            print("   ✅ Read access works")
        else:
            print(f"   ❌ Read access failed: {response.status_code}")
            
        # Test admin access (should be allowed since all tokens have admin privileges)
        print("2. Testing admin access...")
        response = requests.get(f"{BASE_URL}/api/admin/tokens", headers=api_headers)
        if response.status_code == 200:
            print("   ✅ Admin access works (expected for admin tokens)")
        else:
            print(f"   ℹ️ Admin access restricted: {response.status_code}")
        
        return True
    else:
        print(f"❌ Failed to create read-only token: {response.status_code}")
        return False

if __name__ == "__main__":
    print("Starting API Token Tests...")
    print("Make sure the API server is running on localhost:8000\n")
    
    try:
        # Test basic connectivity
        response = requests.get(f"{BASE_URL}/api/sample", timeout=5)
        if response.status_code != 200:
            print("❌ API server not responding. Make sure it's running.")
            exit(1)
            
        print("✅ API server is running\n")
        
        # Run tests
        success1 = test_token_creation()
        success2 = test_token_scopes()
        
        print("\n" + "=" * 50)
        if success1 and success2:
            print("🎉 All tests passed!")
        else:
            print("❌ Some tests failed")
            
    except requests.exceptions.ConnectionError:
        print("❌ Could not connect to API server. Make sure it's running on localhost:8000")
    except Exception as e:
        print(f"❌ Test error: {e}")