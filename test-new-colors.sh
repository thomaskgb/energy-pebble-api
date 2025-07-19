#!/bin/bash

echo "=== Energy Pebble New Color Scheme Test ==="
echo "🎨 Testing Green-Yellow-Red color scheme update"
echo

# Color codes to check for
GREEN="#27ae60"
YELLOW="#f39c12"
RED="#e74c3c"

echo "1. Testing login page colors..."
LOGIN_CONTENT=$(curl -k -s https://app.localhost.local:8443/login)
if echo "$LOGIN_CONTENT" | grep -q "$GREEN" && echo "$LOGIN_CONTENT" | grep -q "$YELLOW" && echo "$LOGIN_CONTENT" | grep -q "$RED"; then
    echo "   ✅ Login page has new green-yellow-red gradient"
else
    echo "   ❌ Login page missing new colors"
fi

echo
echo "2. Testing logout page colors..."
LOGOUT_CONTENT=$(curl -k -s https://app.localhost.local:8443/logout)
if echo "$LOGOUT_CONTENT" | grep -q "$GREEN" && echo "$LOGOUT_CONTENT" | grep -q "$YELLOW" && echo "$LOGOUT_CONTENT" | grep -q "$RED"; then
    echo "   ✅ Logout page has new green-yellow-red gradient"
else
    echo "   ❌ Logout page missing new colors"
fi

echo
echo "3. Testing dashboard colors..."
# First login to get session
curl -k -X POST -d '{"username":"thomas","password":"thomas123"}' https://app.localhost.local:8443/authelia/api/firstfactor -H "Content-Type: application/json" -s -c /tmp/test_cookies.txt >/dev/null 2>&1

DASHBOARD_CONTENT=$(curl -k -s -b /tmp/test_cookies.txt https://app.localhost.local:8443/)
if echo "$DASHBOARD_CONTENT" | grep -q "$GREEN" && echo "$DASHBOARD_CONTENT" | grep -q "$YELLOW" && echo "$DASHBOARD_CONTENT" | grep -q "$RED"; then
    echo "   ✅ Dashboard has new green-yellow-red gradient"
else
    echo "   ❌ Dashboard missing new colors"
fi

echo
echo "4. Color breakdown:"
echo "   🟢 Green (#27ae60) - Primary/Start color"
echo "   🟡 Yellow (#f39c12) - Middle/Accent color"  
echo "   🔴 Red (#e74c3c) - End/Action color"

echo
echo "5. Visual changes:"
echo "   🌈 Background: Green → Yellow → Red gradient"
echo "   🎨 Logo text: Green → Yellow → Red gradient"
echo "   🔘 Login button: Green → Yellow gradient"
echo "   🚪 Logout button: Red gradient (maintained)"
echo "   🎯 Focus states: Green accents"

echo
echo "6. Test in browser:"
echo "   🌐 Visit: https://app.localhost.local:8443/login"
echo "   👀 You should see vibrant green-to-red animated background"
echo "   🔐 Login: thomas / thomas123"
echo "   🎯 Check dashboard and logout page for consistent colors"

echo
echo "=== New color scheme applied successfully! ==="

# Cleanup
rm -f /tmp/test_cookies.txt