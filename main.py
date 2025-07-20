from fastapi import FastAPI, HTTPException, Request, Query, Depends, Security
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
import httpx
from datetime import datetime, timedelta
import pytz
import logging
from fastapi.middleware.cors import CORSMiddleware
from typing import List, Dict, Any, Optional
import re
import json
import hashlib
from pathlib import Path
import sqlite3
import threading
import time

app = FastAPI(
    title="Electricity Price API", 
    description="API that provides electricity price data and color-coded indicators",
    openapi_tags=[
        {
            "name": "public",
            "description": "Public endpoints that don't require authentication",
        },
        {
            "name": "devices",
            "description": "Device management endpoints (authentication required for some)",
        },
        {
            "name": "user",
            "description": "User-specific endpoints (authentication required)",
        },
    ]
)

# Configure security scheme for OpenAPI docs  
from fastapi.openapi.utils import get_openapi

def custom_openapi():
    if app.openapi_schema:
        return app.openapi_schema
    
    openapi_schema = get_openapi(
        title=app.title,
        version="1.0.0",
        description=app.description,
        routes=app.routes,
    )
    
    # Ensure components exists
    if "components" not in openapi_schema:
        openapi_schema["components"] = {}
    
    # Add security scheme
    openapi_schema["components"]["securitySchemes"] = {
        "bearerAuth": {
            "type": "http",
            "scheme": "bearer",
            "bearerFormat": "Token",
            "description": "Enter your username (e.g., 'thomas') or encoded token"
        }
    }
    
    # Note: We handle authentication manually in the endpoint functions
    # No need to add security requirements in OpenAPI since we use custom auth logic
    app.openapi_schema = openapi_schema
    return app.openapi_schema

app.openapi = custom_openapi

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Security scheme for OpenAPI docs
security = HTTPBearer()

def get_current_user(request: Request):
    """
    Get current user from Authelia headers or Bearer token.
    This function supports both Authelia proxy headers and Bearer token authentication for the docs.
    """
    # First try to get user from Authelia headers (for normal web requests)
    user_id = request.headers.get("Remote-User")
    if user_id:
        return user_id
    
    # Try to get from Authorization header for API docs
    auth_header = request.headers.get("Authorization")
    if auth_header and auth_header.startswith("Bearer "):
        token = auth_header[7:]  # Remove "Bearer " prefix
        if token:
            # Simple token format: "user:password" base64 encoded or just username
            try:
                import base64
                decoded = base64.b64decode(token).decode('utf-8')
                if ':' in decoded:
                    username = decoded.split(':')[0]
                else:
                    username = decoded
                return username
            except:
                # If not base64, treat as plain username for demo
                return token
    
    raise HTTPException(
        status_code=401,
        detail="Not authenticated",
        headers={"WWW-Authenticate": "Bearer"},
    )

def get_optional_user(request: Request) -> Optional[str]:
    """Get user from headers without raising exception if not authenticated."""
    return request.headers.get("Remote-User")

# Database setup
DB_PATH = Path("/tmp/energy_pebble.db")
db_lock = threading.Lock()

def init_database():
    """Initialize the SQLite database with required tables."""
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        
        # Create devices table for tracking energy dots
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS devices (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                client_ip TEXT NOT NULL,
                device_fingerprint TEXT UNIQUE NOT NULL,
                first_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                user_agent TEXT,
                request_count INTEGER DEFAULT 1,
                device_id TEXT UNIQUE,
                hardware_id INTEGER,
                mac_address TEXT,
                software_version TEXT,
                UNIQUE(client_ip, device_fingerprint)
            )
        ''')
        
        # Create user_devices table for device ownership
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS user_devices (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                device_id INTEGER NOT NULL,
                nickname TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (device_id) REFERENCES devices (id)
            )
        ''')
        
        # Add new columns to existing devices table if they don't exist
        try:
            cursor.execute('ALTER TABLE devices ADD COLUMN hardware_id INTEGER')
            logger.info("Added hardware_id column to devices table")
        except sqlite3.OperationalError:
            pass  # Column already exists
            
        try:
            cursor.execute('ALTER TABLE devices ADD COLUMN mac_address TEXT')
            logger.info("Added mac_address column to devices table")
        except sqlite3.OperationalError:
            pass  # Column already exists
            
        try:
            cursor.execute('ALTER TABLE devices ADD COLUMN software_version TEXT')
            logger.info("Added software_version column to devices table")
        except sqlite3.OperationalError:
            pass  # Column already exists
        
        # Create index for performance
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_devices_ip ON devices (client_ip)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_devices_fingerprint ON devices (device_fingerprint)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_user_devices_user ON user_devices (user_id)')
        
        # Insert predefined devices if they don't exist
        predefined_devices = [
            (10, "v1", "B4:3A:45:B0:50:A8"),
            (9, "v1", "B4:3A:45:B0:4F:90"),
            (8, "v1", "B4:3A:45:B0:5A:6C"),
            (6, "v1", "B8:F8:62:D8:68:68"),
            (5, "v1", "B4:3A:45:B0:58:E8"),
            (4, "v1", "B4:3A:45:B0:5E:BC"),
            (3, "v1", "24:EC:4A:2F:2E:9C"),
            (2, "v1", "24:EC:4A:2F:2D:04"),
            (1, "v1", "24:EC:4A:2F:C5:D4"),
        ]
        
        for hardware_id, software_version, mac_address in predefined_devices:
            # Check if device with this hardware_id already exists
            cursor.execute('SELECT id FROM devices WHERE hardware_id = ?', (hardware_id,))
            if not cursor.fetchone():
                # Insert as a placeholder device with minimal data
                cursor.execute('''
                    INSERT INTO devices 
                    (client_ip, device_fingerprint, hardware_id, mac_address, software_version, first_seen, last_seen)
                    VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                ''', (
                    f"unknown_{hardware_id}",  # Placeholder IP
                    f"hardware_{hardware_id}_{mac_address}",  # Unique fingerprint
                    hardware_id,
                    mac_address,
                    software_version
                ))
                logger.info(f"Added predefined device {hardware_id} with MAC {mac_address}")
        
        conn.commit()
        logger.info("Database initialized successfully")

