# Energy Pebble - Claude AI Assistant Context

## Project Overview
Energy Pebble is a REST API that provides electricity price color codes (Green, Yellow, Red) based on day-ahead prices from Elia's grid data endpoint. The system helps users optimize their energy consumption by showing when electricity is cheapest.

## Architecture
- **FastAPI**: Python API serving electricity price data and color codes
- **Caddy**: Web server serving static HTML interface
- **Authelia**: Authentication and authorization server with 2FA support
- **Traefik**: Reverse proxy routing traffic between services with forward auth
- **Docker Compose**: Container orchestration

## Key Features
- **Commitment-based color stability**: Colors are locked for 8 hours to prevent user confusion
- **Extended reference window**: Uses up to 48 hours of price data for stable color calculations
- **Real-time data**: Fetches from Elia's day-ahead pricing API
- **Clean web interface**: Shows current color codes with stability indicators
- **User authentication**: Authelia-based authentication with protected user area
- **Device management**: Automatic detection and pairing of Energy Dot hardware devices
- **Energy secrets**: Fun, educational content for authenticated users
- **Interface languages**: English, Dutch and French, chosen per account

## API Endpoints

### Public Endpoints
- `GET /api/color-code`: Get stable color codes for current hour and next 7 hours
- `GET /api/json`: Get raw electricity price data in JSON format
- `GET /api/sample`: Get sample data for testing
- `GET /api/sample-color-code`: Get sample color codes for testing
- `GET /docs`: Swagger UI documentation

### Device Management (Protected)
- `GET /api/devices`: Get detected devices from client's IP address
- `POST /api/devices/{id}/claim`: Claim a device and assign nickname (requires auth)
- `GET /api/user/devices`: Get all devices claimed by authenticated user
- `GET/PUT /api/user/preferences`: Account-level preferences — currently the interface `language` (requires auth)

## Web Routes
- `GET /`: Public landing page with color codes and API information
- `GET /dashboard`: Protected area with energy secrets (requires authentication)
- `GET /api/verify`: Authelia verification endpoint
- `GET /api/authz/*`: Authelia authorization endpoints

## File Structure
```
energy_pebble/
├── main.py                 # FastAPI application
├── requirements.txt        # Python dependencies
├── Dockerfile             # Docker container config
├── docker-compose.yml     # Multi-service orchestration
├── Caddyfile             # Caddy web server config
├── authelia/             # Authentication configuration
│   ├── config/
│   │   ├── configuration.yml  # Authelia main config
│   │   └── users.yml         # User database
│   └── secrets/              # Security secrets
│       ├── jwt_secret
│       ├── session_secret
│       └── storage_encryption_key
├── static/               # Static web assets
│   ├── index.html        # Main webpage
│   ├── dashboard.html    # Protected dashboard
│   └── energy-pebble-image.jpg  # Project image
├── sample_data.json      # Sample data for testing
├── test_device_detection.py  # Test script for device detection
└── CLAUDE.md            # This file
```

## Device Management System
- **Passive Detection**: Automatically detects Energy Dots making API requests
- **Device Fingerprinting**: Creates unique identifiers based on IP, User-Agent, and timing
- **Backward Compatibility**: Existing devices continue working without changes
- **User Claiming**: Users can claim and name devices detected on their network
- **SQLite Database**: Device data stored in `/tmp/energy_pebble.db`

## Internationalization
The web UI ships in English (`en`), Dutch (`nl`) and French (`fr`). The pebble
itself shows colors and needs no translation.

- **Per account**: the choice lives in the `user_preferences` table and is
  edited under Settings → Account → Language, so it follows the person across
  devices.
- **Logged-out visitors**: resolved from the browser's language, overridable
  with the EN/NL/FR switcher in the top nav; the choice is kept in
  `localStorage` until they sign in, after which the account setting wins.
- **Runtime**: `static/i18n.js` (the small runtime) plus `static/i18n-strings.js`
  (all three catalogs). Load them in that order and **before** `pebble-sim.js`
  and `settings-modal.js`, which register their shadow roots with the runtime
  when they upgrade.
