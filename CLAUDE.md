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
- `GET /api/insights`: Last 7 completed days of price swings, what they were worth per load, and the week coloured hour by hour. Public; adds a `personal` block when signed in
- `POST /api/waitlist`: Ask to be told when pebbles are available. Public, rate limited
- `GET /docs`: Swagger UI documentation

### Device Management (Protected)
- `GET /api/devices`: Get detected devices from client's IP address
- `POST /api/devices/{id}/claim`: Claim a device and assign nickname (requires auth)
- `GET /api/user/devices`: Get all devices claimed by authenticated user
- `GET/PUT /api/user/preferences`: Account-level preferences, currently the interface `language` (requires auth)

## Web Routes
- `GET /`: Public landing page with color codes and API information
- `GET /dashboard`: Protected area with device management (requires authentication)
- `GET /insights`: Public. What last week's price swings were worth; adds a personal section when signed in
- `GET /admin/waitlist`: Admin. People who asked to be told when pebbles are available
- `GET /privacy`: Public. What is collected, why, how long it is kept, and how to have it deleted
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
│   ├── base.css          # Design system: tokens + primitives (customer UI)
│   ├── icons.js          # Inline SVG icon set
│   ├── admin.css         # Admin console layer, built on base.css
│   ├── index.html        # Main webpage
│   ├── dashboard.html    # Protected dashboard
│   ├── login.html        # Sign-in page
│   ├── insights.html     # What last week's price swings were worth
│   ├── admin-waitlist.html # Admin: people waiting for a pebble
│   ├── simulator.html    # Scenario simulator
│   ├── setup/index.html  # Device Wi-Fi setup (translated variant; see the file header)
│   ├── pebble-sim.js     # <pebble-sim> web component
│   ├── settings-modal.js # <settings-modal> web component
│   └── energy-pebble-device.jpg  # Product photo
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

## Design System
`static/base.css` is the single stylesheet for the customer-facing UI. Pages
link it and then carry only the CSS that is genuinely theirs; anything that
appears on two pages belongs in `base.css`.

- **Tokens first**: colour, type scale, spacing, radii, elevation and motion
  are all custom properties on `:root`. Never hard-code a hex value or a pixel
  spacing in a page; reach for the token.
- **Dark theme**: a single `@media (prefers-color-scheme: dark)` block
  redefines the semantic tokens (`--bg`, `--surface`, `--text`, `--accent`, the
  signal colours). Components never need their own dark rules. Text on the
  accent uses `--on-accent`, which flips to dark ink in the dark theme so
  primary buttons keep WCAG AA contrast.
- **Colour discipline**: one neutral ramp carries the interface, one green
  accent carries the brand, and green/amber/red are reserved for the price
  signal. Signal elements always spell out their state in words as well, so
  colour is never the only carrier of meaning.
- **Icons**: `static/icons.js` renders an inline SVG for every
  `<i data-icon="name">` placeholder, or `Icons.svg(name, {size})` for markup
  built in JavaScript. Call `Icons.render(root)` after inserting HTML. Emoji
  are not used as interface icons: they render differently per platform and
  ignore the surrounding text colour.
- **Shadow DOM**: `pebble-sim.js` and `settings-modal.js` cannot link
  `base.css`, but custom properties cross the shadow boundary, so their styles
  consume the same tokens with standalone fallbacks.
- **Admin pages** load `base.css` plus `admin.css`. They keep their own class
  names (`.section`, `.stat-card`, `.user-table`, `.status-badge`) because the
  JavaScript that builds their rows speaks that vocabulary; `admin.css` defines
  it once in terms of the shared tokens. Their asset hrefs are root-absolute
  (`/base.css`), because the browser URL is `/admin/users` and a relative href
  would resolve under `/admin/`.

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
  (all three catalogs). Load them in that order and **before** `icons.js`,
  `pebble-sim.js` and `settings-modal.js`; the last two register their shadow
  roots with the runtime when they upgrade.
- **No emoji in strings**: catalog values are text only. Icons belong in the
  markup (see the Design System section), so a translator never has to carry
  one and the same key works next to any icon.
