#!/usr/bin/env python3
"""
Test suite for Energy Pebble authentication flow and API endpoints.
This helps debug issues with Authelia integration and dashboard loading.
"""

import requests
import json
import time
from urllib.parse import urljoin, urlparse
import sys

# Configuration
BASE_URL = "https://energypebble.tdlx.nl"
AUTH_URL = "https://auth.tdlx.nl"

def print_test_header(test_name):
    print(f"\n{'='*60}")
    print(f"TEST: {test_name}")
    print(f"{'='*60}")

def print_result(success, message):
    status = "✅ PASS" if success else "❌ FAIL"
    print(f"{status}: {message}")

def test_public_endpoints():
    """Test that public endpoints are accessible without authentication."""
    print_test_header("Public Endpoints (Should be accessible)")
    
    endpoints = [
        "/",
        "/api/color-code",
        "/api/json", 
        "/api/sample",
        "/api/sample-color-code",
        "/docs",
        "/openapi.json",
        "/components.css"
    ]
    
    session = requests.Session()
    session.verify = False  # Skip SSL verification for local testing
    
    for endpoint in endpoints:
        try:
            url = urljoin(BASE_URL, endpoint)
            response = session.get(url, timeout=10, allow_redirects=False)
            
            if response.status_code == 200:
                print_result(True, f"{endpoint} -> {response.status_code}")
            elif response.status_code == 308:
                print_result(False, f"{endpoint} -> {response.status_code} (Redirect to HTTPS)")
            else:
                print_result(False, f"{endpoint} -> {response.status_code}")
                
        except Exception as e:
            print_result(False, f"{endpoint} -> Error: {str(e)}")

def test_protected_endpoints():
    """Test that protected endpoints redirect to authentication."""
    print_test_header("Protected Endpoints (Should redirect to auth)")
    
    endpoints = [
        "/dashboard",
        "/api/verify",
        "/api/user/devices",
        "/admin/users",
        "/admin/devices",
        "/admin/firmware"
    ]
    
    session = requests.Session()
    session.verify = False
    
    for endpoint in endpoints:
        try:
            url = urljoin(BASE_URL, endpoint)
            response = session.get(url, timeout=10, allow_redirects=False)
            
            if response.status_code in [302, 307, 308]:
                location = response.headers.get('Location', '')
                if 'auth.tdlx.nl' in location:
                    print_result(True, f"{endpoint} -> {response.status_code} (Redirects to auth)")
                else:
                    print_result(False, f"{endpoint} -> {response.status_code} (Redirects to: {location})")
            else:
                print_result(False, f"{endpoint} -> {response.status_code} (Should redirect)")
                
        except Exception as e:
            print_result(False, f"{endpoint} -> Error: {str(e)}")

def test_authelia_portal():
    """Test that Authelia portal is accessible."""
    print_test_header("Authelia Portal Accessibility")
    
    session = requests.Session() 
    session.verify = False
    
    try:
        response = session.get(AUTH_URL, timeout=10)
        
        if response.status_code == 200:
            if 'authelia' in response.text.lower() or 'sign in' in response.text.lower():
                print_result(True, f"Authelia portal accessible and shows login form")
            else:
                print_result(False, f"Authelia portal accessible but content unexpected")
        else:
            print_result(False, f"Authelia portal -> {response.status_code}")
            
    except Exception as e:
        print_result(False, f"Authelia portal -> Error: {str(e)}")

def test_docker_containers():
    """Test that Docker containers are running."""
    print_test_header("Docker Container Status")
    
    import subprocess
    
    try:
        result = subprocess.run(['docker', 'ps', '--format', 'table {{.Names}}\t{{.Status}}'], 
                              capture_output=True, text=True, timeout=10)
        
        if result.returncode == 0:
            lines = result.stdout.strip().split('\n')
            containers = {}
            
            for line in lines[1:]:  # Skip header
                if line.strip():
                    parts = line.split('\t')
                    if len(parts) >= 2:
                        name = parts[0].strip()
                        status = parts[1].strip()
                        containers[name] = status
            
            required_containers = ['authelia', 'energy_pebble-api-1', 'energy_pebble-web-1']
            
            for container in required_containers:
                if container in containers:
                    if 'Up' in containers[container]:
                        print_result(True, f"{container}: {containers[container]}")
                    else:
                        print_result(False, f"{container}: {containers[container]}")
                else:
                    print_result(False, f"{container}: Not found")
                    
        else:
            print_result(False, f"Docker command failed: {result.stderr}")
            
    except Exception as e:
        print_result(False, f"Docker status check error: {str(e)}")

