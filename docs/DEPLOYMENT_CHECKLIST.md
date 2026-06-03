# Energy Pebble Production Deployment Checklist

## 🚀 **Required Updates for Admin Firmware Page**

### **1. Static Files**
- ✅ `static/admin-firmware.html` - New admin firmware management page
- ✅ `static/dashboard.html` - Updated with admin firmware button link

### **2. API Updates**
- ✅ `main.py` - Enhanced firmware management endpoints with public URLs
- ✅ `requirements.txt` - Updated dependencies (python-multipart)

### **3. Configuration Updates**
- ✅ `docker-compose.yml` - Updated Traefik routing for `/admin/*` paths
- ✅ `Caddyfile` - Added admin firmware route handling

### **4. Database State**
- ✅ Clean firmware database (1 valid entry: `energy_dot_v1.0.0.bin`)
- ✅ Physical firmware file exists in `/firmware/` directory

## 📋 **Deployment Steps Needed**

```bash
# On production server:
1. git pull origin main                    # Get latest code
2. docker compose build api               # Rebuild API with updates
3. docker compose up -d                   # Deploy all updates
```

## 🧪 **Expected Results After Deployment**

### **Admin Page Access:**
- **URL:** `https://energypebble.tdlx.nl/admin/firmware`
- **Auth:** Requires login via Authelia
- **Access:** Only `thomas` (admin user) can access
- **Content:** Firmware management dashboard

### **API Endpoints:**
- **Versions:** `GET /api/firmware/versions` (enhanced with URLs)
- **Checksum:** `GET /api/firmware/{filename}/checksum` (new)
- **Download:** `GET /firmware/{filename}` (existing, working)

### **Dashboard:**
- **Firmware Button:** Visible only to admin users
- **Navigation:** Points to `/admin/firmware`

## 🔍 **Current Production Status**

- ✅ API endpoints updated and working
- ✅ Firmware downloads working
- ✅ Checksum endpoint working
- ⚠️ Admin page returns 403 (needs file deployment)
- ⚠️ Dashboard firmware button (needs deployment)

## 🎯 **Verification Commands**

```bash
# Test admin page (should redirect to auth for non-authenticated)
curl -I https://energypebble.tdlx.nl/admin/firmware

# Test API endpoints
curl https://energypebble.tdlx.nl/api/firmware/energy_dot_v1.0.0.bin/checksum

# Test firmware download
curl -I https://energypebble.tdlx.nl/firmware/energy_dot_v1.0.0.bin
```