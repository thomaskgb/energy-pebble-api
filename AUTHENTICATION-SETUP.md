# Energy Pebble Authentication System

This branch contains the updated authentication system with beautiful Energy Pebble styling and green-yellow-red color scheme.

## 🎨 Features

- **Beautiful Login Page**: Custom Energy Pebble styling with animated gradient background
- **Secure Authentication**: Powered by Authelia with Argon2 password hashing
- **Logout Functionality**: Proper session management with styled logout page
- **Consistent Branding**: Green-yellow-red color scheme across all pages
- **HTTPS Security**: All communications secured with Caddy's automatic HTTPS

## 🚀 Quick Start

1. **Add DNS entries** (required for HTTPS):
   ```bash
   sudo ./setup-hosts.sh
   ```

2. **Start the services**:
   ```bash
   docker-compose -f docker-compose-new.yml up -d
   ```

3. **Access the application**:
   - Visit: `https://app.localhost.local:8443`
   - Login: `thomas` / `thomas123`
   - Logout: Click logout button or visit `/logout`

## 📁 File Structure

### Updated Files
- `static/login.html` - Beautiful Energy Pebble login page
- `static/logout.html` - New logout page with confirmation
- `static/dashboard-new.html` - Updated dashboard with logout button
- `authelia.yml` - Authelia configuration
- `users_database.yml` - User database with working thomas account
- `Caddyfile-new` - Caddy configuration with authentication
- `docker-compose-new.yml` - Complete Docker setup

### Test Scripts
- `test-energy-pebble-login.sh` - Test login functionality
- `test-logout.sh` - Test logout functionality  
- `test-new-colors.sh` - Test color scheme
- `setup-hosts.sh` - Set up DNS entries

## 🌈 Color Scheme

The new Energy Pebble theme uses:
- 🟢 **Green** (#27ae60) - Primary/start color
- 🟡 **Yellow** (#f39c12) - Middle/accent color
- 🔴 **Red** (#e74c3c) - End/action color

## 🔧 Configuration

### Default User
- **Username**: `thomas`
- **Password**: `thomas123`
- **Groups**: `admins`, `dev`

### URLs
- **Main App**: `https://app.localhost.local:8443`
- **Login**: `https://app.localhost.local:8443/login`
- **Logout**: `https://app.localhost.local:8443/logout`
- **Authelia Admin**: `https://auth.localhost.local:8443`

## 🧪 Testing

Run the test scripts to verify functionality:

```bash
# Test complete login system
./test-energy-pebble-login.sh

# Test logout functionality
./test-logout.sh

# Test new color scheme
./test-new-colors.sh
```

## 🔄 Migration from Previous Setup

To use this new authentication system:

1. Stop existing services
2. Backup current configuration
3. Use the new Docker Compose file: `docker-compose-new.yml`
4. Use the new Caddyfile: `Caddyfile-new`
5. Run setup scripts to configure DNS

## 🛠️ Development

The system includes:
- Automatic HTTPS with Caddy
- Session-based authentication
- Secure password hashing
- CSRF protection
- Proper logout handling

## 📝 Notes

- HTTPS is required for Authelia session cookies
- DNS entries are required for proper certificate generation
- All styling uses embedded CSS for easy deployment
- Color scheme can be easily modified in the CSS sections

---

Created with ⚡ Energy Pebble styling and 🔒 Authelia security