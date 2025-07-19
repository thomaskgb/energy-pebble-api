#!/bin/bash

echo "=== Energy Pebble Logout Functionality Test ==="
echo

echo "1. Testing logout page accessibility..."
LOGOUT_CONTENT=$(curl -k -s https://app.localhost.local:8443/logout | grep -o "Energy Pebble" | head -1)
if [ "$LOGOUT_CONTENT" = "Energy Pebble" ]; then
    echo "   ✅ Logout page loads successfully"
else
    echo "   ❌ Logout page not loading"
fi

echo
echo "2. Testing logout API endpoint..."
LOGOUT_RESPONSE=$(curl -k -X POST -s https://app.localhost.local:8443/authelia/api/logout)
if echo "$LOGOUT_RESPONSE" | grep -q '"status":"OK"'; then
    echo "   ✅ Logout API works correctly"
    echo "   Response: $LOGOUT_RESPONSE"
else
    echo "   ❌ Logout API failed"
    echo "   Response: $LOGOUT_RESPONSE"
fi

echo
echo "3. Testing dashboard logout button..."
DASHBOARD_CONTENT=$(curl -k -s https://app.localhost.local:8443/ 2>/dev/null | grep -o "Logout" | head -1)
if [ "$DASHBOARD_CONTENT" = "Logout" ]; then
    echo "   ✅ Dashboard has logout button"
else
    echo "   ❌ Dashboard missing logout button"
fi

echo
echo "4. Testing complete logout flow..."
echo "   Step 1: Login..."
LOGIN_RESPONSE=$(curl -k -X POST -d '{"username":"thomas","password":"thomas123"}' https://app.localhost.local:8443/authelia/api/firstfactor -H "Content-Type: application/json" -s -c /tmp/cookies.txt)
if echo "$LOGIN_RESPONSE" | grep -q '"status":"OK"'; then
    echo "   ✅ Login successful"
    
    echo "   Step 2: Logout with session..."
    LOGOUT_WITH_SESSION=$(curl -k -X POST -s -b /tmp/cookies.txt https://app.localhost.local:8443/authelia/api/logout)
    if echo "$LOGOUT_WITH_SESSION" | grep -q '"status":"OK"'; then
        echo "   ✅ Logout with session successful"
    else
        echo "   ❌ Logout with session failed"
    fi
else
    echo "   ❌ Login failed, cannot test logout flow"
fi

echo
echo "5. How to use logout:"
echo "   🎯 After logging in to https://app.localhost.local:8443"
echo "   🔘 Click the red 'Logout' button on the dashboard"
echo "   🚪 Or visit https://app.localhost.local:8443/logout directly"
echo "   ✅ Confirm logout on the Energy Pebble logout page"
echo "   🔄 You'll be redirected to the login page"

echo
echo "=== Logout functionality ready! ==="

# Cleanup
rm -f /tmp/cookies.txt