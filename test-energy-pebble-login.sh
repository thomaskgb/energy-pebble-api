#!/bin/bash

echo "=== Energy Pebble Login Page Test ==="
echo

echo "1. Testing main app redirect..."
STATUS=$(curl -k -s -o /dev/null -w "%{http_code}" https://app.localhost.local:8443/)
if [ "$STATUS" = "302" ]; then
    echo "   ✅ App correctly redirects to login (status: $STATUS)"
else
    echo "   ❌ App redirect failed (status: $STATUS)"
fi

echo
echo "2. Testing custom Energy Pebble login page..."
CONTENT=$(curl -k -s https://app.localhost.local:8443/login | grep -o "Energy Pebble" | head -1)
if [ "$CONTENT" = "Energy Pebble" ]; then
    echo "   ✅ Energy Pebble login page loads successfully"
else
    echo "   ❌ Energy Pebble login page not loading"
fi

echo
echo "3. Testing login functionality..."
RESPONSE=$(curl -k -X POST -d '{"username":"thomas","password":"thomas123"}' https://app.localhost.local:8443/authelia/api/firstfactor -H "Content-Type: application/json" -s)

if echo "$RESPONSE" | grep -q '"status":"OK"'; then
    echo "   ✅ Login API works correctly"
    echo "   Response: $RESPONSE"
else
    echo "   ❌ Login API failed"
    echo "   Response: $RESPONSE"
fi

echo
echo "4. Visual test:"
echo "   🌐 Visit: https://app.localhost.local:8443"
echo "   👀 You should see the beautiful Energy Pebble login page with:"
echo "      - Animated gradient background (blue to green to orange)"
echo "      - Glassmorphism login card"
echo "      - Energy Pebble branding with ⚡ icon"
echo "      - Smooth animations and hover effects"
echo "   🔐 Login with: thomas / thomas123"
echo "   🎯 After login: Weather dashboard with 'Hello, Thomas!'"

echo
echo "=== Energy Pebble styling complete! ==="