def get_real_client_ip(request: Request) -> str:
    """Extract real client IP from proxy headers."""
    return (
        request.headers.get("cf-connecting-ip") or  # Cloudflare real IP
        request.headers.get("x-real-ip") or        # Standard proxy header
        request.headers.get("x-forwarded-for", "").split(",")[0].strip() or  # Standard forwarded header
        (request.client.host if request.client else "unknown")
    )

def calculate_device_status(last_seen_str: str) -> tuple[str, int]:
    """Calculate device status based on last seen timestamp.
    
    Energy Pebbles poll every 15 minutes, so:
    - online: <= 20 minutes ago
    - recently_active: <= 60 minutes ago  
    - offline: > 60 minutes ago
    
    Returns: (status, minutes_since_last_seen)
    """
    try:
        last_seen_dt = datetime.fromisoformat(last_seen_str) if last_seen_str else datetime.min.replace(tzinfo=pytz.UTC)
        now = datetime.now(pytz.UTC)
        minutes_since_last_seen = (now - last_seen_dt).total_seconds() / 60
        
        if minutes_since_last_seen <= 20:
            status = "online"
        elif minutes_since_last_seen <= 60:
            status = "recently_active"
        else:
            status = "offline"
            
        return status, int(minutes_since_last_seen)
    except Exception:
        return "offline", 999999

def create_device_fingerprint(client_ip: str, user_agent: str, timestamp: datetime) -> str:
    """Create a unique fingerprint for device identification."""
    # Use client IP, user agent, and hour of first request to create fingerprint
    hour_key = timestamp.replace(minute=0, second=0, microsecond=0).isoformat()
    fingerprint_data = f"{client_ip}:{user_agent}:{hour_key}"
    return hashlib.sha256(fingerprint_data.encode()).hexdigest()[:16]

def log_device_request(client_ip: str, user_agent: str, device_id: Optional[str] = None):
    """Log a device request for tracking purposes."""
    try:
        with db_lock:
            with sqlite3.connect(DB_PATH) as conn:
                cursor = conn.cursor()
                
                now = datetime.now(pytz.UTC)
                
                if device_id:
                    # If device_id is provided, update or create device by device_id (UUID-based approach)
                    cursor.execute('''
                        UPDATE devices 
                        SET last_seen = ?, request_count = request_count + 1, client_ip = ?
                        WHERE device_id = ?
                    ''', (now, client_ip, device_id))
                    
                    # If no rows updated, insert new device with device_id
                    if cursor.rowcount == 0:
                        fingerprint = create_device_fingerprint(client_ip, user_agent or "unknown", now)
                        cursor.execute('''
                            INSERT OR IGNORE INTO devices 
                            (client_ip, device_fingerprint, first_seen, last_seen, user_agent, device_id)
                            VALUES (?, ?, ?, ?, ?, ?)
                        ''', (client_ip, fingerprint, now, now, user_agent, device_id))
                else:
                    # Fallback to fingerprint-based detection for devices without device_id
                    fingerprint = create_device_fingerprint(client_ip, user_agent or "unknown", now)
                    
                    cursor.execute('''
                        UPDATE devices 
                        SET last_seen = ?, request_count = request_count + 1
                        WHERE device_fingerprint = ? AND device_id IS NULL
                    ''', (now, fingerprint))
                    
                    # If no rows updated, insert new device
                    if cursor.rowcount == 0:
                        cursor.execute('''
                            INSERT OR IGNORE INTO devices 
                            (client_ip, device_fingerprint, first_seen, last_seen, user_agent)
                            VALUES (?, ?, ?, ?, ?)
                        ''', (client_ip, fingerprint, now, now, user_agent))
                
                conn.commit()
                
    except Exception as e:
        logger.error(f"Error logging device request: {e}")

