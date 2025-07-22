#!/usr/bin/env python3
"""
Test the /api/admin/users/management endpoint
"""

import requests
import json

def test_users_endpoint():
    """Test the users management endpoint with admin headers."""
    
    print("🧪 Testing Admin Users Management Endpoint")
    print("=" * 50)
    
    # Simulate Authelia headers for admin user
    headers = {
        'Remote-User': 'thomas@tdlx.nl',
        'Remote-Name': 'Thomas',
        'Remote-Email': 'thomas@tdlx.nl', 
        'Remote-Groups': 'admins,users'
    }
    
    try:
        # Test the endpoint
        response = requests.get('http://localhost:8000/api/admin/users/management', 
                              headers=headers)
        
        if response.status_code == 200:
            data = response.json()
            print(f"✅ Endpoint working!")
            print(f"   Total users: {data.get('total_users', 0)}")
            print(f"   Admin users: {data.get('admin_users', 0)}")
            print(f"   Regular users: {data.get('regular_users', 0)}")
            
            print("\n👥 Users found:")
            for user in data.get('users', []):
                role_emoji = "👑" if user.get('role') == 'admin' else "👤"
                print(f"   {role_emoji} {user.get('display_name')} ({user.get('username')}) - {user.get('role')}")
                
        elif response.status_code == 403:
            print("❌ Access denied - admin privileges required")
        elif response.status_code == 500:
            print(f"❌ Server error: {response.text}")
        else:
            print(f"❌ Unexpected response: {response.status_code} - {response.text}")
            
    except requests.exceptions.RequestException as e:
        print(f"❌ Connection error: {e}")
        print("   Make sure the API is running on localhost:8000")

if __name__ == "__main__":
    test_users_endpoint()