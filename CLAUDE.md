# Energy Pebble - Claude AI Assistant Context

## Project Overview
Energy Pebble is a REST API that provides electricity price color codes (Green, Yellow, Red) based on day-ahead prices from Elia's grid data endpoint. The system helps users optimize their energy consumption by showing when electricity is cheapest.

## Architecture
- **FastAPI**: Python API serving electricity price data and color codes
- **Caddy**: Web server serving static HTML interface
- **Traefik**: Reverse proxy routing traffic between services
- **Docker Compose**: Container orchestration

## Key Features
- **Commitment-based color stability**: Colors are locked for 8 hours to prevent user confusion
- **Extended reference window**: Uses up to 48 hours of price data for stable color calculations
- **Real-time data**: Fetches from Elia's day-ahead pricing API
- **Clean web interface**: Shows current color codes with stability indicators

## API Endpoints
- `GET /api/color-code`: Get stable color codes for current hour and next 7 hours
- `GET /api/json`: Get raw electricity price data in JSON format
- `GET /api/sample`: Get sample data for testing
- `GET /api/sample-color-code`: Get sample color codes for testing
- `GET /docs`: Swagger UI documentation

## File Structure
```
energy_pebble/
├── main.py                 # FastAPI application
├── requirements.txt        # Python dependencies
├── Dockerfile             # Docker container config
├── docker-compose.yml     # Multi-service orchestration
├── Caddyfile             # Caddy web server config
├── static/               # Static web assets
│   ├── index.html        # Main webpage
│   └── energy-pebble-image.jpg  # Project image
├── sample_data.json      # Sample data for testing
└── CLAUDE.md            # This file
```

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

## Dependencies
- FastAPI with CORS support
- httpx for async HTTP requests
- pytz for timezone handling
- Caddy 2 Alpine for web serving
- Traefik for reverse proxy (external)

## Recent Updates
- Implemented commitment-based color stability
- Added extended 48-hour reference window
- Created clean web interface with stability indicators
- Added Caddy web server for static file serving
- Updated Traefik routing for multi-service architecture