# Initialize database on startup
init_database()

# Add custom logging middleware
@app.middleware("http")
async def log_requests(request: Request, call_next):
    start_time = time.time()
    
    # Get real client IP and device ID for logging
    client_ip = get_real_client_ip(request)
    device_id = request.headers.get("x-device-id") or request.query_params.get("device_id")
    
    
    response = await call_next(request)
    
    # Log with custom format
    process_time = time.time() - start_time
    device_info = f" - device: {device_id}" if device_id else ""
    logger.info(f"{client_ip} - \"{request.method} {request.url.path}{request.url.query and '?' + str(request.url.query) or ''}\" {response.status_code} ({process_time:.3f}s){device_info}")
    
    return response

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allow all origins
    allow_credentials=True,
    allow_methods=["*"],  # Allow all methods
    allow_headers=["*"],  # Allow all headers
)

async def fetch_data(date_str: Optional[str] = None):
    """Fetch data from Elia's API for a given date."""
    if not date_str:
        # Use today's date if not specified
        date_str = datetime.now().strftime("%Y-%m-%d")
    
    url = f"https://griddata.elia.be/eliabecontrols.prod/interface/Interconnections/daily/auctionresultsqh/{date_str}"
    
    logger.info(f"Fetching data from URL: {url}")
    
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(url, timeout=10.0)
            response.raise_for_status()  # Raise an exception for HTTP errors
            
            # Log response status and size
            content = response.text
            logger.info(f"Response status: {response.status_code}, content size: {len(content)} bytes")
            
            # Check for empty response
            if not content:
                logger.warning("Received empty response from Elia API")
            
            # Check if the response is JSON (which appears to be the case)
            try:
                # Try to parse as JSON first
                json_data = response.json()
                logger.info("Successfully parsed response as JSON")
                return json_data
            except:
                # If not JSON, check if it's XML and try to handle it
                if content.strip().startswith("<"):
                    logger.info("Response appears to be XML, not JSON")
                    raise HTTPException(status_code=415, 
                                        detail="Received XML response from Elia API, but JSON was expected. Try using wget or another tool to fetch the data.")
                # If not XML either, return the raw text
                logger.info("Response is not JSON or XML, returning raw text")
                return content
                
    except httpx.HTTPError as e:
        logger.error(f"HTTP error occurred: {e}")
        raise HTTPException(status_code=503, detail=f"Error fetching data from Elia API: {str(e)}")
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        raise HTTPException(status_code=500, detail=f"Unexpected error: {str(e)}")

def should_data_be_available(target_date: datetime) -> bool:
    """
    Check if day-ahead price data should be available for a given date.
    Day-ahead prices are published around 12:45 CET for the next day.
    """
    # Convert target date to CET timezone for comparison
    cet = pytz.timezone('CET')
    now_cet = datetime.now(cet)
    target_date_cet = target_date.replace(tzinfo=cet)
    
    # Data for today should always be available (published yesterday)
    today_cet = now_cet.date()
    target_date_only = target_date_cet.date()
    
    if target_date_only <= today_cet:
        return True
    
    # For tomorrow's data, check if it's after 12:45 CET today
    if target_date_only == today_cet + timedelta(days=1):
        publication_time = now_cet.replace(hour=12, minute=45, second=0, microsecond=0)
        return now_cet >= publication_time
    
    # For dates further in the future, data is not expected to be available yet
    return False

async def fetch_data_for_date_range(start_date: datetime, num_days: int = 3):
    """Fetch data for multiple consecutive days and combine the results."""
    all_data = []
    
    for day_offset in range(num_days):
        # Calculate the date for this offset
        current_date = start_date + timedelta(days=day_offset)
        date_str = current_date.strftime("%Y-%m-%d")
        
        # Skip dates where data definitely won't be available
        if not should_data_be_available(current_date):
            logger.debug(f"Skipping {date_str} - data not yet published (before 12:45 CET)")
            continue
        
        try:
            # Fetch data for this date
            day_data = await fetch_data(date_str)
            if day_data:
                # Append to the combined results
                if isinstance(day_data, list):
                    all_data.extend(day_data)
                else:
                    logger.warning(f"Data for {date_str} is not a list: {type(day_data)}")
            else:
                logger.warning(f"No data available for {date_str} (data should be available)")
        except Exception as e:
            logger.error(f"Error fetching data for {date_str}: {e}")
    
    return all_data

