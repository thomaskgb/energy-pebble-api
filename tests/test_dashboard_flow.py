#!/usr/bin/env python3
"""
Test the complete dashboard flow to verify authentication integration.
This simulates what happens when a user accesses the dashboard.
"""

import requests
from urllib.parse import urljoin, urlparse, parse_qs
import json

def test_dashboard_flow():
    """Test the complete dashboard authentication flow."""
    
    print("🧪 Testing Dashboard Authentication Flow")
    print("=" * 50)
    
    session = requests.Session()
    session.verify = False  # Skip SSL verification for testing
    
    # Step 1: Access dashboard (should redirect to auth)
    print("\n1️⃣ Accessing /dashboard")
    
    try:
        response = session.get("https://energypebble.tdlx.nl/dashboard", allow_redirects=False)
        
        if response.status_code == 302:
            location = response.headers.get('Location', '')
            if 'auth.tdlx.nl' in location:
                print(f"✅ Dashboard redirects to auth: {location}")
                
                # Parse redirect URL
                parsed_url = urlparse(location)
                query_params = parse_qs(parsed_url.query)
                
                if 'rd' in query_params:
                    redirect_destination = query_params['rd'][0]
                    if 'dashboard' in redirect_destination:
                        print(f"✅ Redirect destination includes dashboard: {redirect_destination}")
                    else:
                        print(f"❌ Unexpected redirect destination: {redirect_destination}")
                else:
                    print("❌ No 'rd' parameter in auth redirect")
                    
            else:
                print(f"❌ Dashboard redirects to unexpected location: {location}")
        else:
            print(f"❌ Dashboard returned unexpected status: {response.status_code}")
            
    except Exception as e:
        print(f"❌ Error accessing dashboard: {e}")
    
    # Step 2: Check auth portal accessibility  
    print("\n2️⃣ Checking auth portal accessibility")
    
    try:
        response = session.get("https://auth.tdlx.nl", timeout=10)
        
        if response.status_code == 200:
            content = response.text.lower()
            if any(word in content for word in ['sign in', 'login', 'authelia', 'username', 'password']):
                print("✅ Auth portal accessible and shows login form")
            else:
                print("❌ Auth portal accessible but doesn't show expected login form")
        else:
            print(f"❌ Auth portal returned status: {response.status_code}")
            
    except Exception as e:
        print(f"❌ Error accessing auth portal: {e}")
    
    # Step 3: Check that static assets are accessible
    print("\n3️⃣ Checking static assets accessibility")
    
    assets = [
        "/components.css",
        "/energy-pebble-image.jpg"
    ]
    
    for asset in assets:
        try:
            response = session.get(f"https://energypebble.tdlx.nl{asset}", timeout=10)
            
            if response.status_code == 200:
                print(f"✅ {asset} -> 200 (accessible)")
            else:
                print(f"❌ {asset} -> {response.status_code}")
                
        except Exception as e:
            print(f"❌ {asset} -> Error: {e}")
    
    # Step 4: Verify API endpoints work as expected
    print("\n4️⃣ Checking API endpoint behavior")
    
    # Public endpoints should be accessible
    public_endpoints = [
        "/api/color-code",
        "/api/sample"
    ]
    
    for endpoint in public_endpoints:
        try:
            response = session.get(f"https://energypebble.tdlx.nl{endpoint}", timeout=10)
            
            if response.status_code == 200:
                print(f"✅ {endpoint} -> 200 (public access works)")
            else:
                print(f"❌ {endpoint} -> {response.status_code}")
                
        except Exception as e:
            print(f"❌ {endpoint} -> Error: {e}")
    
    # Protected endpoints should redirect
    protected_endpoints = [
        "/api/verify",
        "/api/user/devices"
    ]
    
    for endpoint in protected_endpoints:
        try:
            response = session.get(f"https://energypebble.tdlx.nl{endpoint}", 
                                 allow_redirects=False, timeout=10)
            
            if response.status_code == 302:
                location = response.headers.get('Location', '')
                if 'auth.tdlx.nl' in location:
                    print(f"✅ {endpoint} -> 302 (redirects to auth)")
                else:
                    print(f"❌ {endpoint} -> 302 but redirects to: {location}")
            else:
                print(f"❌ {endpoint} -> {response.status_code} (should redirect)")
                
        except Exception as e:
            print(f"❌ {endpoint} -> Error: {e}")
    
    print("\n📋 SUMMARY")
    print("=" * 50)
    print("Expected behavior:")
    print("1. /dashboard redirects to auth.tdlx.nl with proper return URL")
    print("2. Auth portal is accessible and shows login form") 
    print("3. Static assets (CSS, images) are accessible without auth")
    print("4. Public API endpoints return 200")
    print("5. Protected API endpoints redirect to auth")
    print()
    print("If all tests pass, the authentication flow is working correctly!")
    print("Users should be able to:")
    print("• Access dashboard → get redirected to login")
    print("• Login successfully → get redirected back to dashboard")
    print("• See dashboard with proper styling (CSS loaded)")
    print("• See user info and admin button (if admin)")

if __name__ == "__main__":
    test_dashboard_flow()