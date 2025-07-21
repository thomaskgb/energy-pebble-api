from fastapi import FastAPI, HTTPException, Request, Query, Depends, Security, File, UploadFile, Form
from fastapi.responses import FileResponse
from pydantic import BaseModel
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
import httpx
from datetime import datetime, timedelta, timezone
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
import shutil

# Pydantic models for OTA requests
class OTAStatusReport(BaseModel):
    status: str  # 'downloading', 'installing', 'completed', 'failed'
    error_message: Optional[str] = None
    install_duration: Optional[int] = None  # seconds
    current_version: Optional[str] = None

class FirmwareUpload(BaseModel):
    version: str
    is_stable: bool = True
    force_update: bool = False
    min_version: Optional[str] = None
    rollback_version: Optional[str] = None
    release_notes: Optional[str] = None
    target_devices: Optional[str] = None

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
        {
            "name": "ota",
            "description": "Over-the-air update endpoints",
        },
        {
            "name": "firmware",
            "description": "Firmware management endpoints (admin)",
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
        
        # Check if we need to migrate the devices table to remove hardware_id
        cursor.execute("PRAGMA table_info(devices)")
        columns = [col[1] for col in cursor.fetchall()]
        
        if 'hardware_id' in columns:
            logger.info("Migrating devices table to remove hardware_id column")
            
            # Create new table without hardware_id
            cursor.execute('''
                CREATE TABLE devices_new (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    client_ip TEXT NOT NULL,
                    device_fingerprint TEXT UNIQUE NOT NULL,
                    first_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    last_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    user_agent TEXT,
                    request_count INTEGER DEFAULT 1,
                    device_id TEXT UNIQUE,
                    mac_address TEXT,
                    software_version TEXT,
                    UNIQUE(client_ip, device_fingerprint)
                )
            ''')
            
            # Copy data from old table to new table (excluding hardware_id)
            cursor.execute('''
                INSERT INTO devices_new (id, client_ip, device_fingerprint, first_seen, last_seen, 
                                       user_agent, request_count, device_id, mac_address, software_version)
                SELECT id, client_ip, device_fingerprint, first_seen, last_seen,
                       user_agent, request_count, device_id, mac_address, software_version
                FROM devices
            ''')
            
            # Drop old table and rename new table
            cursor.execute('DROP TABLE devices')
            cursor.execute('ALTER TABLE devices_new RENAME TO devices')
            
            logger.info("Successfully migrated devices table")
        else:
            # Create devices table for tracking energy dots (new installations)
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
        
        # Create predefined_devices table for bulk device uploads
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS predefined_devices (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                device_id TEXT UNIQUE NOT NULL,
                mac_address TEXT,
                software_version TEXT DEFAULT 'v1',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Create firmware_versions table for OTA management
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS firmware_versions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                version TEXT UNIQUE NOT NULL,
                filename TEXT NOT NULL,
                checksum TEXT NOT NULL,
                file_size INTEGER NOT NULL,
                release_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                is_stable BOOLEAN DEFAULT TRUE,
                force_update BOOLEAN DEFAULT FALSE,
                min_version TEXT,
                rollback_version TEXT,
                release_notes TEXT,
                target_devices TEXT,
                created_by TEXT
            )
        ''')
        
        # Create OTA logs table for tracking update attempts
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS ota_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                device_id TEXT NOT NULL,
                check_timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                current_version TEXT,
                offered_version TEXT,
                status TEXT CHECK(status IN ('check', 'downloading', 'installing', 'completed', 'failed', 'skipped')) DEFAULT 'check',
                error_message TEXT,
                install_duration INTEGER,
                ip_address TEXT,
                user_agent TEXT
            )
        ''')
        
        # Add new columns to existing devices table if they don't exist
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
            
        try:
            cursor.execute('ALTER TABLE devices ADD COLUMN current_firmware_version TEXT DEFAULT "v1.0.0"')
            logger.info("Added current_firmware_version column to devices table")
        except sqlite3.OperationalError:
            pass  # Column already exists
            
        try:
            cursor.execute('ALTER TABLE devices ADD COLUMN last_ota_check TIMESTAMP')
            logger.info("Added last_ota_check column to devices table")
        except sqlite3.OperationalError:
            pass  # Column already exists
            
        try:
            cursor.execute('ALTER TABLE devices ADD COLUMN ota_status TEXT DEFAULT "idle"')
            logger.info("Added ota_status column to devices table")
        except sqlite3.OperationalError:
            pass  # Column already exists
        
        # Create index for performance
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_devices_ip ON devices (client_ip)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_devices_fingerprint ON devices (device_fingerprint)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_user_devices_user ON user_devices (user_id)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_ota_logs_device ON ota_logs (device_id)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_ota_logs_timestamp ON ota_logs (check_timestamp)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_firmware_version ON firmware_versions (version)')
        
        # Insert initial predefined devices if the table is empty
        cursor.execute('SELECT COUNT(*) FROM predefined_devices')
        count = cursor.fetchone()[0]
        
        if count == 0:
            logger.info("Initializing predefined devices table")
            initial_devices = [
                ("904fb0453ab4", "B4:3A:45:B0:50:A8", "v1"),
                ("test-device-1", "B4:3A:45:B0:4F:90", "v1"), 
                ("test-device-2", "B4:3A:45:B0:5A:6C", "v1"),
                ("test-device-3", "B8:F8:62:D8:68:68", "v1"),
                ("test-device-4", "B4:3A:45:B0:58:E8", "v1"),
                ("test-device-5", "B4:3A:45:B0:5E:BC", "v1"),
                ("test-device-6", "24:EC:4A:2F:2E:9C", "v1"),
                ("test-device-7", "24:EC:4A:2F:2D:04", "v1"),
                ("test-device-8", "24:EC:4A:2F:C5:D4", "v1"),
            ]
            
            for device_id, mac_address, software_version in initial_devices:
                cursor.execute('''
                    INSERT INTO predefined_devices (device_id, mac_address, software_version)
                    VALUES (?, ?, ?)
                ''', (device_id, mac_address, software_version))
            
            logger.info(f"Added {len(initial_devices)} predefined devices")
        else:
            logger.info(f"Predefined devices table already contains {count} devices")
        
        # Insert initial firmware versions if the table is empty
        cursor.execute('SELECT COUNT(*) FROM firmware_versions')
        firmware_count = cursor.fetchone()[0]
        
        if firmware_count == 0:
            logger.info("Initializing firmware versions table")
            initial_firmwares = [
                ("v1.0.0", "esp32_v1.0.0.bin", "sha256:0000000000000000000000000000000000000000000000000000000000000000", 1048576, True, False, None, None, "Initial release firmware", None, "system"),
                ("v1.1.0", "esp32_v1.1.0.bin", "sha256:1111111111111111111111111111111111111111111111111111111111111111", 1072640, True, False, "v1.0.0", "v1.0.0", "Bug fixes and improvements", None, "system"),
                ("v1.2.0", "esp32_v1.2.0.bin", "sha256:2222222222222222222222222222222222222222222222222222222222222222", 1098752, True, False, "v1.0.0", "v1.1.0", "New features and optimizations", None, "system"),
            ]
            
            for version, filename, checksum, file_size, is_stable, force_update, min_version, rollback_version, release_notes, target_devices, created_by in initial_firmwares:
                cursor.execute('''
                    INSERT INTO firmware_versions (version, filename, checksum, file_size, is_stable, force_update, min_version, rollback_version, release_notes, target_devices, created_by)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (version, filename, checksum, file_size, is_stable, force_update, min_version, rollback_version, release_notes, target_devices, created_by))
            
            logger.info(f"Added {len(initial_firmwares)} initial firmware versions")
        else:
            logger.info(f"Firmware versions table already contains {firmware_count} versions")
        
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

def generate_mac_from_device_id(device_id: str) -> str:
    """Convert ESP32 device ID to actual hardware MAC address.
    
    ESP32 device IDs are eFuse MAC addresses with bytes reversed.
    Algorithm:
    1. Split device_id into byte pairs: 904fb0453ab4 -> [90, 4f, b0, 45, 3a, b4]
    2. Reverse byte order: [b4, 3a, 45, b0, 4f, 90]
    3. Format with colons: B4:3A:45:B0:4F:90
    """
    if not device_id or len(device_id) != 12:
        return "00:00:00:00:00:00"
    
    try:
        # Split into byte pairs and reverse order
        byte_pairs = [device_id[i:i+2] for i in range(0, 12, 2)]
        reversed_pairs = byte_pairs[::-1]
        
        # Format as MAC address with uppercase
        mac_address = ':'.join(reversed_pairs).upper()
        return mac_address
    except:
        # Fallback to default if conversion fails
        return "00:00:00:00:00:00"

def get_device_mac_address(cursor, conn, device_db_id: int, device_id: str, stored_mac: str) -> str:
    """Get MAC address for a device: stored, predefined, or generated."""
    if stored_mac:
        return stored_mac
    
    # Check predefined_devices table for MAC address
    cursor.execute('SELECT mac_address FROM predefined_devices WHERE device_id = ?', (device_id,))
    predefined_result = cursor.fetchone()
    if predefined_result and predefined_result[0]:
        mac_address = predefined_result[0]
        # Update devices table with predefined MAC for future use
        cursor.execute('UPDATE devices SET mac_address = ? WHERE id = ?', (mac_address, device_db_id))
        conn.commit()
        return mac_address
    
    # Generate MAC from device_id as fallback
    return generate_mac_from_device_id(device_id)

def compare_versions(version1: str, version2: str) -> int:
    """Compare two version strings. Returns: -1 if v1 < v2, 0 if equal, 1 if v1 > v2"""
    try:
        # Remove 'v' prefix if present and split by dots
        v1_parts = [int(x) for x in version1.lstrip('v').split('.')]
        v2_parts = [int(x) for x in version2.lstrip('v').split('.')]
        
        # Pad with zeros to make equal length
        max_len = max(len(v1_parts), len(v2_parts))
        v1_parts.extend([0] * (max_len - len(v1_parts)))
        v2_parts.extend([0] * (max_len - len(v2_parts)))
        
        for i in range(max_len):
            if v1_parts[i] < v2_parts[i]:
                return -1
            elif v1_parts[i] > v2_parts[i]:
                return 1
        return 0
    except:
        # Fallback to string comparison if parsing fails
        return -1 if version1 < version2 else (1 if version1 > version2 else 0)

def version_is_newer(new_version: str, current_version: str) -> bool:
    """Check if new_version is newer than current_version"""
    return compare_versions(new_version, current_version) > 0

def get_latest_firmware_for_device(device_id: str, current_version: str) -> dict:
    """Get the latest available firmware for a device"""
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        
        # Get latest stable firmware that's newer than current version
        cursor.execute('''
            SELECT version, filename, checksum, file_size, force_update, rollback_version, release_notes, min_version
            FROM firmware_versions 
            WHERE is_stable = TRUE 
            AND (target_devices IS NULL OR target_devices LIKE ? OR target_devices = '[]')
            ORDER BY release_date DESC
            LIMIT 1
        ''', (f'%{device_id}%',))
        
        result = cursor.fetchone()
        if not result:
            return None
            
        version, filename, checksum, file_size, force_update, rollback_version, release_notes, min_version = result
        
        # Check if this version is newer than current
        if not version_is_newer(version, current_version):
            return None
            
        # Check minimum version requirement
        if min_version and compare_versions(current_version, min_version) < 0:
            return None
            
        return {
            'version': version,
            'filename': filename,
            'checksum': checksum,
            'file_size': file_size,
            'force_update': bool(force_update),
            'rollback_version': rollback_version,
            'release_notes': release_notes
        }

def log_ota_check(device_id: str, current_version: str, offered_version: str = None, ip_address: str = None, user_agent: str = None):
    """Log an OTA check attempt"""
    try:
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()
            
            # Insert OTA log entry
            cursor.execute('''
                INSERT INTO ota_logs (device_id, current_version, offered_version, status, ip_address, user_agent)
                VALUES (?, ?, ?, 'check', ?, ?)
            ''', (device_id, current_version, offered_version, ip_address, user_agent))
            
            # Update device's last OTA check timestamp
            cursor.execute('''
                UPDATE devices 
                SET last_ota_check = CURRENT_TIMESTAMP 
                WHERE device_id = ?
            ''', (device_id,))
            
            conn.commit()
    except Exception as e:
        logger.error(f"Failed to log OTA check: {e}")

def calculate_file_checksum(file_path: Path) -> str:
    """Calculate SHA256 checksum of a file"""
    sha256_hash = hashlib.sha256()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(4096), b""):
            sha256_hash.update(chunk)
    return f"sha256:{sha256_hash.hexdigest()}"

def get_firmware_storage_path() -> Path:
    """Get the firmware storage directory path"""
    return Path("/home/cumulus/github/energy_pebble/firmware")

def is_admin_user(user_id: str, request: Request = None) -> bool:
    """Check if user has admin privileges"""
    # If we have a request, check Remote-Groups header from Authelia
    if request:
        remote_groups = request.headers.get("Remote-Groups", "")
        groups = [group.strip() for group in remote_groups.split(",") if group.strip()]
        if "admins" in groups:
            return True
    
    # Fallback: extract username from email if present (e.g., thomas@tdlx.nl -> thomas)
    username = user_id.split('@')[0] if '@' in user_id else user_id
    
    # Simple admin check - in production you'd check against proper user roles  
    return username in ["thomas", "admin", "willie", "seba"]

def log_device_request(client_ip: str, user_agent: str, device_id: Optional[str] = None):
    """Log a device request for tracking purposes. Only tracks devices with device_id."""
    try:
        # Only log devices that provide a device_id
        if not device_id:
            return
            
        with db_lock:
            with sqlite3.connect(DB_PATH) as conn:
                cursor = conn.cursor()
                
                now = datetime.now(pytz.UTC)
                
                # Update existing device or create new one
                cursor.execute('''
                    UPDATE devices 
                    SET last_seen = ?, request_count = request_count + 1, client_ip = ?
                    WHERE device_id = ?
                ''', (now, client_ip, device_id))
                
                # If no rows updated, insert new device with device_id
                if cursor.rowcount == 0:
                    fingerprint = create_device_fingerprint(client_ip, user_agent or "unknown", now)
                    
                    # Get MAC address from predefined devices or generate one
                    mac_address = None
                    cursor.execute('SELECT mac_address FROM predefined_devices WHERE device_id = ?', (device_id,))
                    predefined_result = cursor.fetchone()
                    if predefined_result and predefined_result[0]:
                        mac_address = predefined_result[0]
                    else:
                        mac_address = generate_mac_from_device_id(device_id)
                    
                    cursor.execute('''
                        INSERT OR IGNORE INTO devices 
                        (client_ip, device_fingerprint, first_seen, last_seen, user_agent, device_id, mac_address)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                    ''', (client_ip, fingerprint, now, now, user_agent, device_id, mac_address))
                    
                    logger.info(f"New device registered: {device_id} with MAC {mac_address}")
                
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
    
    # Return the first 9 hours for display (current + next 8)
    display_colors = color_codes[:9]
    
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

@app.get("/api/verify", tags=["auth"])
async def verify_user(request: Request):
    """
    Verify user authentication and return user information from Authelia headers.
    This endpoint is used by the dashboard to check authentication status.
    """
    # Get user information from Authelia headers
    remote_user = request.headers.get("Remote-User")
    remote_name = request.headers.get("Remote-Name") 
    remote_email = request.headers.get("Remote-Email")
    remote_groups = request.headers.get("Remote-Groups")
    
    if not remote_user:
        raise HTTPException(status_code=401, detail="User not authenticated")
    
    # Parse groups if available
    groups = []
    if remote_groups:
        groups = [group.strip() for group in remote_groups.split(",")]
    
    return {
        "authenticated": True,
        "user": remote_user,
        "display_name": remote_name or remote_user.split("@")[0],
        "email": remote_email,
        "groups": groups,
        "is_admin": "admins" in groups
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
                       d.mac_address, d.software_version,
                       ud.nickname, ud.created_at
                FROM devices d
                JOIN user_devices ud ON d.id = ud.device_id
                WHERE ud.user_id = ?
                ORDER BY d.last_seen DESC
            ''', (user_id,))
            
            devices = []
            for row in cursor.fetchall():
                status, minutes_ago = calculate_device_status(row[3])
                
                # Get MAC address using helper function
                stored_mac = row[8]  # mac_address from database
                device_id = row[6]
                device_db_id = row[0]
                mac_address = get_device_mac_address(cursor, conn, device_db_id, device_id, stored_mac)
                
                device = {
                    "id": row[0],
                    "fingerprint": row[1],
                    "first_seen": row[2],
                    "last_seen": row[3],
                    "user_agent": row[4],
                    "request_count": row[5],
                    "device_id": device_id,
                    "client_ip": row[7],
                    "mac_address": mac_address,
                    "software_version": row[9],
                    "nickname": row[10],
                    "claimed_at": row[11],
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
        if not user_id:
            raise HTTPException(status_code=401, detail="Authentication required")
        
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()
            
            cursor.execute('''
                SELECT d.id, d.device_fingerprint, d.first_seen, d.last_seen, 
                       d.user_agent, d.request_count, d.device_id, d.client_ip,
                       d.mac_address, d.software_version,
                       ud.nickname, ud.created_at
                FROM devices d
                JOIN user_devices ud ON d.id = ud.device_id
                WHERE ud.user_id = ?
                ORDER BY d.last_seen DESC
            ''', (user_id,))
            
            devices = []
            for row in cursor.fetchall():
                status, minutes_ago = calculate_device_status(row[3])
                
                # Get MAC address using helper function
                stored_mac = row[8]  # mac_address from database
                device_id = row[6]
                device_db_id = row[0]
                mac_address = get_device_mac_address(cursor, conn, device_db_id, device_id, stored_mac)
                
                device = {
                    "id": row[0],
                    "fingerprint": row[1],
                    "first_seen": row[2],
                    "last_seen": row[3],
                    "user_agent": row[4],
                    "request_count": row[5],
                    "device_id": device_id,
                    "client_ip": row[7],
                    "mac_address": mac_address,
                    "software_version": row[9],
                    "nickname": row[10],
                    "claimed_at": row[11],
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
        if not user_id:
            raise HTTPException(status_code=401, detail="Authentication required")
        
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
        if not user_id:
            raise HTTPException(status_code=401, detail="Authentication required")
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

# Firmware Management Endpoints

@app.post("/api/firmware/upload", tags=["firmware"])
async def upload_firmware(
    request: Request,
    firmware_file: UploadFile = File(...),
    version: str = Form(...),
    product_name: str = Form("energy_pebble"),
    variant: str = Form("release"),
    is_stable: bool = Form(True),
    force_update: bool = Form(False),
    min_version: str = Form(None),
    rollback_version: str = Form(None),
    release_notes: str = Form(None),
    target_devices: str = Form(None)
):
    """
    Upload a new firmware binary file.
    Requires admin authentication. Designed for use by GitHub Actions.
    """
    try:
        # Check authentication and admin privileges
        user_id = get_current_user(request)
        if not is_admin_user(user_id, request):
            raise HTTPException(status_code=403, detail="Admin privileges required")
        
        # Validate firmware file
        if not firmware_file.filename.endswith('.bin'):
            raise HTTPException(status_code=400, detail="Firmware file must be a .bin file")
        
        # Validate version format
        if not re.match(r'^v?\d+\.\d+\.\d+$', version):
            raise HTTPException(status_code=400, detail="Version must be in format v1.2.3 or 1.2.3")
        
        # Normalize version (ensure it starts with 'v')
        if not version.startswith('v'):
            version = f'v{version}'
        
        # Check if version already exists
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT id FROM firmware_versions WHERE version = ?', (version,))
            if cursor.fetchone():
                raise HTTPException(status_code=409, detail=f"Firmware version {version} already exists")
        
        # Validate and sanitize product name and variant
        product_name = re.sub(r'[^a-zA-Z0-9_-]', '', product_name.lower())
        variant = re.sub(r'[^a-zA-Z0-9_-]', '', variant.lower())
        
        if not product_name:
            product_name = "energy_pebble"
        if not variant:
            variant = "release"
        
        # Generate filename: product_version_variant.bin
        if variant == "release":
            filename = f"{product_name}_{version}.bin"
        else:
            filename = f"{product_name}_{version}_{variant}.bin"
        
        # Save file to firmware directory
        firmware_storage = get_firmware_storage_path()
        firmware_storage.mkdir(exist_ok=True)
        
        firmware_path = firmware_storage / filename
        
        # Write file
        with open(firmware_path, "wb") as buffer:
            shutil.copyfileobj(firmware_file.file, buffer)
        
        # Calculate checksum and file size
        checksum = calculate_file_checksum(firmware_path)
        file_size = firmware_path.stat().st_size
        
        # Insert into database
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO firmware_versions 
                (version, filename, checksum, file_size, is_stable, force_update, 
                 min_version, rollback_version, release_notes, target_devices, created_by)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (version, filename, checksum, file_size, is_stable, force_update,
                  min_version, rollback_version, release_notes, target_devices, user_id))
            
            firmware_id = cursor.lastrowid
            conn.commit()
        
        logger.info(f"Firmware {version} uploaded successfully by {user_id}")
        
        return {
            "id": firmware_id,
            "version": version,
            "filename": filename,
            "checksum": checksum,
            "file_size": file_size,
            "message": f"Firmware {version} uploaded successfully"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error uploading firmware: {e}")
        # Clean up file if it was created
        try:
            if 'firmware_path' in locals() and firmware_path.exists():
                firmware_path.unlink()
        except:
            pass
        raise HTTPException(status_code=500, detail=f"Error uploading firmware: {str(e)}")

@app.get("/api/firmware/versions", tags=["firmware"])
async def list_firmware_versions(request: Request):
    """
    List all firmware versions.
    Requires admin authentication.
    """
    try:
        user_id = get_current_user(request)
        if not is_admin_user(user_id, request):
            raise HTTPException(status_code=403, detail="Admin privileges required")
        
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT id, version, filename, checksum, file_size, release_date, 
                       is_stable, force_update, min_version, rollback_version, 
                       release_notes, target_devices, created_by
                FROM firmware_versions 
                ORDER BY release_date DESC
            ''')
            
            versions = []
            for row in cursor.fetchall():
                filename = row[2]
                version_info = {
                    "id": row[0],
                    "version": row[1],
                    "filename": filename,
                    "checksum": row[3],
                    "file_size": row[4],
                    "release_date": row[5],
                    "is_stable": bool(row[6]),
                    "force_update": bool(row[7]),
                    "min_version": row[8],
                    "rollback_version": row[9],
                    "release_notes": row[10],
                    "target_devices": row[11],
                    "created_by": row[12],
                    # Add public URLs
                    "download_url": f"https://energypebble.tdlx.nl/firmware/{filename}",
                    "checksum_url": f"https://energypebble.tdlx.nl/api/firmware/{filename}/checksum"
                }
                versions.append(version_info)
            
            return {
                "versions": versions,
                "total": len(versions)
            }
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error listing firmware versions: {e}")
        raise HTTPException(status_code=500, detail=f"Error listing firmware versions: {str(e)}")

@app.delete("/api/firmware/versions/{version}", tags=["firmware"])
async def delete_firmware_version(version: str, request: Request):
    """
    Delete a firmware version and its associated file.
    Requires admin authentication.
    """
    try:
        user_id = get_current_user(request)
        if not is_admin_user(user_id, request):
            raise HTTPException(status_code=403, detail="Admin privileges required")
        
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()
            
            # Get firmware info before deleting
            cursor.execute('SELECT filename FROM firmware_versions WHERE version = ?', (version,))
            result = cursor.fetchone()
            
            if not result:
                raise HTTPException(status_code=404, detail=f"Firmware version {version} not found")
            
            filename = result[0]
            
            # Delete from database
            cursor.execute('DELETE FROM firmware_versions WHERE version = ?', (version,))
            
            if cursor.rowcount == 0:
                raise HTTPException(status_code=404, detail=f"Firmware version {version} not found")
            
            conn.commit()
        
        # Delete physical file
        firmware_path = get_firmware_storage_path() / filename
        if firmware_path.exists():
            firmware_path.unlink()
            logger.info(f"Deleted firmware file: {firmware_path}")
        
        logger.info(f"Firmware {version} deleted by {user_id}")
        
        return {
            "message": f"Firmware version {version} deleted successfully",
            "version": version,
            "filename": filename
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting firmware version {version}: {e}")
        raise HTTPException(status_code=500, detail=f"Error deleting firmware: {str(e)}")

@app.get("/api/firmware/ota-stats", tags=["firmware"])
async def get_ota_statistics(request: Request):
    """
    Get OTA update statistics.
    Requires admin authentication.
    """
    try:
        user_id = get_current_user(request)
        if not is_admin_user(user_id, request):
            raise HTTPException(status_code=403, detail="Admin privileges required")
        
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()
            
            # Get total OTA checks
            cursor.execute('SELECT COUNT(*) FROM ota_logs WHERE status = "check"')
            total_checks = cursor.fetchone()[0]
            
            # Get successful updates
            cursor.execute('SELECT COUNT(*) FROM ota_logs WHERE status = "completed"')
            successful_updates = cursor.fetchone()[0]
            
            # Get failed updates
            cursor.execute('SELECT COUNT(*) FROM ota_logs WHERE status = "failed"')
            failed_updates = cursor.fetchone()[0]
            
            # Get recent activity (last 7 days)
            cursor.execute('''
                SELECT DATE(check_timestamp) as date, COUNT(*) as count
                FROM ota_logs 
                WHERE check_timestamp >= datetime('now', '-7 days')
                GROUP BY DATE(check_timestamp)
                ORDER BY date DESC
            ''')
            recent_activity = [{"date": row[0], "count": row[1]} for row in cursor.fetchall()]
            
            # Get firmware version distribution
            cursor.execute('''
                SELECT current_firmware_version, COUNT(*) as count
                FROM devices 
                WHERE current_firmware_version IS NOT NULL
                GROUP BY current_firmware_version
                ORDER BY count DESC
            ''')
            version_distribution = [{"version": row[0], "device_count": row[1]} for row in cursor.fetchall()]
            
            return {
                "total_checks": total_checks,
                "successful_updates": successful_updates,
                "failed_updates": failed_updates,
                "success_rate": (successful_updates / max(total_checks, 1)) * 100,
                "recent_activity": recent_activity,
                "version_distribution": version_distribution
            }
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting OTA statistics: {e}")
        raise HTTPException(status_code=500, detail=f"Error getting OTA statistics: {str(e)}")

# OTA (Over-The-Air) Update Endpoints

@app.get("/api/ota/check/{device_id}", tags=["ota"])
async def check_ota_updates(device_id: str, current_version: str = Query(..., description="Current firmware version (e.g., v1.0.0)"), request: Request = None):
    """
    Check for available OTA updates for a device.
    Called by devices every 12 hours to check for firmware updates.
    """
    try:
        # Extract client info for logging
        client_ip = get_real_client_ip(request) if request else None
        user_agent = request.headers.get("user-agent") if request else None
        
        # Get latest firmware for this device
        latest_firmware = get_latest_firmware_for_device(device_id, current_version)
        
        if latest_firmware:
            # Log the OTA check with offered version
            log_ota_check(device_id, current_version, latest_firmware['version'], client_ip, user_agent)
            
            return {
                "update_available": True,
                "version": latest_firmware['version'],
                "download_url": f"https://energypebble.tdlx.nl/firmware/{latest_firmware['filename']}",
                "checksum": latest_firmware['checksum'],
                "size_bytes": latest_firmware['file_size'],
                "force_update": latest_firmware['force_update'],
                "rollback_version": latest_firmware['rollback_version'],
                "release_notes": latest_firmware['release_notes'],
                "estimated_install_time": "2-3 minutes"
            }
        else:
            # Log the OTA check with no update available
            log_ota_check(device_id, current_version, None, client_ip, user_agent)
            
            return {
                "update_available": False,
                "current_version": current_version,
                "message": "You're running the latest firmware"
            }
            
    except Exception as e:
        logger.error(f"Error checking OTA updates for device {device_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Error checking for updates: {str(e)}")

@app.post("/api/ota/status/{device_id}", tags=["ota"])
async def report_ota_status(device_id: str, status_report: OTAStatusReport, request: Request = None):
    """
    Device reports OTA installation status.
    Called by devices during/after firmware update process.
    """
    try:
        client_ip = get_real_client_ip(request) if request else None
        user_agent = request.headers.get("user-agent") if request else None
        
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()
            
            # Insert status report into ota_logs
            cursor.execute('''
                INSERT INTO ota_logs (device_id, current_version, status, error_message, install_duration, ip_address, user_agent)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (device_id, status_report.current_version, status_report.status, 
                  status_report.error_message, status_report.install_duration, client_ip, user_agent))
            
            # Update device status and firmware version if completed successfully
            if status_report.status == "completed" and status_report.current_version:
                cursor.execute('''
                    UPDATE devices 
                    SET current_firmware_version = ?, ota_status = 'idle'
                    WHERE device_id = ?
                ''', (status_report.current_version, device_id))
            elif status_report.status in ["downloading", "installing"]:
                cursor.execute('''
                    UPDATE devices 
                    SET ota_status = ?
                    WHERE device_id = ?
                ''', (status_report.status, device_id))
            elif status_report.status == "failed":
                cursor.execute('''
                    UPDATE devices 
                    SET ota_status = 'failed'
                    WHERE device_id = ?
                ''', (device_id,))
            
            conn.commit()
            
        logger.info(f"OTA status update from {device_id}: {status_report.status}")
        
        return {
            "status": "received",
            "message": f"Status '{status_report.status}' recorded for device {device_id}"
        }
        
    except Exception as e:
        logger.error(f"Error recording OTA status for device {device_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Error recording status: {str(e)}")

@app.get("/api/firmware/{filename}/checksum", tags=["ota"])
async def get_firmware_checksum(filename: str):
    """
    Get the SHA256 checksum for a firmware file.
    Public endpoint for firmware verification.
    """
    try:
        # Validate filename
        if not re.match(r'^[a-zA-Z0-9_\-\.]+\.bin$', filename):
            raise HTTPException(status_code=400, detail="Invalid firmware filename")
        
        # Get checksum from database
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT checksum FROM firmware_versions WHERE filename = ?', (filename,))
            result = cursor.fetchone()
            
            if not result:
                raise HTTPException(status_code=404, detail="Firmware not found")
            
            checksum = result[0]
            # Extract just the hash part (remove 'sha256:' prefix)
            if checksum.startswith('sha256:'):
                hash_value = checksum[7:]
            else:
                hash_value = checksum
            
            return {
                "filename": filename,
                "algorithm": "sha256",
                "checksum": hash_value,
                "full_checksum": checksum
            }
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting checksum for {filename}: {e}")
        raise HTTPException(status_code=500, detail=f"Error getting checksum: {str(e)}")

@app.get("/firmware/{filename}", tags=["ota"])
async def download_firmware(filename: str, request: Request = None):
    """
    Secure firmware download endpoint.
    Serves firmware binary files for OTA updates.
    """
    try:
        # Validate filename to prevent directory traversal
        if not re.match(r'^[a-zA-Z0-9_\-\.]+\.bin$', filename):
            raise HTTPException(status_code=400, detail="Invalid firmware filename")
        
        # Check if firmware exists in database
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT version, checksum, file_size FROM firmware_versions WHERE filename = ?', (filename,))
            firmware_info = cursor.fetchone()
            
            if not firmware_info:
                raise HTTPException(status_code=404, detail="Firmware not found")
        
        # Check if file exists on disk
        firmware_path = get_firmware_storage_path() / filename
        
        if not firmware_path.exists():
            logger.error(f"Firmware file not found on disk: {firmware_path}")
            raise HTTPException(status_code=404, detail="Firmware file not found on disk")
        
        # Verify file size matches database
        actual_size = firmware_path.stat().st_size
        expected_size = firmware_info[2]
        
        if actual_size != expected_size:
            logger.error(f"Firmware file size mismatch: expected {expected_size}, got {actual_size}")
            raise HTTPException(status_code=500, detail="Firmware file corrupted")
        
        # Log download attempt
        client_ip = get_real_client_ip(request) if request else "unknown"
        logger.info(f"Firmware download: {filename} by {client_ip}")
        
        # Return the binary file
        return FileResponse(
            firmware_path, 
            media_type='application/octet-stream', 
            filename=filename,
            headers={
                "X-Firmware-Version": firmware_info[0],
                "X-Firmware-Checksum": firmware_info[1],
                "Content-Length": str(firmware_info[2])
            }
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error downloading firmware {filename}: {e}")
        raise HTTPException(status_code=500, detail=f"Error downloading firmware: {str(e)}")

@app.get("/api/firmware/latest-stable", tags=["firmware"])
async def get_latest_stable_firmware():
    """
    Get the latest stable firmware version and its details.
    Public endpoint for displaying current stable firmware information.
    """
    try:
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()
            
            # Get the latest stable firmware version
            cursor.execute('''
                SELECT 
                    version,
                    filename,
                    checksum,
                    file_size,
                    release_date,
                    release_notes
                FROM firmware_versions 
                WHERE is_stable = 1 
                ORDER BY release_date DESC, version DESC 
                LIMIT 1
            ''')
            
            result = cursor.fetchone()
            
            if not result:
                return {
                    "version": None,
                    "message": "No stable firmware version available"
                }
            
            version, filename, checksum, file_size, release_date, release_notes = result
            
            # Extract hash from checksum
            hash_value = checksum[7:] if checksum.startswith('sha256:') else checksum
            
            # Calculate release date relative time
            release_date_obj = datetime.fromisoformat(release_date.replace('Z', '+00:00')) if release_date else None
            release_date_relative = None
            if release_date_obj:
                time_diff = datetime.now(timezone.utc) - release_date_obj.replace(tzinfo=timezone.utc)
                if time_diff.total_seconds() < 86400:  # Less than 1 day
                    release_date_relative = f"{int(time_diff.total_seconds() / 3600)} hours ago"
                elif time_diff.total_seconds() < 2592000:  # Less than 30 days
                    release_date_relative = f"{int(time_diff.total_seconds() / 86400)} days ago"
                else:
                    release_date_relative = release_date_obj.strftime("%B %Y")
            
            return {
                "version": version,
                "filename": filename,
                "file_size": file_size,
                "file_size_mb": round(file_size / (1024 * 1024), 2) if file_size else 0,
                "release_date": release_date,
                "release_date_relative": release_date_relative,
                "description": release_notes or f"Stable release {version}",
                "release_notes": release_notes,
                "is_stable": True,
                "download_url": f"https://energypebble.tdlx.nl/firmware/{filename}",
                "checksum_url": f"https://energypebble.tdlx.nl/api/firmware/{filename}/checksum",
                "checksum": hash_value,
                "algorithm": "sha256"
            }
            
    except Exception as e:
        logger.error(f"Error getting latest stable firmware: {e}")
        raise HTTPException(status_code=500, detail=f"Error getting latest stable firmware: {str(e)}")

# Admin Device Management Endpoints

@app.get("/api/admin/devices", tags=["admin"])
async def get_all_devices(
    request: Request,
    skip: int = Query(0, ge=0, description="Number of devices to skip"),
    limit: int = Query(100, ge=1, le=1000, description="Number of devices to return"),
    search: str = Query(None, description="Search devices by device_id, MAC, or IP"),
    firmware_version: str = Query(None, description="Filter by firmware version"),
    status: str = Query(None, description="Filter by online status (online/offline)")
):
    """
    Get all devices with detailed information for admin management.
    Requires admin privileges.
    """
    try:
        # Check authentication and admin privileges
        user_id = get_current_user(request)
        if not is_admin_user(user_id, request):
            raise HTTPException(status_code=403, detail="Admin access required")
        
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()
            
            # Build query with filters
            base_query = '''
                SELECT 
                    d.id,
                    d.device_id,
                    d.client_ip,
                    d.mac_address,
                    d.current_firmware_version,
                    d.software_version,
                    d.first_seen,
                    d.last_seen,
                    d.last_ota_check,
                    d.ota_status,
                    d.request_count,
                    d.user_agent,
                    ud.user_id as claimed_by,
                    ud.nickname as device_nickname,
                    ud.created_at as claimed_at
                FROM devices d
                LEFT JOIN user_devices ud ON d.id = ud.device_id
            '''
            
            conditions = []
            params = []
            
            if search:
                conditions.append("(d.device_id LIKE ? OR d.mac_address LIKE ? OR d.client_ip LIKE ?)")
                search_param = f"%{search}%"
                params.extend([search_param, search_param, search_param])
            
            if firmware_version:
                conditions.append("d.current_firmware_version = ?")
                params.append(firmware_version)
            
            # Note: Status filtering is done post-query since we need to calculate status using our function
            
            if conditions:
                base_query += " WHERE " + " AND ".join(conditions)
            
            # Add ordering and pagination
            base_query += " ORDER BY d.last_seen DESC LIMIT ? OFFSET ?"
            params.extend([limit, skip])
            
            cursor.execute(base_query, params)
            devices = cursor.fetchall()
            
            # Get total count for pagination
            count_query = '''
                SELECT COUNT(DISTINCT d.id)
                FROM devices d
                LEFT JOIN user_devices ud ON d.id = ud.device_id
            '''
            if conditions:
                count_query += " WHERE " + " AND ".join(conditions[:-2] if status else conditions)  # Remove LIMIT params
            
            cursor.execute(count_query, params[:-2])  # Remove LIMIT and OFFSET params
            total_count = cursor.fetchone()[0]
            
            # Format response and apply status filtering
            device_list = []
            for device in devices:
                # Use the same status calculation as personal dashboard
                device_status, minutes_ago = calculate_device_status(device[7])  # device[7] is last_seen
                
                # Apply status filter if specified
                if status and device_status != status:
                    continue
                
                is_online = device_status == "online"
                
                # Calculate last seen relative time
                last_seen_relative = None
                if device[7]:  # if last_seen exists
                    if minutes_ago < 60:
                        last_seen_relative = f"{minutes_ago} minutes ago"
                    elif minutes_ago < 1440:  # Less than 24 hours
                        last_seen_relative = f"{int(minutes_ago / 60)} hours ago"
                    else:
                        last_seen_relative = f"{int(minutes_ago / 1440)} days ago"
                
                device_list.append({
                    "id": device[0],
                    "device_id": device[1],
                    "client_ip": device[2],
                    "mac_address": device[3],
                    "current_firmware_version": device[4] or "Unknown",
                    "software_version": device[5],
                    "first_seen": device[6],
                    "last_seen": device[7],
                    "last_seen_relative": last_seen_relative,
                    "last_ota_check": device[8],
                    "ota_status": device[9] or "idle",
                    "request_count": device[10] or 0,
                    "user_agent": device[11],
                    "claimed_by": device[12],
                    "device_nickname": device[13],
                    "claimed_at": device[14],
                    "is_online": is_online,
                    "status": device_status,
                    "minutes_since_last_seen": minutes_ago
                })
            
            # Adjust total count if status filtering was applied
            actual_total = len(device_list) if status else total_count
            
            return {
                "devices": device_list,
                "total": actual_total,
                "skip": skip,
                "limit": limit,
                "has_more": skip + len(device_list) < actual_total
            }
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting admin devices: {e}")
        raise HTTPException(status_code=500, detail=f"Error getting devices: {str(e)}")

@app.get("/api/admin/devices/stats", tags=["admin"])
async def get_device_stats(request: Request):
    """
    Get device statistics for admin dashboard.
    """
    try:
        # Check authentication and admin privileges
        user_id = get_current_user(request)
        if not is_admin_user(user_id, request):
            raise HTTPException(status_code=403, detail="Admin access required")
        
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()
            
            # Total devices
            cursor.execute('SELECT COUNT(*) FROM devices')
            total_devices = cursor.fetchone()[0]
            
            # Online devices (using correct 20-minute window)
            cursor.execute("SELECT last_seen FROM devices WHERE last_seen IS NOT NULL")
            all_devices_last_seen = cursor.fetchall()
            online_devices = 0
            for (last_seen,) in all_devices_last_seen:
                status, _ = calculate_device_status(last_seen)
                if status == "online":
                    online_devices += 1
            
            # Claimed devices
            cursor.execute('SELECT COUNT(DISTINCT device_id) FROM user_devices')
            claimed_devices = cursor.fetchone()[0]
            
            # Firmware version distribution
            cursor.execute('''
                SELECT current_firmware_version, COUNT(*) as count
                FROM devices 
                WHERE current_firmware_version IS NOT NULL
                GROUP BY current_firmware_version
                ORDER BY count DESC
            ''')
            firmware_distribution = [
                {"version": row[0], "count": row[1]}
                for row in cursor.fetchall()
            ]
            
            # Recent devices (last 7 days)
            cursor.execute("SELECT COUNT(*) FROM devices WHERE datetime(first_seen) > datetime('now', '-7 days')")
            recent_devices = cursor.fetchone()[0]
            
            return {
                "total_devices": total_devices,
                "online_devices": online_devices,
                "offline_devices": total_devices - online_devices,
                "claimed_devices": claimed_devices,
                "unclaimed_devices": total_devices - claimed_devices,
                "recent_devices": recent_devices,
                "firmware_distribution": firmware_distribution,
                "online_percentage": round((online_devices / total_devices) * 100) if total_devices > 0 else 0
            }
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting device statistics: {e}")
        raise HTTPException(status_code=500, detail=f"Error getting device statistics: {str(e)}")

@app.delete("/api/admin/devices/{device_id}", tags=["admin"])
async def delete_device(device_id: int, request: Request):
    """
    Delete a device from the system.
    This will remove the device and all associated user claims.
    """
    try:
        # Check authentication and admin privileges
        user_id = get_current_user(request)
        if not is_admin_user(user_id, request):
            raise HTTPException(status_code=403, detail="Admin access required")
        
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()
            
            # Check if device exists
            cursor.execute('SELECT device_id FROM devices WHERE id = ?', (device_id,))
            device = cursor.fetchone()
            if not device:
                raise HTTPException(status_code=404, detail="Device not found")
            
            # Delete user claims first (foreign key constraint)
            cursor.execute('DELETE FROM user_devices WHERE device_id = ?', (device_id,))
            
            # Delete device
            cursor.execute('DELETE FROM devices WHERE id = ?', (device_id,))
            
            conn.commit()
            
            logger.info(f"Admin {user_id} deleted device {device[0]} (ID: {device_id})")
            
            return {"message": f"Device {device[0]} deleted successfully"}
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting device {device_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Error deleting device: {str(e)}")

@app.put("/api/admin/devices/{device_id}/nickname", tags=["admin"])
async def set_device_nickname(device_id: int, nickname: str, request: Request):
    """
    Set or update a device nickname/location note.
    Creates a user_devices entry if it doesn't exist.
    """
    try:
        # Check authentication and admin privileges
        user_id = get_current_user(request)
        if not is_admin_user(user_id, request):
            raise HTTPException(status_code=403, detail="Admin access required")
        
        # Validate nickname
        if not nickname or len(nickname.strip()) == 0:
            raise HTTPException(status_code=400, detail="Nickname cannot be empty")
        
        nickname = nickname.strip()
        if len(nickname) > 100:
            raise HTTPException(status_code=400, detail="Nickname too long (max 100 characters)")
        
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()
            
            # Check if device exists
            cursor.execute('SELECT device_id FROM devices WHERE id = ?', (device_id,))
            device = cursor.fetchone()
            if not device:
                raise HTTPException(status_code=404, detail="Device not found")
            
            device_uuid = device[0]
            
            # Check if user_devices entry exists
            cursor.execute('SELECT id FROM user_devices WHERE device_id = ?', (device_id,))
            existing_entry = cursor.fetchone()
            
            if existing_entry:
                # Update existing nickname
                cursor.execute('''
                    UPDATE user_devices 
                    SET nickname = ?, user_id = ?
                    WHERE device_id = ?
                ''', (nickname, user_id, device_id))
                action = "updated"
            else:
                # Create new user_devices entry
                cursor.execute('''
                    INSERT INTO user_devices (user_id, device_id, nickname, created_at)
                    VALUES (?, ?, ?, CURRENT_TIMESTAMP)
                ''', (user_id, device_id, nickname))
                action = "set"
            
            conn.commit()
            
            logger.info(f"Admin {user_id} {action} nickname for device {device_uuid} (ID: {device_id}) to: {nickname}")
            
            return {
                "message": f"Device nickname {action} successfully",
                "device_id": device_uuid,
                "nickname": nickname
            }
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error setting nickname for device {device_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Error setting device nickname: {str(e)}")

@app.get("/api/admin/users", tags=["admin"])
async def get_all_users(request: Request):
    """
    Get all users from Authelia database for device claiming.
    """
    try:
        # Check authentication and admin privileges
        user_id = get_current_user(request)
        if not is_admin_user(user_id, request):
            raise HTTPException(status_code=403, detail="Admin access required")
        
        # For now, return known admin users - in production this would query Authelia
        users = [
            {"username": "thomas", "display_name": "Thomas"},
            {"username": "willie", "display_name": "Willie"},
            {"username": "seba", "display_name": "Seba"},
            {"username": "herman", "display_name": "Herman"}
        ]
        
        return {"users": users}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting users: {e}")
        raise HTTPException(status_code=500, detail=f"Error getting users: {str(e)}")

@app.put("/api/admin/devices/{device_id}/claim", tags=["admin"])
async def claim_device_for_user(device_id: int, user: str, request: Request):
    """
    Claim a device for a specific user (admin only).
    """
    try:
        # Check authentication and admin privileges
        admin_user = get_current_user(request)
        if not is_admin_user(admin_user):
            raise HTTPException(status_code=403, detail="Admin access required")
        
        # Validate user parameter
        if not user or len(user.strip()) == 0:
            raise HTTPException(status_code=400, detail="User cannot be empty")
        
        user = user.strip()
        
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()
            
            # Check if device exists
            cursor.execute('SELECT device_id FROM devices WHERE id = ?', (device_id,))
            device = cursor.fetchone()
            if not device:
                raise HTTPException(status_code=404, detail="Device not found")
            
            device_uuid = device[0]
            
            # Check if device is already claimed
            cursor.execute('SELECT user_id FROM user_devices WHERE device_id = ?', (device_id,))
            existing_claim = cursor.fetchone()
            
            if existing_claim:
                # Update existing claim
                cursor.execute('''
                    UPDATE user_devices 
                    SET user_id = ?
                    WHERE device_id = ?
                ''', (user, device_id))
                action = f"reassigned from {existing_claim[0]} to {user}"
            else:
                # Create new claim
                cursor.execute('''
                    INSERT INTO user_devices (user_id, device_id, created_at)
                    VALUES (?, ?, CURRENT_TIMESTAMP)
                ''', (user, device_id))
                action = f"claimed by {user}"
            
            conn.commit()
            
            logger.info(f"Admin {admin_user} {action} device {device_uuid} (ID: {device_id})")
            
            return {
                "message": f"Device {action} successfully",
                "device_id": device_uuid,
                "claimed_by": user
            }
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error claiming device {device_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Error claiming device: {str(e)}")

@app.get("/api/admin/users/management", tags=["admin"])
async def get_user_management_data(request: Request):
    """
    Get comprehensive user management data including roles, devices, and activity.
    """
    try:
        # Check authentication and admin privileges
        user_id = get_current_user(request)
        if not is_admin_user(user_id, request):
            raise HTTPException(status_code=403, detail="Admin access required")
        
        # Known users with roles (in production this would come from Authelia)
        users_data = [
            {"username": "thomas", "display_name": "Thomas", "role": "admin"},
            {"username": "willie", "display_name": "Willie", "role": "admin"},
            {"username": "seba", "display_name": "Seba", "role": "admin"},
            {"username": "herman", "display_name": "Herman", "role": "user"}
        ]
        
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()
            
            # Get device counts and last activity for each user
            for user in users_data:
                username = user["username"]
                
                # Count claimed devices
                cursor.execute('SELECT COUNT(*) FROM user_devices WHERE user_id = ?', (username,))
                device_count = cursor.fetchone()[0]
                user["device_count"] = device_count
                
                # Get last device activity (most recent last_seen from user's devices)
                cursor.execute('''
                    SELECT MAX(d.last_seen)
                    FROM devices d
                    JOIN user_devices ud ON d.id = ud.device_id
                    WHERE ud.user_id = ?
                ''', (username,))
                result = cursor.fetchone()
                last_activity = result[0] if result and result[0] else None
                
                # Calculate relative time for last activity
                last_activity_relative = None
                if last_activity:
                    try:
                        last_activity_dt = datetime.fromisoformat(last_activity.replace('Z', '+00:00'))
                        time_diff = datetime.now(timezone.utc) - last_activity_dt.replace(tzinfo=timezone.utc)
                        if time_diff.total_seconds() < 3600:  # Less than 1 hour
                            last_activity_relative = f"{int(time_diff.total_seconds() / 60)} minutes ago"
                        elif time_diff.total_seconds() < 86400:  # Less than 1 day
                            last_activity_relative = f"{int(time_diff.total_seconds() / 3600)} hours ago"
                        else:
                            last_activity_relative = f"{int(time_diff.total_seconds() / 86400)} days ago"
                    except:
                        last_activity_relative = "Unknown"
                
                user["last_activity"] = last_activity
                user["last_activity_relative"] = last_activity_relative or "Never"
                
                # Get list of user's devices with basic info
                cursor.execute('''
                    SELECT d.device_id, d.mac_address, ud.nickname, d.last_seen
                    FROM devices d
                    JOIN user_devices ud ON d.id = ud.device_id
                    WHERE ud.user_id = ?
                    ORDER BY d.last_seen DESC
                ''', (username,))
                
                devices = []
                for device_row in cursor.fetchall():
                    device_id, mac_address, nickname, last_seen = device_row
                    devices.append({
                        "device_id": device_id,
                        "mac_address": mac_address,
                        "nickname": nickname,
                        "last_seen": last_seen
                    })
                
                user["devices"] = devices
        
        return {
            "users": users_data,
            "total_users": len(users_data),
            "admin_users": len([u for u in users_data if u["role"] == "admin"]),
            "regular_users": len([u for u in users_data if u["role"] == "user"])
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting user management data: {e}")
        raise HTTPException(status_code=500, detail=f"Error getting user management data: {str(e)}")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)