# Global cache for committed colors
committed_colors_cache = {}
cache_file_path = Path("/tmp/committed_colors.json")

def load_committed_colors():
    """Load committed colors from file cache."""
    global committed_colors_cache
    try:
        if cache_file_path.exists():
            with open(cache_file_path, 'r') as f:
                committed_colors_cache = json.load(f)
            logger.info(f"Loaded {len(committed_colors_cache)} committed colors from cache")
        else:
            committed_colors_cache = {}
    except Exception as e:
        logger.error(f"Error loading committed colors: {e}")
        committed_colors_cache = {}

def save_committed_colors():
    """Save committed colors to file cache."""
    try:
        with open(cache_file_path, 'w') as f:
            json.dump(committed_colors_cache, f)
        logger.info(f"Saved {len(committed_colors_cache)} committed colors to cache")
    except Exception as e:
        logger.error(f"Error saving committed colors: {e}")

def get_committed_colors_for_window(commitment_hours: int = 8) -> Dict[str, str]:
    """Get committed colors for the next N hours."""
    now = datetime.now(pytz.UTC).replace(minute=0, second=0, microsecond=0)
    committed_colors = {}
    
    for i in range(commitment_hours):
        target_hour = now + timedelta(hours=i)
        target_key = target_hour.isoformat().replace('+00:00', 'Z')
        
        if target_key in committed_colors_cache:
            committed_colors[target_key] = committed_colors_cache[target_key]
    
    return committed_colors

def commit_colors_for_window(color_codes: List[Dict[str, Any]], commitment_hours: int = 8):
    """Commit colors for the next N hours to ensure stability."""
    global committed_colors_cache
    
    # Load existing committed colors
    load_committed_colors()
    
    # Only commit colors for the first N hours
    for i, color_data in enumerate(color_codes[:commitment_hours]):
        hour_key = color_data["hour"]
        
        # Only commit if not already committed
        if hour_key not in committed_colors_cache:
            committed_colors_cache[hour_key] = color_data["color_code"]
            logger.info(f"Committed color {color_data['color_code']} for hour {hour_key}")
    
    # Clean up old committed colors (older than current time)
    now = datetime.now(pytz.UTC).replace(minute=0, second=0, microsecond=0)
    old_keys = []
    for hour_key in committed_colors_cache:
        try:
            hour_time = datetime.fromisoformat(hour_key.replace('Z', '+00:00'))
            if hour_time < now:
                old_keys.append(hour_key)
        except Exception as e:
            logger.error(f"Error parsing hour key {hour_key}: {e}")
            old_keys.append(hour_key)
    
    for key in old_keys:
        del committed_colors_cache[key]
        logger.info(f"Removed old committed color for hour {key}")
    
    # Save to file
    save_committed_colors()

