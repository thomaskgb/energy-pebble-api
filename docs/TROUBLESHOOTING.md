# Troubleshooting Guide

## Authorization Button Not Appearing in FastAPI Docs

### Quick Fix
**Restart the FastAPI server** - The OpenAPI schema is cached, so changes require a restart.

```bash
# Stop the current server and restart
docker compose restart energy-pebble
# OR if running directly:
# Kill the process and restart main.py
```

### Verification Steps

1. **Check the OpenAPI Schema**
   - Go to: `http://your-domain/openapi.json`
   - Look for: `"components": {"securitySchemes": {"bearerAuth": ...}}`
   - Verify protected endpoints have: `"security": [{"bearerAuth": []}]`

2. **Check Server Logs**
   - Look for: `"OpenAPI: Added bearerAuth security scheme, protected X endpoints"`
   - Should show 2 protected endpoints

3. **Browser Cache**
   - Hard refresh the `/docs` page (Ctrl+F5 or Cmd+Shift+R)
   - Try incognito/private mode

### Expected Behavior

✅ **What you should see:**
- Green "Authorize" button in top-right of `/docs`
- Protected endpoints show a lock icon 🔒
- When you click "Authorize", you can enter a token

✅ **How to test:**
1. Go to `/docs`
2. Click "Authorize" button
3. Enter `thomas` in the "Value" field
4. Click "Authorize"
5. Try `GET /api/user/devices` - should work
6. Try `POST /api/devices/{device_id}/claim` - should work

### Common Issues

❌ **No Authorize Button**
- Server needs restart after code changes
- Check browser cache/hard refresh
- Verify OpenAPI schema at `/openapi.json`

❌ **Button Appears but Auth Fails**
- Check token format (just use username like `thomas`)
- Verify endpoint returns user data
- Check server logs for auth errors

❌ **Devices Not Showing in Dashboard**
- Check debug panel in dashboard for your client IP
- Device needs to match your actual IP address
- Try refreshing device data

### Device Visibility Debug

The dashboard shows debug information including:
- Your client IP address  
- Total devices found for your IP
- Claimed vs unclaimed counts
- Raw device data

If device not visible:
1. Note your client IP from debug panel
2. Check database for devices with that IP
3. Add device manually if needed

### API Testing with curl

```bash
# Test public endpoint
curl -X GET "http://localhost:8000/api/devices"

# Test protected endpoint with Bearer token  
curl -X GET "http://localhost:8000/api/user/devices" \
  -H "Authorization: Bearer thomas"

# Claim a device
curl -X POST "http://localhost:8000/api/devices/1/claim" \
  -H "Authorization: Bearer thomas" \
  -H "Content-Type: application/json" \
  -d '{"nickname": "My Device"}'
```

### Database Commands

```bash
# Check devices in database
python3 -c "
import sqlite3
with sqlite3.connect('/tmp/energy_pebble.db') as conn:
    cursor = conn.cursor()
    cursor.execute('SELECT id, client_ip, device_id FROM devices')
    for row in cursor.fetchall():
        print(f'Device {row[0]}: IP={row[1]}, device_id={row[2]}')
"

# Add test device for your IP
python3 -c "
import sqlite3
your_ip = 'YOUR_ACTUAL_IP_HERE'  # Replace with your IP
with sqlite3.connect('/tmp/energy_pebble.db') as conn:
    cursor = conn.cursor()
    cursor.execute('''INSERT OR IGNORE INTO devices 
        (client_ip, device_fingerprint, device_id, first_seen, last_seen, user_agent, request_count)
        VALUES (?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, ?, 1)''',
        (your_ip, f'manual_904fb0453ab4_{your_ip}', '904fb0453ab4', 'manually_added'))
    device_id = cursor.lastrowid
    cursor.execute('INSERT OR IGNORE INTO user_devices (user_id, device_id, nickname) VALUES (?, ?, ?)',
        ('thomas', device_id, 'Thomas Device'))
    conn.commit()
    print(f'Added device for IP {your_ip}')
"
```

### Success Indicators

When everything works correctly:

1. **FastAPI Docs (`/docs`)**:
   - Green "Authorize" button visible
   - Protected endpoints show lock icons
   - Can authenticate with username `thomas`
   - Protected endpoints return data

2. **Dashboard**:
   - Shows device count in stats
   - "Manage My Devices" shows claimed devices
   - Can click devices for popup details
   - Debug panel shows correct IP and device count

3. **API Responses**:
   - `/api/devices` returns devices for your IP
   - `/api/user/devices` returns claimed devices for authenticated user
   - Device popup shows status, connection times, and details