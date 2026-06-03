# FastAPI Authentication Guide

## Overview

The Energy Pebble API now supports authentication in the FastAPI documentation interface (`/docs`). This allows you to test both public and protected endpoints directly from the Swagger UI.

## How to Authenticate in FastAPI Docs

1. **Navigate to the API docs**: Go to `http://your-domain/docs`

2. **Click the "Authorize" button** in the top-right of the Swagger UI

3. **Enter your authentication token**:
   - **Format 1**: Just your username (e.g., `thomas`)
   - **Format 2**: Base64 encoded username (e.g., `dGhvbWFz` for "thomas")
   - **Format 3**: Base64 encoded "username:password" (e.g., `dGhvbWFzOnBhc3N3b3Jk` for "thomas:password")

4. **Click "Authorize"** to save the token

5. **Test protected endpoints**: You can now use the "Try it out" feature on protected endpoints like:
   - `POST /api/devices/{device_id}/claim`
   - `GET /api/user/devices`

## API Endpoint Categories

### 🟢 Public Endpoints (No Authentication Required)
- `GET /` - Root endpoint with API information
- `GET /api/json` - Get electricity price data
- `GET /api/color-code` - Get color codes for current and future hours
- `GET /api/sample` - Get sample electricity price data
- `GET /api/sample-color-code` - Get sample color codes
- `GET /api/devices` - Get detected devices from your IP
- `GET /api/diagnostic` - Diagnostic endpoint

### 🔒 Protected Endpoints (Authentication Required)
- `POST /api/devices/{device_id}/claim` - Claim a device and assign nickname
- `GET /api/user/devices` - Get all devices claimed by authenticated user

## Quick Test

To quickly test authentication:

1. Go to `/docs`
2. Click "Authorize" 
3. Enter `thomas` as the token
4. Try the `GET /api/user/devices` endpoint
5. You should see the device "904fb0453ab4" claimed by user thomas

## Authentication Methods

The API supports dual authentication:

1. **Authelia Headers** (for normal web requests): Uses `Remote-User` header set by the Authelia proxy
2. **Bearer Token** (for API docs): Uses the `Authorization: Bearer <token>` header

## Example cURL Commands

```bash
# Public endpoint (no auth needed)
curl -X GET "http://localhost:8000/api/devices"

# Protected endpoint with Bearer token
curl -X GET "http://localhost:8000/api/user/devices" \
  -H "Authorization: Bearer thomas"

# Claim a device
curl -X POST "http://localhost:8000/api/devices/1/claim" \
  -H "Authorization: Bearer thomas" \
  -H "Content-Type: application/json" \
  -d '{"nickname": "My Energy Dot"}'
```

## Security Notes

- In production, implement proper token validation
- The current implementation accepts simple usernames for demonstration
- Consider using JWT tokens or OAuth2 for production deployments
- Always use HTTPS in production