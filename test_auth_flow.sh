#!/bin/bash

# Energy Pebble Authentication Flow Test Script
# This script tests the complete authentication flow

set -e

BASE_URL="https://energypebble.tdlx.nl"
TEMP_DIR="/tmp/auth_test_$$"
mkdir -p "$TEMP_DIR"

echo "🔍 Energy Pebble Authentication Flow Test"
echo "=========================================="

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Helper functions
log_info() {
    echo -e "${GREEN}✓${NC} $1"
}

log_warning() {
    echo -e "${YELLOW}⚠${NC} $1"
}

log_error() {
    echo -e "${RED}✗${NC} $1"
}

# Test 1: Check if services are running
echo -e "\n📋 Test 1: Service Health Check"
echo "--------------------------------"

# Check API service
if curl -s -f "$BASE_URL/api/color-code" > /dev/null; then
    log_info "API service is responding"
else
    log_error "API service is not responding"
    exit 1
fi

# Check main web service
if curl -s -f "$BASE_URL/" > /dev/null; then
    log_info "Web service is responding"
else
    log_error "Web service is not responding"
    exit 1
fi

# Test 2: Test Authelia endpoints
echo -e "\n🔐 Test 2: Authelia Endpoint Test"
echo "--------------------------------"

# Test Authelia health (should be accessible)
AUTHELIA_HEALTH=$(curl -s -o /dev/null -w "%{http_code}" "$BASE_URL/api/verify")
if [ "$AUTHELIA_HEALTH" = "401" ] || [ "$AUTHELIA_HEALTH" = "200" ]; then
    log_info "Authelia /api/verify endpoint is accessible (HTTP $AUTHELIA_HEALTH)"
else
    log_error "Authelia /api/verify endpoint returned HTTP $AUTHELIA_HEALTH"
fi

# Test Authelia portal
AUTHELIA_PORTAL=$(curl -s -o /dev/null -w "%{http_code}" "$BASE_URL/authelia/")
if [ "$AUTHELIA_PORTAL" = "200" ]; then
    log_info "Authelia portal is accessible (HTTP $AUTHELIA_PORTAL)"
else
    log_warning "Authelia portal returned HTTP $AUTHELIA_PORTAL (might need trailing slash)"
fi

# Test 3: Test protected dashboard access
echo -e "\n🛡️  Test 3: Protected Dashboard Access"
echo "------------------------------------"

# Test dashboard without authentication (should redirect)
DASHBOARD_RESPONSE=$(curl -s -o "$TEMP_DIR/dashboard_response.html" -w "%{http_code}|%{redirect_url}" "$BASE_URL/dashboard")
HTTP_CODE=$(echo "$DASHBOARD_RESPONSE" | cut -d'|' -f1)
REDIRECT_URL=$(echo "$DASHBOARD_RESPONSE" | cut -d'|' -f2)

echo "Dashboard access without auth: HTTP $HTTP_CODE"
if [ "$HTTP_CODE" = "302" ] || [ "$HTTP_CODE" = "401" ]; then
    log_info "Dashboard is properly protected (HTTP $HTTP_CODE)"
    if [ ! -z "$REDIRECT_URL" ]; then
        log_info "Redirect URL: $REDIRECT_URL"
    fi
else
    log_error "Dashboard should be protected but returned HTTP $HTTP_CODE"
    echo "Response content:"
    cat "$TEMP_DIR/dashboard_response.html"
fi

# Test 4: Test forward auth flow
echo -e "\n🔄 Test 4: Forward Auth Flow"
echo "----------------------------"

# Test with curl following redirects
echo "Testing full redirect flow..."
FULL_FLOW=$(curl -s -L -o "$TEMP_DIR/full_flow.html" -w "%{http_code}|%{url_effective}" "$BASE_URL/dashboard")
FINAL_CODE=$(echo "$FULL_FLOW" | cut -d'|' -f1)
FINAL_URL=$(echo "$FULL_FLOW" | cut -d'|' -f2)

echo "Final HTTP code: $FINAL_CODE"
echo "Final URL: $FINAL_URL"

if [[ "$FINAL_URL" == *"authelia"* ]]; then
    log_info "Successfully redirected to Authelia login"
    # Check if login form is present
    if grep -q "username" "$TEMP_DIR/full_flow.html"; then
        log_info "Login form found in response"
    else
        log_warning "Login form not found in response"
    fi
else
    log_error "Did not redirect to Authelia login page"
    echo "Response content preview:"
    head -20 "$TEMP_DIR/full_flow.html"
fi

# Test 5: Test public endpoints (should work without auth)
echo -e "\n🌐 Test 5: Public Endpoint Access"
echo "--------------------------------"

# Test API endpoints (should be public)
API_ENDPOINTS=("/api/color-code" "/api/json" "/api/sample")
for endpoint in "${API_ENDPOINTS[@]}"; do
    if curl -s -f "$BASE_URL$endpoint" > /dev/null; then
        log_info "Public endpoint $endpoint is accessible"
    else
        log_error "Public endpoint $endpoint is not accessible"
    fi
done

# Test 6: Check Traefik routing
echo -e "\n🛣️  Test 6: Traefik Routing Analysis"
echo "-----------------------------------"

# Test different paths to see routing
echo "Testing various paths..."
PATHS=("/" "/dashboard" "/api/verify" "/authelia" "/api/authz/forward-auth")

for path in "${PATHS[@]}"; do
    response=$(curl -s -o /dev/null -w "%{http_code}" "$BASE_URL$path")
    echo "  $path → HTTP $response"
done

# Test 7: Docker container status
echo -e "\n🐳 Test 7: Docker Container Status"
echo "---------------------------------"

docker compose ps --format "table {{.Service}}\t{{.Status}}\t{{.Ports}}"

# Clean up
rm -rf "$TEMP_DIR"

echo -e "\n📊 Test Summary"
echo "==============="
echo "Review the results above to identify any issues."
echo "Look for:"
echo "- All services should be running and healthy"
echo "- Dashboard should redirect to Authelia login"
echo "- Public API endpoints should be accessible"
echo "- Authelia endpoints should be reachable"

echo -e "\n🔍 Next Steps:"
echo "1. If dashboard returns 401, check Traefik middleware configuration"
echo "2. If no redirect happens, check access control rules in Authelia"
echo "3. If login form is missing, check Authelia portal configuration"