- **Markup**: put the key in an attribute: `data-i18n` (textContent),
  `data-i18n-html` (strings with inline markup), or `data-i18n-<attr>` for
  placeholders, titles and aria labels. Strings built in JavaScript use
  `I18n.t('key', {vars})`, counts use `I18n.plural('key', n)`.
- **Adding a string**: add the key to all three catalogs. `tests/test_i18n.py`
  fails when `nl`/`fr` fall behind `en`, when a key is used but not translated,
  or when a catalog key is never referenced.
- **Scope**: admin pages are deliberately untranslated; they are internal.

## Waitlist
Energy Pebble is not on general sale, so the call to action on `/insights`
collects an address rather than an order.

- **Stored, never mailed from here.** A public endpoint that triggers outbound
  mail is a spam relay, and a failed send loses a signup silently where a row
  cannot. `energypebble@tdlx.nl` appears on the page as the contact and
  deletion address; nothing is sent automatically.
- **Thin by design**: address, timestamp, and which language they were reading.
  It is the only personal data held about someone who is not a user.
- **Deletable**: `DELETE /api/admin/waitlist/{id}`, surfaced as a button on
  `/admin/waitlist`, is how the promise on the form is kept.
- Signing up twice returns the same response as signing up once, so the
  endpoint cannot be used to probe whether an address is on the list.

## Privacy and retention
`static/privacy.html` states what the project collects and how long it keeps
it. It is customer-facing, so it is translated like the rest of the site.

- **Device records are deleted after twelve months** without a connection
  (`DEVICE_RETENTION_DAYS`, `prune_device_records`). They hold the only
  network-identifying data we keep: IP address, user agent and a fingerprint.
  The sweep rides along with device traffic, at most once a day, because there
  is no scheduler in this app.
- **The page and the code must move together.** `tests/test_retention.py` fails
  if `DEVICE_RETENTION_DAYS` changes without the catalog sentence changing too.
- **Account deletion is manual** for now: people email energypebble@tdlx.nl.
  The page says so plainly rather than implying a button that does not exist.
- Data lives on a DigitalOcean droplet in Amsterdam. Elia and Open-Meteo are
  the only outside services involved, and neither receives personal data.

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
- **Persistence**: Committed colors survive container restarts

## Deployment
```bash
docker compose up -d
```

### Static asset caching
Our own HTML, CSS and JS carry no version in their filenames, so Caddy serves
them with `Cache-Control: no-cache`; they revalidate against an ETag, which
costs a 304 and no body. Only vendored libraries (pinned by filename) and
images keep the year-long cache. Extensionless routes (`/`, `/setup/`,
`/dashboard`, `/insights`, `/login`, `/admin/*`) are named explicitly in
the Caddyfile because the `file` matcher cannot see them before the rewrite.

Script and stylesheet tags carry a `?v=` marker. It exists to break caches
populated under the previous year-long policy; with revalidation in place it
does not need bumping on every deploy.

Bump it when an asset's *content* changes in a way the HTML depends on. A
browser still holding a year-long copy from before the revalidation policy
will fetch the new HTML (it revalidates) but keep the old script, and the two
disagree: the design-system rewrite hit exactly that, pairing new markup that
draws its own chevron with an old catalog whose string still ended in a
literal triangle.

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
- **UI redesign**: single `base.css` design system with light/dark tokens,
  an SVG icon set replacing emoji, and reworked home/dashboard/login/impact/
  simulator/setup layouts
- **Admin console migrated**: the four admin pages now build on `base.css` +
  `admin.css`; `components.css` is retired
- **Device Management**: Added automatic detection and pairing system for Energy Dots
- **Dashboard Enhancement**: Updated dashboard with device management interface
- **Backward Compatibility**: Ensured existing devices continue working unchanged
- **Database Integration**: Added SQLite database for device tracking
- **Authentication**: Migrated to `auth.tdlx.nl` subdomain for better security
- **UI Improvements**: Professional top navigation and improved styling