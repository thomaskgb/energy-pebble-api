#!/bin/bash

echo "=== Testing Login Functionality ==="
echo

echo "1. Testing API login..."
RESPONSE=$(curl -k -X POST -d '{"username":"thomas","password":"thomas123"}' https://auth.localhost.local:8443/api/firstfactor -H "Content-Type: application/json" -s)

if echo "$RESPONSE" | grep -q '"status":"OK"'; then
    echo "   ✅ API login successful"
    echo "   Response: $RESPONSE"
else
    echo "   ❌ API login failed"
    echo "   Response: $RESPONSE"
fi

echo
echo "2. Testing protected app access..."
STATUS=$(curl -k -s -o /dev/null -w "%{http_code}" https://app.localhost.local:8443/)
if [ "$STATUS" = "302" ]; then
    echo "   ✅ App correctly redirects to auth (status: $STATUS)"
else
    echo "   ❌ App not redirecting properly (status: $STATUS)"
fi

echo
echo "3. Manual test instructions:"
echo "   - Visit: https://app.localhost.local:8443"
echo "   - Login with: thomas / thomas123"
echo "   - Should see weather dashboard after successful login"

echo
echo "=== Login test complete! ==="