def apply_committed_colors(color_codes: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Apply committed colors to the color codes, preserving stability."""
    committed_colors = get_committed_colors_for_window()
    
    for color_data in color_codes:
        hour_key = color_data["hour"]
        if hour_key in committed_colors:
            original_color = color_data["color_code"]
            committed_color = committed_colors[hour_key]
            
            if original_color != committed_color:
                logger.info(f"Using committed color {committed_color} instead of calculated {original_color} for hour {hour_key}")
                color_data["color_code"] = committed_color
                color_data["committed"] = True
            else:
                color_data["committed"] = True
        else:
            color_data["committed"] = False
    
    return color_codes

def group_entries_by_hour(entries: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """Group 15-minute entries into hourly data points."""
    hourly_data = {}
    
    for entry in entries:
        # Extract the hour part from the timestamp
        dt = datetime.fromisoformat(entry["dateTime"].replace('Z', '+00:00'))
        hour_key = dt.replace(minute=0, second=0, microsecond=0).isoformat().replace('+00:00', 'Z')
        
        if hour_key not in hourly_data:
            hourly_data[hour_key] = {
                "dateTime": hour_key,
                "prices": [],
                "avgPrice": 0
            }
        
        hourly_data[hour_key]["prices"].append(entry["price"])
    
    # Calculate average price for each hour
    for hour_key, data in hourly_data.items():
        if data["prices"]:
            data["avgPrice"] = sum(data["prices"]) / len(data["prices"])
        
        # Remove the individual prices from the final output
        data.pop("prices")
    
    return hourly_data

def get_current_and_future_hours(hourly_data: Dict[str, Dict[str, Any]], hours: int = 12) -> List[Dict[str, Any]]:
    """Get current hour and future hours data."""
    now = datetime.now(pytz.UTC).replace(minute=0, second=0, microsecond=0)
    result = []
    
    for i in range(hours):
        target_hour = now + timedelta(hours=i)
        target_key = target_hour.isoformat().replace('+00:00', 'Z')
        
        if target_key in hourly_data:
            result.append(hourly_data[target_key])
        # Skip individual hour warnings - day-level warnings are sufficient
    
    return result

def determine_color_codes(hourly_data: List[Dict[str, Any]], reference_window_hours: int = 48) -> List[Dict[str, Any]]:
    """Determine color codes for all hours in the window using extended reference window."""
    if not hourly_data:
        raise HTTPException(status_code=404, detail="No data available for the requested time period")
    
    # Use extended reference window for more stable color calculations
    # This ensures colors are based on a broader price context
    reference_data = hourly_data[:reference_window_hours] if len(hourly_data) >= reference_window_hours else hourly_data
    
    # Extract prices from reference window
    reference_prices = [entry["avgPrice"] for entry in reference_data]
    
    # Find min and max prices across the reference window
    min_price = min(reference_prices)
    max_price = max(reference_prices)
    
    # Calculate range and thresholds based on the extended reference window
    price_range = max_price - min_price
    
    # Initialize result list
    hourly_color_codes = []
    
    # Determine color code for each hour
    for hour_data in hourly_data:
        hour_price = hour_data["avgPrice"]
        
        # Avoid division by zero if all prices are the same
        if price_range == 0:
            color_code = "G"  # Default to green if all prices are equal
        else:
            lower_threshold = min_price + (price_range / 3)
            upper_threshold = max_price - (price_range / 3)
            
            if hour_price <= lower_threshold:
                color_code = "G"  # Green for cheapest third
            elif hour_price <= upper_threshold:
                color_code = "Y"  # Yellow for middle third
            else:
                color_code = "R"  # Red for most expensive third
        
        # Add to result
        hourly_color_codes.append({
            "hour": hour_data["dateTime"],
            "color_code": color_code
        })
    
    return hourly_color_codes

@app.get("/", tags=["public"])
async def root():
    """Root endpoint with API information."""
    return {
        "message": "Electricity Price API",
        "endpoints": {
            "/api/json": "Get electricity price data in JSON format (Optional query param: date=YYYY-MM-DD)",
            "/api/color-code": "Get color codes for current hour and next 11 hours (Optional query params: date=YYYY-MM-DD, device_id=string)",
            "/api/sample": "Get sample electricity price data for testing",
            "/api/sample-color-code": "Get sample color codes for current hour and next 11 hours",
            "/docs": "API documentation (Swagger UI)"
        }
    }

@app.get("/api/json", tags=["public"])
async def get_json_data(date: Optional[str] = None):
    """
    Get electricity price data in JSON format.
    
    Optional query parameter:
    - date: Date in YYYY-MM-DD format
    """
    # Validate date format if provided
    if date and not re.match(r'^\d{4}-\d{2}-\d{2}$', date):
        raise HTTPException(status_code=400, detail="Invalid date format. Use YYYY-MM-DD")
    
    # For testing, can use the sample data from the uploaded document
    use_sample_data = False  # Set to True to use sample data
    
    if use_sample_data:
        # Use sample data from the provided document
        try:
            with open("sample_data.json", "r") as f:
                json_data = json.load(f)
            logger.info("Using sample data from file")
        except Exception as e:
            logger.error(f"Error loading sample data: {e}")
            raise HTTPException(status_code=500, detail=f"Error loading sample data: {str(e)}")
    else:
        # Fetch from API - now handling JSON directly
        json_data = await fetch_data(date)
    
    try:
        return {"data": json_data}
    except Exception as e:
        logger.error(f"Unexpected error in get_json_data: {e}")
        raise HTTPException(status_code=500, detail=f"Error processing request: {str(e)}")

@app.get("/api/color-code", tags=["public"])
async def get_color_code(request: Request, date: Optional[str] = None, device_id: Optional[str] = None):
    """
    Get color codes (G, Y, R) for the current hour and next 7 hours based on price analysis.
    Uses commitment-based stability - colors won't change once committed.
    
    Optional query parameters:
    - date: Date in YYYY-MM-DD format
    - device_id: Device identifier for potential device-specific color logic (future use)
    """
    # Log device request for tracking (non-breaking)
    try:
        client_ip = get_real_client_ip(request)
        user_agent = request.headers.get("user-agent", "unknown")
        final_device_id = device_id or request.headers.get("x-device-id")
        
        # Log request asynchronously to avoid blocking
        log_device_request(client_ip, user_agent, final_device_id)
    except Exception as e:
        logger.warning(f"Device logging failed (non-critical): {e}")
    
    # Validate date format if provided
    if date and not re.match(r'^\d{4}-\d{2}-\d{2}$', date):
        raise HTTPException(status_code=400, detail="Invalid date format. Use YYYY-MM-DD")
    
    # Determine the start date
    if date:
        start_date = datetime.strptime(date, "%Y-%m-%d")
    else:
        start_date = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    
    # Fetch data for multiple days to ensure we have enough hours (3 days for extended reference window)
    json_data = await fetch_data_for_date_range(start_date, num_days=3)
    
    if not json_data:
        raise HTTPException(status_code=404, detail="No data available for the requested date range")
    
    # Group by hour
    hourly_data = group_entries_by_hour(json_data)
    
    # Get current and future hours (48 hours for extended reference window)
    extended_hours_data = get_current_and_future_hours(hourly_data, 48)
    
    if not extended_hours_data:
        raise HTTPException(status_code=404, detail="No data available for the requested time period")
    
    # Get the current hour
    current_hour = extended_hours_data[0]["dateTime"]
    
    # Determine color codes using extended reference window
    color_codes = determine_color_codes(extended_hours_data, reference_window_hours=48)
    
    # Apply commitment logic - preserve committed colors for stability
    color_codes = apply_committed_colors(color_codes)
    
    # Commit new colors for the next 8 hours if not already committed
    commit_colors_for_window(color_codes, commitment_hours=8)
    
    # Return only the first 8 hours for display (current + next 7)
    display_colors = color_codes[:8]
    
    # Add metadata about commitment status
    committed_count = sum(1 for color in display_colors if color.get("committed", False))
    
    # Return both the current hour and display color codes
    return {
        "current_hour": current_hour,
        "hour_color_codes": display_colors,
        "meta": {
            "total_hours": len(display_colors),
            "committed_hours": committed_count,
            "flexible_hours": len(display_colors) - committed_count,
            "reference_window_hours": 48,
            "commitment_window_hours": 8
        }
    }

@app.get("/api/sample", tags=["public"])
async def get_sample_data():
    """
    Get sample electricity price data for testing.
    """
    # Create sample data that includes various price scenarios
    sample_data = []
    
    # Create a datetime series starting from yesterday and spanning 3 days
    start_date = datetime.now(pytz.UTC).replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=1)
    
    # Create sample data with realistic patterns:
    # - Higher prices in morning and evening peaks
    # - Lower prices during night and midday
    # - Occasional negative prices (solar/wind surplus)
    # - 15-minute intervals for each hour
    
    for day_offset in range(3):  # 3 days of data
        current_date = start_date + timedelta(days=day_offset)
        
        for hour in range(24):
            base_time = current_date.replace(hour=hour)
            
            # Create price patterns
            if 0 <= hour < 6:  # Night (low demand)
                base_price = 40.0 + (day_offset * 5)
            elif 6 <= hour < 9:  # Morning peak
                base_price = 120.0 + (day_offset * 10)
            elif 9 <= hour < 14:  # Midday (solar generation)
                # Occasionally negative prices during high solar/wind periods
                if hour == 12 and day_offset == 1:
                    base_price = -10.0
                else:
                    base_price = 30.0 + (day_offset * 5)
            elif 14 <= hour < 17:  # Afternoon
                base_price = 80.0 + (day_offset * 8)
            elif 17 <= hour < 22:  # Evening peak
                base_price = 150.0 + (day_offset * 15)
            else:  # Late evening
                base_price = 70.0 + (day_offset * 5)
                
            # Add some randomness to prices
            price_variation = (hash(f"{current_date.isoformat()}_{hour}") % 20) - 10
            hour_base_price = base_price + price_variation
            
            # Create 15-minute intervals
            for minute in [0, 15, 30, 45]:
                entry_time = base_time.replace(minute=minute)
                # Add slight variation within the hour
                minute_variation = (hash(f"{entry_time.isoformat()}") % 10) - 5
                price = round(hour_base_price + (minute_variation / 10), 4)
                
                sample_data.append({
                    "isVisible": True,
                    "dateTime": entry_time.isoformat().replace('+00:00', 'Z'),
                    "price": price
                })
    
    return {"data": sample_data}

@app.get("/api/sample-color-code", tags=["public"])
async def get_sample_color_code():
    """
    Get sample color codes for the current hour and next 11 hours for testing.
    """
    # Get sample data from the sample endpoint that will span multiple days if needed
    sample_data_response = await get_sample_data()
    sample_data = sample_data_response["data"]
    
    # Group by hour
    hourly_data = group_entries_by_hour(sample_data)
    
    # Get current and future 11 hours (total 12 hours)
    hours_data = get_current_and_future_hours(hourly_data, 12)
    
    if not hours_data:
        raise HTTPException(status_code=404, detail="No sample data available for the requested time period")
    
    # Get the current hour
    current_hour = hours_data[0]["dateTime"]
    
    # Determine color codes for all hours
    color_codes = determine_color_codes(hours_data)
    
    # Return both the current hour and all hour color codes
    return {
        "current_hour": current_hour,
        "hour_color_codes": color_codes
    }

# Device claiming endpoints removed for simplicity
# Devices are now pre-assigned to users via database setup

@app.get("/api/test/user/devices", tags=["user"])
async def test_user_devices(request: Request, user: str = Query("thomas", description="Test user (thomas or willie)")):
    """Test endpoint for local development - allows switching between test users."""
    try:
        user_id = user  # Use query parameter, default to thomas
        
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()
            
            cursor.execute('''
                SELECT d.id, d.device_fingerprint, d.first_seen, d.last_seen, 
                       d.user_agent, d.request_count, d.device_id, d.client_ip,
                       d.hardware_id, d.mac_address, d.software_version,
                       ud.nickname, ud.created_at
                FROM devices d
                JOIN user_devices ud ON d.id = ud.device_id
                WHERE ud.user_id = ?
                ORDER BY d.last_seen DESC
            ''', (user_id,))
            
            devices = []
            for row in cursor.fetchall():
                status, minutes_ago = calculate_device_status(row[3])
                
                device = {
                    "id": row[0],
                    "fingerprint": row[1],
                    "first_seen": row[2],
                    "last_seen": row[3],
                    "user_agent": row[4],
                    "request_count": row[5],
                    "device_id": row[6],
                    "client_ip": row[7],
                    "hardware_id": row[8],
                    "mac_address": row[9],
                    "software_version": row[10],
                    "nickname": row[11],
                    "claimed_at": row[12],
                    "status": status,
                    "minutes_since_last_seen": minutes_ago
                }
                devices.append(device)
            
            return {
                "user_id": user_id,
                "devices": devices,
                "total_devices": len(devices)
            }
            
    except Exception as e:
        logger.error(f"Error fetching test user devices: {e}")
        raise HTTPException(status_code=500, detail=f"Error fetching user devices: {str(e)}")

@app.get("/api/user/devices", tags=["user"])  
async def get_user_devices(request: Request):
    """
    Get all devices claimed by the authenticated user.
    """
    try:
        # Get user directly from authentication function
        user_id = get_current_user(request)
        
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()
            
            cursor.execute('''
                SELECT d.id, d.device_fingerprint, d.first_seen, d.last_seen, 
                       d.user_agent, d.request_count, d.device_id, d.client_ip,
                       d.hardware_id, d.mac_address, d.software_version,
                       ud.nickname, ud.created_at
                FROM devices d
                JOIN user_devices ud ON d.id = ud.device_id
                WHERE ud.user_id = ?
                ORDER BY d.last_seen DESC
            ''', (user_id,))
            
            devices = []
            for row in cursor.fetchall():
                status, minutes_ago = calculate_device_status(row[3])
                
                device = {
                    "id": row[0],
                    "fingerprint": row[1],
                    "first_seen": row[2],
                    "last_seen": row[3],
                    "user_agent": row[4],
                    "request_count": row[5],
                    "device_id": row[6],
                    "client_ip": row[7],
                    "hardware_id": row[8],
                    "mac_address": row[9],
                    "software_version": row[10],
                    "nickname": row[11],
                    "claimed_at": row[12],
                    "status": status,
                    "minutes_since_last_seen": minutes_ago
                }
                devices.append(device)
            
            return {
                "user_id": user_id,
                "devices": devices,
                "total_devices": len(devices)
            }
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching user devices: {e}")
        raise HTTPException(status_code=500, detail=f"Error fetching user devices: {str(e)}")

@app.get("/api/user/profile", tags=["user"])
async def get_user_profile(request: Request):
    """Get current user profile information."""
    try:
        user_id = get_current_user(request)
        
        # For now, return basic user info
        # In a real implementation, you'd fetch from a user database
        return {
            "username": user_id,
            "email": f"{user_id}@example.com",  # Placeholder
            "created_at": "2025-01-01T00:00:00Z"  # Placeholder
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching user profile: {e}")
        raise HTTPException(status_code=500, detail=f"Error fetching user profile: {str(e)}")

@app.get("/api/test/user/profile", tags=["user"])
async def test_get_user_profile(user: str = Query("thomas", description="Test user (thomas or willie)")):
    """Test endpoint for user profile - local development."""
    return {
        "username": user,
        "email": f"{user}@example.com",
        "created_at": "2025-01-01T00:00:00Z"
    }

@app.put("/api/user/profile", tags=["user"])
async def update_user_profile(request: Request):
    """Update user profile (username and password)."""
    try:
        user_id = get_current_user(request)
        body = await request.json()
        
        new_username = body.get("username", "").strip()
        current_password = body.get("currentPassword", "")
        new_password = body.get("newPassword", "")
        
        # Validation
        if not new_username:
            raise HTTPException(status_code=400, detail="Username is required")
        
        # Check username format (letters, numbers, underscores only)
        import re
        if not re.match(r'^[a-zA-Z0-9_]+$', new_username):
            raise HTTPException(status_code=400, detail="Username can only contain letters, numbers, and underscores")
        
        if len(new_username) < 3:
            raise HTTPException(status_code=400, detail="Username must be at least 3 characters long")
        
        if new_password and len(new_password) < 6:
            raise HTTPException(status_code=400, detail="Password must be at least 6 characters long")
        
        # In a real implementation, you would:
        # 1. Verify current password
        # 2. Check username uniqueness
        # 3. Update Authelia user database
        # 4. Update user_devices table if username changed
        
        # For now, simulate success
        logger.info(f"User {user_id} updated profile: username={new_username}, password_changed={bool(new_password)}")
        
        username_changed = new_username != user_id
        
        if username_changed:
            # Update user_devices table with new username
            with sqlite3.connect(DB_PATH) as conn:
                cursor = conn.cursor()
                cursor.execute('UPDATE user_devices SET user_id = ? WHERE user_id = ?', (new_username, user_id))
                conn.commit()
                logger.info(f"Updated user_devices: {user_id} -> {new_username}")
        
        return {
            "message": "Profile updated successfully",
            "username": new_username,
            "usernameChanged": username_changed,
            "passwordChanged": bool(new_password)
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating user profile: {e}")
        raise HTTPException(status_code=500, detail=f"Error updating user profile: {str(e)}")

@app.put("/api/test/user/profile", tags=["user"])  
async def test_update_user_profile(request: Request, user: str = Query("thomas", description="Test user (thomas or willie)")):
    """Test endpoint for updating user profile - local development."""
    try:
        body = await request.json()
        
        new_username = body.get("username", "").strip()
        new_password = body.get("newPassword", "")
        
        # Basic validation
        if not new_username:
            raise HTTPException(status_code=400, detail="Username is required")
        
        # Simulate username uniqueness check
        if new_username in ["admin", "root", "test"] and new_username != user:
            raise HTTPException(status_code=409, detail="Username already taken")
        
        username_changed = new_username != user
        
        if username_changed:
            # Update user_devices table with new username
            with sqlite3.connect(DB_PATH) as conn:
                cursor = conn.cursor()
                cursor.execute('UPDATE user_devices SET user_id = ? WHERE user_id = ?', (new_username, user))
                conn.commit()
                logger.info(f"Test: Updated user_devices: {user} -> {new_username}")
        
        logger.info(f"Test: User {user} updated profile: username={new_username}, password_changed={bool(new_password)}")
        
        return {
            "message": "Profile updated successfully (test mode)",
            "username": new_username,
            "usernameChanged": username_changed,
            "passwordChanged": bool(new_password)
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in test update user profile: {e}")
        raise HTTPException(status_code=500, detail=f"Error updating user profile: {str(e)}")

@app.get("/api/diagnostic", tags=["public"])
async def get_diagnostic(date: Optional[str] = None):
    """
    Diagnostic endpoint to check available data.
    
    Optional query parameter:
    - date: Date in YYYY-MM-DD format
    """
    # Validate date format if provided
    if date and not re.match(r'^\d{4}-\d{2}-\d{2}$', date):
        raise HTTPException(status_code=400, detail="Invalid date format. Use YYYY-MM-DD")
    
    # Determine the start date
    if date:
        start_date = datetime.strptime(date, "%Y-%m-%d")
    else:
        start_date = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    
    # Fetch data for multiple days to ensure we have enough hours
    json_data = await fetch_data_for_date_range(start_date, num_days=2)
    
    # Group by hour
    hourly_data = group_entries_by_hour(json_data)
    
    # Current time for reference
    now = datetime.now(pytz.UTC).replace(minute=0, second=0, microsecond=0)
    
    # Return diagnostic information
    return {
        "total_entries": len(json_data),
        "unique_hours": len(hourly_data),
        "current_time": now.isoformat().replace('+00:00', 'Z'),
        "available_hours": list(hourly_data.keys()),
        "hours_data": get_current_and_future_hours(hourly_data, 12)
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)