def test_internal_api():
    """Test internal API endpoints directly (bypass Traefik)."""
    print_test_header("Internal API Direct Access")
    
    session = requests.Session()
    
    # Test FastAPI directly on port 8000
    try:
        response = session.get("http://localhost:8000/docs", timeout=5)
        if response.status_code == 200:
            print_result(True, f"FastAPI docs accessible on port 8000")
        else:
            print_result(False, f"FastAPI docs -> {response.status_code}")
    except Exception as e:
        print_result(False, f"FastAPI docs -> Error: {str(e)}")
    
    # Test API verify endpoint directly
    try:
        response = session.get("http://localhost:8000/api/verify", timeout=5)
        if response.status_code == 401:
            print_result(True, f"API /verify responds correctly (401 without auth headers)")
        else:
            print_result(False, f"API /verify -> {response.status_code} (expected 401)")
    except Exception as e:
        print_result(False, f"API /verify -> Error: {str(e)}")
    
    # Test static files on Caddy port 80 (in container)
    try:
        result = subprocess.run(['docker', 'exec', 'energy_pebble-web-1', 'ls', '-la', '/usr/share/caddy/'], 
                              capture_output=True, text=True, timeout=10)
        if result.returncode == 0:
            if 'components.css' in result.stdout and 'dashboard.html' in result.stdout:
                print_result(True, f"Static files present in Caddy container")
            else:
                print_result(False, f"Static files missing in Caddy container")
        else:
            print_result(False, f"Cannot check Caddy container files")
    except Exception as e:
        print_result(False, f"Caddy container check -> Error: {str(e)}")

def test_authelia_config():
    """Test Authelia configuration parsing."""
    print_test_header("Authelia Configuration")
    
    import subprocess
    
    try:
        # Check if Authelia container can read config
        result = subprocess.run(['docker', 'logs', 'authelia', '--tail', '20'], 
                              capture_output=True, text=True, timeout=10)
        
        if result.returncode == 0:
            logs = result.stdout.lower()
            
            if 'error' in logs or 'fatal' in logs:
                print_result(False, f"Authelia logs contain errors:")
                print("Recent logs:")
                print(result.stdout)
            elif 'startup complete' in logs or 'listening' in logs:
                print_result(True, f"Authelia started successfully")
            else:
                print_result(False, f"Authelia status unclear from logs")
                print("Recent logs:")
                print(result.stdout)
        else:
            print_result(False, f"Cannot read Authelia logs")
            
    except Exception as e:
        print_result(False, f"Authelia logs check -> Error: {str(e)}")

def test_traefik_routing():
    """Test if Traefik is properly routing requests."""
    print_test_header("Traefik Routing Test")
    
    session = requests.Session()
    session.verify = False
    
    # Test if requests are reaching the right service
    endpoints_to_test = [
        ("/", "should reach Caddy (web)"),
        ("/api/color-code", "should reach FastAPI (api)"),
        ("/components.css", "should reach Caddy (web)"),
    ]
    
    for endpoint, description in endpoints_to_test:
        try:
            url = urljoin(BASE_URL, endpoint)
            response = session.get(url, timeout=10, allow_redirects=True)
            
            # Check response headers to identify which service responded
            server_header = response.headers.get('Server', '').lower()
            
            if endpoint == "/" and response.status_code == 200:
                if 'caddy' in server_header or 'energy pebble' in response.text.lower():
                    print_result(True, f"{endpoint} -> Caddy (as expected)")
                else:
                    print_result(False, f"{endpoint} -> Wrong service or unexpected response")
                    
            elif endpoint == "/api/color-code":
                if response.status_code == 200 and '"hour_color_codes"' in response.text:
                    print_result(True, f"{endpoint} -> FastAPI (as expected)")
                else:
                    print_result(False, f"{endpoint} -> {response.status_code}, might not be FastAPI")
                    
            elif endpoint == "/components.css":
                if response.status_code == 200 and 'css' in response.headers.get('content-type', '').lower():
                    print_result(True, f"{endpoint} -> CSS file served correctly")
                else:
                    print_result(False, f"{endpoint} -> {response.status_code}, CSS not served properly")
                    
        except Exception as e:
            print_result(False, f"{endpoint} -> Error: {str(e)}")

def main():
    """Run all tests."""
    print("Energy Pebble Authentication Flow Test Suite")
    print("=" * 60)
    
    # Import subprocess here since we use it in multiple functions
    import subprocess
    globals()['subprocess'] = subprocess
    
    # Run all test suites
    test_docker_containers()
    test_authelia_config() 
    test_internal_api()
    test_traefik_routing()
    test_authelia_portal()
    test_public_endpoints()
    test_protected_endpoints()
    
    print(f"\n{'='*60}")
    print("TEST SUITE COMPLETED")
    print(f"{'='*60}")
    
    print("\n📋 DEBUGGING CHECKLIST:")
    print("1. All containers should be 'Up'")
    print("2. Authelia should start without errors")
    print("3. Internal APIs should be accessible") 
    print("4. Public endpoints should return 200")
    print("5. Protected endpoints should redirect to auth.tdlx.nl")
    print("6. Static files (CSS) should be served correctly")
    
    print("\n🔧 NEXT STEPS IF TESTS FAIL:")
    print("- Check Docker logs: docker logs <container_name>")
    print("- Verify Traefik configuration and labels")
    print("- Check DNS resolution for *.tdlx.nl domains")
    print("- Verify SSL certificates are working")

if __name__ == "__main__":
    main()