- **Markup**: put the key in an attribute — `data-i18n` (textContent),
  `data-i18n-html` (strings with inline markup), or `data-i18n-<attr>` for
  placeholders, titles and aria labels. Strings built in JavaScript use
  `I18n.t('key', {vars})`, counts use `I18n.plural('key', n)`.
- **Adding a string**: add the key to all three catalogs. `tests/test_i18n.py`
  fails when `nl`/`fr` fall behind `en`, when a key is used but not translated,
  or when a catalog key is never referenced.
- **Scope**: admin pages are deliberately untranslated — they are internal.

## Color Logic
The system uses a commitment-based approach to ensure color stability:

1. **Reference Window**: Analyzes up to 48 hours of price data
2. **Commitment Window**: Locks colors for next 8 hours
3. **Thirds Calculation**: Divides price range into Green (cheapest), Yellow (middle), Red (most expensive)
4. **Stability Cache**: Committed colors are saved to `/tmp/committed_colors.json`

## Development Notes
- **Day-ahead pricing**: New prices published daily at 12:45 CET
- **Color stability**: Once committed, colors don't change for 8 hours
- **Data fetching**: Fetches 3 days of data for extended analysis
- **Price cache**: A fetched day is kept in memory and in
  `/tmp/elia_prices.json`, so page loads no longer hit griddata.elia.be. A
  complete day (96 quarter-hourly entries) is held for 6 hours, a missing or
  partial one is retried after 5 minutes, concurrent requests for the same day
  share a single fetch, and if Elia is unreachable the stale day is served
  rather than an error.
- **Persistence**: Committed colors and cached prices survive container restarts

## Deployment
```bash
docker compose up -d
```

### Static asset caching
Our own HTML, CSS and JS carry no version in their filenames, so Caddy serves
them with `Cache-Control: no-cache` — they revalidate against an ETag, which
costs a 304 and no body. Only vendored libraries (pinned by filename) and
images keep the year-long cache. Extensionless routes (`/`, `/setup/`,
`/dashboard`, `/impact-circle`, `/login`, `/admin/*`) are named explicitly in
the Caddyfile because the `file` matcher cannot see them before the rewrite.

Script and stylesheet tags carry a `?v=` marker. It exists to break caches
populated under the previous year-long policy; with revalidation in place it
does not need bumping on every deploy.

## Domain Configuration
- **Production**: `energypebble.tdlx.nl`
- **Routing**: 
  - `/` → Caddy (static files)
  - `/api/*` → FastAPI (API endpoints)
- **SSL**: Handled by Traefik with Let's Encrypt

## Testing
- Use `/api/sample-color-code` for testing without real API calls
- Sample data includes realistic price patterns and edge cases
- Web interface auto-refreshes every 15 minutes
- Run `python3 test_device_detection.py` to test device detection functionality
- Run `pytest tests/test_i18n.py` after touching any user-facing string

## Dependencies
- FastAPI with CORS support
- httpx for async HTTP requests
- pytz for timezone handling
- requests for testing scripts
- Caddy 2 Alpine for web serving
- Traefik for reverse proxy (external)

## User Authentication
- **Authentication**: Authelia-based authentication with subdomain at `auth.tdlx.nl`
- **Users**: Configured in `authelia/config/users.yml` with secure password hashing
- **Groups**: admins, users
- **Protection**: Only `/dashboard` route requires authentication
- **Session**: 1 hour duration with 5 minute inactivity timeout
- **Security**: All passwords use Argon2ID hashing with strong parameters

## Recent Updates
- **Device Management**: Added automatic detection and pairing system for Energy Dots
- **Dashboard Enhancement**: Updated dashboard with device management interface
- **Backward Compatibility**: Ensured existing devices continue working unchanged
- **Database Integration**: Added SQLite database for device tracking
- **Authentication**: Migrated to `auth.tdlx.nl` subdomain for better security
- **UI Improvements**: Professional top navigation and improved styling