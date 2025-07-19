#!/bin/bash

echo "=== Testing Caddy + Authelia Setup ==="
echo

echo "1. Checking containers status..."
docker-compose ps

echo
echo "2. Testing individual services..."

echo "   - Authelia health endpoint..."
if curl -k -s https://auth.localhost.local:8443/api/health > /dev/null 2>&1; then
    echo "   ✅ Authelia is responding"
else
    echo "   ❌ Authelia not responding"
fi

echo "   - Webapp through Caddy (should redirect to auth)..."
STATUS=$(curl -k -s -o /dev/null -w "%{http_code}" https://app.localhost.local:8443/)
if [ "$STATUS" = "302" ] || [ "$STATUS" = "200" ]; then
    echo "   ✅ App endpoint responding (status: $STATUS)"
else
    echo "   ❌ App endpoint not responding (status: $STATUS)"
fi

echo
echo "3. Add these entries to your /etc/hosts file:"
echo "127.0.0.1 app.localhost.local"
echo "127.0.0.1 auth.localhost.local"

echo
echo "4. Then visit: https://app.localhost.local:8443"
echo "   Login with: thomas / thomas123"

echo
echo "=== Services are ready! ==="