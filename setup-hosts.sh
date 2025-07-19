#!/bin/bash

echo "Adding entries to /etc/hosts..."
echo "You'll need to run this with sudo privileges"

# Check if entries already exist
if ! grep -q "app.localhost.local" /etc/hosts; then
    echo "127.0.0.1 app.localhost.local" | sudo tee -a /etc/hosts
    echo "✅ Added app.localhost.local"
else
    echo "✅ app.localhost.local already exists"
fi

if ! grep -q "auth.localhost.local" /etc/hosts; then
    echo "127.0.0.1 auth.localhost.local" | sudo tee -a /etc/hosts  
    echo "✅ Added auth.localhost.local"
else
    echo "✅ auth.localhost.local already exists"
fi

echo ""
echo "Testing DNS resolution..."
if nslookup app.localhost.local > /dev/null 2>&1; then
    echo "✅ app.localhost.local resolves"
else
    echo "❌ app.localhost.local doesn't resolve"
fi

if nslookup auth.localhost.local > /dev/null 2>&1; then
    echo "✅ auth.localhost.local resolves"  
else
    echo "❌ auth.localhost.local doesn't resolve"
fi

echo ""
echo "Now try visiting https://app.localhost.local:8443"