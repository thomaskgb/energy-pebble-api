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
import os
import re
import json
import hashlib
from pathlib import Path
import sqlite3
import threading
import time
import shutil
import yaml
import secrets
import bcrypt
import firmware_signing

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

# Pydantic models for device management
class DeviceNicknameUpdate(BaseModel):
    nickname: str

class DeviceClaimRequest(BaseModel):
    user: str

class DeviceSelfClaimRequest(BaseModel):
    device_id: str
    secret: Optional[str] = None   # per-device secret from the QR sticker
    nickname: Optional[str] = None

# Pydantic models for API tokens
class TokenCreate(BaseModel):
    token_name: str
    expires_days: Optional[int] = None  # None = no expiration

class UserTokenCreate(BaseModel):
    token_name: str = "Home Assistant"
    expires_days: Optional[int] = None  # None = no expiration

class HomeCreate(BaseModel):
    name: str = "Home"
    address: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None

class HomeUpdate(BaseModel):
    name: Optional[str] = None
    address: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None

class DeviceHomeAssign(BaseModel):
    home_id: int

class TokenResponse(BaseModel):
    id: int
    token_name: str
    created_at: str
    expires_at: Optional[str]
    last_used_at: Optional[str]
    is_active: bool
    created_by: str

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

# Local development auth shim: set LOCAL_DEV_USER=<name> to act as that user
# without Traefik/Authelia in front. NEVER set this in production compose.
LOCAL_DEV_USER = os.environ.get("LOCAL_DEV_USER")
if LOCAL_DEV_USER:
    logging.getLogger(__name__).warning(
        f"LOCAL_DEV_USER={LOCAL_DEV_USER}: authentication is BYPASSED — local development only"
    )

def get_current_user(request: Request):
    """
    Hybrid authentication: supports both Authelia headers and API Bearer tokens.
    Returns user info dict with authentication details.
    """
    # First try to get user from Authelia headers (for web requests through proxy)
    user_id = request.headers.get("Remote-User")
    if user_id:
        remote_groups = request.headers.get("Remote-Groups", "")
        groups = [group.strip() for group in remote_groups.split(",") if group.strip()]
        return {
            'user_id': user_id,
            'auth_method': 'authelia',
            'is_admin': 'admins' in groups,
            'groups': groups
        }
    
    # Try to get from Authorization header for API tokens
    auth_header = request.headers.get("Authorization")
    if auth_header and auth_header.startswith("Bearer "):
        token = auth_header[7:]  # Remove "Bearer " prefix
        if token:
            # Validate API token
            token_info = validate_api_token(token)
            if token_info:
                # User-bound tokens (Home Assistant etc.) authenticate as the
                # user; legacy 'system' tokens stay system-wide admin.
                return {
                    'user_id': token_info.get('user_id') or 'system',
                    'auth_method': 'bearer_token',
                    'is_admin': token_info['is_admin'],
                    'token_name': token_info['token_name']
                }
    
    # Local development fallback (see LOCAL_DEV_USER above)
    if LOCAL_DEV_USER:
        return {
            'user_id': LOCAL_DEV_USER,
            'auth_method': 'local_dev',
            'is_admin': True,
            'groups': ['admins', 'users']
        }

    raise HTTPException(
        status_code=401,
        detail="Not authenticated",
        headers={"WWW-Authenticate": "Bearer"},
    )

def get_optional_user(request: Request) -> Optional[str]:
    """Get user from headers without raising exception if not authenticated."""
    return request.headers.get("Remote-User")

def get_admin_user(request: Request):
    """Get current user and verify admin privileges."""
    user_info = get_current_user(request)
    if not user_info['is_admin']:
        raise HTTPException(status_code=403, detail="Admin access required")
    return user_info

# Database setup
# /tmp is volume-mounted to ./data in docker-compose; ENERGY_PEBBLE_DATA_DIR
# allows tests and alternative deployments to relocate all persistent state.
DATA_DIR = Path(os.environ.get("ENERGY_PEBBLE_DATA_DIR", "/tmp"))
DB_PATH = DATA_DIR / "energy_pebble.db"
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
                status TEXT DEFAULT 'check',
                error_message TEXT,
                install_duration INTEGER,
                ip_address TEXT,
                user_agent TEXT
            )
        ''')
        
        # Create user_settings table: per-person signal & display preferences.
        # Every column default reproduces the pure price-based behavior, so a
        # missing row means "default pebble".
        # Users describe their household (contract, solar, battery); the color
        # signal is derived from that — see derive_signal_source().
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS user_settings (
                user_id TEXT PRIMARY KEY,
                contract_type TEXT NOT NULL DEFAULT 'dynamic',
                has_solar BOOLEAN NOT NULL DEFAULT 0,
                has_battery BOOLEAN NOT NULL DEFAULT 0,
                palette TEXT NOT NULL DEFAULT 'standard',
                brightness INTEGER NOT NULL DEFAULT 100,
                night_dim_enabled BOOLEAN NOT NULL DEFAULT 1,
                night_dim_start TEXT NOT NULL DEFAULT '22:00',
                night_dim_end TEXT NOT NULL DEFAULT '07:00',
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        for ddl, log_msg in [
            ("ALTER TABLE user_settings ADD COLUMN has_battery BOOLEAN NOT NULL DEFAULT 0",
             "Added has_battery column to user_settings table"),
            ("ALTER TABLE user_settings ADD COLUMN contract_type TEXT NOT NULL DEFAULT 'dynamic'",
             "Added contract_type column to user_settings table"),
        ]:
            try:
                cursor.execute(ddl)
                logger.info(log_msg)
            except sqlite3.OperationalError:
                pass  # Column already exists

        # Migrate rows saved under the old signal_source model, if any
        cursor.execute("PRAGMA table_info(user_settings)")
        if 'signal_source' in [col[1] for col in cursor.fetchall()]:
            cursor.execute("UPDATE user_settings SET contract_type = 'day_night' WHERE signal_source = 'day_night'")
            cursor.execute("UPDATE user_settings SET has_solar = 1 WHERE signal_source = 'solar'")

        # Homes: a user can have several; devices and settings hang off a home.
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS homes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                name TEXT NOT NULL DEFAULT 'Home',
                address TEXT,
                latitude REAL,
                longitude REAL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS home_settings (
                home_id INTEGER PRIMARY KEY,
                contract_type TEXT NOT NULL DEFAULT 'dynamic',
                has_solar BOOLEAN NOT NULL DEFAULT 0,
                has_battery BOOLEAN NOT NULL DEFAULT 0,
                palette TEXT NOT NULL DEFAULT 'standard',
                brightness INTEGER NOT NULL DEFAULT 100,
                night_dim_enabled BOOLEAN NOT NULL DEFAULT 1,
                night_dim_start TEXT NOT NULL DEFAULT '22:00',
                night_dim_end TEXT NOT NULL DEFAULT '07:00',
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (home_id) REFERENCES homes (id)
            )
        ''')
        try:
            cursor.execute("ALTER TABLE devices ADD COLUMN home_id INTEGER")
            logger.info("Added home_id column to devices table")
        except sqlite3.OperationalError:
            pass  # Column already exists
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_homes_user ON homes (user_id)')

        # Migration: every user with settings or claimed devices gets a default
        # home; their user_settings row becomes that home's settings, and their
        # claimed devices attach to it.
        cursor.execute('''
            SELECT DISTINCT user_id FROM user_settings
            UNION SELECT DISTINCT user_id FROM user_devices
        ''')
        for (uid,) in cursor.fetchall():
            cursor.execute('SELECT id FROM homes WHERE user_id = ? ORDER BY created_at, id LIMIT 1', (uid,))
            row = cursor.fetchone()
            if row:
                home_id = row[0]
            else:
                cursor.execute('INSERT INTO homes (user_id, name) VALUES (?, ?)', (uid, 'Home'))
                home_id = cursor.lastrowid
                logger.info(f"Created default home {home_id} for user {uid}")
            cursor.execute('''
                INSERT OR IGNORE INTO home_settings
                    (home_id, contract_type, has_solar, has_battery, palette, brightness,
                     night_dim_enabled, night_dim_start, night_dim_end, updated_at)
                SELECT ?, contract_type, has_solar, has_battery, palette, brightness,
                       night_dim_enabled, night_dim_start, night_dim_end, updated_at
                FROM user_settings WHERE user_id = ?
            ''', (home_id, uid))
            cursor.execute('''
                UPDATE devices SET home_id = ?
                WHERE home_id IS NULL AND id IN (SELECT device_id FROM user_devices WHERE user_id = ?)
            ''', (home_id, uid))

        # Account-level preferences. These belong to the person, not to a home
        # or a device: one language for the whole account, whichever home or
        # pebble they are looking at. A missing row means the defaults below.
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS user_preferences (
                user_id TEXT PRIMARY KEY,
                language TEXT NOT NULL DEFAULT 'en',
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        # Create API tokens table for bearer token authentication
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS api_tokens (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                token_hash TEXT UNIQUE NOT NULL,
                token_name TEXT NOT NULL,
                user_id TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                expires_at TIMESTAMP,
                last_used_at TIMESTAMP,
                is_active BOOLEAN DEFAULT TRUE,
                created_by TEXT
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
            
        # Remove scopes column from api_tokens table if it exists (migration from old schema)
        try:
            # Check if scopes column exists
            cursor.execute("PRAGMA table_info(api_tokens)")
            columns = [column[1] for column in cursor.fetchall()]
            if 'scopes' in columns:
                logger.info("Migrating api_tokens table to remove scopes column")
                # Create new table without scopes
                cursor.execute('''
                    CREATE TABLE api_tokens_new (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        token_hash TEXT UNIQUE NOT NULL,
                        token_name TEXT NOT NULL,
                        user_id TEXT NOT NULL,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        expires_at TIMESTAMP,
                        last_used_at TIMESTAMP,
                        is_active BOOLEAN DEFAULT TRUE,
                        created_by TEXT
                    )
                ''')
                # Copy data from old table
                cursor.execute('''
                    INSERT INTO api_tokens_new (id, token_hash, token_name, user_id, created_at, expires_at, last_used_at, is_active, created_by)
                    SELECT id, token_hash, token_name, user_id, created_at, expires_at, last_used_at, is_active, created_by
                    FROM api_tokens
                ''')
                # Drop old table and rename new one
                cursor.execute('DROP TABLE api_tokens')
                cursor.execute('ALTER TABLE api_tokens_new RENAME TO api_tokens')
                logger.info("Successfully migrated api_tokens table")
        except sqlite3.OperationalError:
            pass  # Migration not needed or already completed
            
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
            
        try:
            cursor.execute('ALTER TABLE firmware_versions ADD COLUMN md5_checksum TEXT')
            logger.info("Added md5_checksum column to firmware_versions table")
        except sqlite3.OperationalError:
            pass  # Column already exists

        # Migration: Ed25519 firmware signature (base64) + algorithm tag
        try:
            cursor.execute('ALTER TABLE firmware_versions ADD COLUMN signature TEXT')
            logger.info("Added signature column to firmware_versions table")
        except sqlite3.OperationalError:
            pass  # Column already exists
        try:
            cursor.execute('ALTER TABLE firmware_versions ADD COLUMN signature_alg TEXT')
            logger.info("Added signature_alg column to firmware_versions table")
        except sqlite3.OperationalError:
            pass  # Column already exists

        # Migration: Remove CHECK constraint from ota_logs.status column
        try:
            # Check if constraint exists by trying to insert an invalid status
            cursor.execute("INSERT INTO ota_logs (device_id, status) VALUES ('test', 'invalid_status')")
            cursor.execute("DELETE FROM ota_logs WHERE device_id = 'test'")
            logger.info("ota_logs table already migrated (no CHECK constraint)")
        except sqlite3.IntegrityError:
            # Constraint exists, need to migrate
            logger.info("Migrating ota_logs table to remove status CHECK constraint")
            
            # Create new table without CHECK constraint
            cursor.execute('''
                CREATE TABLE ota_logs_new (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    device_id TEXT NOT NULL,
                    check_timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    current_version TEXT,
                    offered_version TEXT,
                    status TEXT DEFAULT 'check',
                    error_message TEXT,
                    install_duration INTEGER,
                    ip_address TEXT,
                    user_agent TEXT
                )
            ''')
            
            # Copy data from old table
            cursor.execute('''
                INSERT INTO ota_logs_new 
                SELECT * FROM ota_logs
            ''')
            
            # Drop old table and rename new one
            cursor.execute('DROP TABLE ota_logs')
            cursor.execute('ALTER TABLE ota_logs_new RENAME TO ota_logs')
            
            logger.info("Successfully migrated ota_logs table")
        except Exception as e:
            logger.error(f"Error during ota_logs migration: {e}")
            pass
        
        # Create index for performance
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_devices_ip ON devices (client_ip)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_devices_fingerprint ON devices (device_fingerprint)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_user_devices_user ON user_devices (user_id)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_ota_logs_device ON ota_logs (device_id)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_ota_logs_timestamp ON ota_logs (check_timestamp)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_firmware_version ON firmware_versions (version)')

        # Per-device claim secrets: minted by an admin, printed in the QR
        # sticker at manufacturing time, and presented by the setup page as
        # proof of physical possession when claiming. Only the hash is stored.
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS device_secrets (
                device_id TEXT PRIMARY KEY,
                secret_hash TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                created_by TEXT
            )
        ''')

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
            SELECT version, filename, checksum, file_size, force_update, rollback_version, release_notes, min_version, md5_checksum, signature, signature_alg
            FROM firmware_versions
            WHERE is_stable = TRUE
            AND (target_devices IS NULL OR target_devices LIKE ? OR target_devices = '[]')
            ORDER BY release_date DESC
            LIMIT 1
        ''', (f'%{device_id}%',))

        result = cursor.fetchone()
        if not result:
            return None

        version, filename, checksum, file_size, force_update, rollback_version, release_notes, min_version, md5_checksum, signature, signature_alg = result
        
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
            'md5_checksum': md5_checksum,
            'file_size': file_size,
            'force_update': bool(force_update),
            'rollback_version': rollback_version,
            'release_notes': release_notes,
            'signature': signature,
            'signature_alg': signature_alg
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
            
            # Update device's last OTA check timestamp and current firmware version
            cursor.execute('''
                UPDATE devices 
                SET last_ota_check = CURRENT_TIMESTAMP,
                    current_firmware_version = ?
                WHERE device_id = ?
            ''', (current_version, device_id))
            
            conn.commit()
    except Exception as e:
        logger.error(f"Failed to log OTA check: {e}")

def calculate_file_checksum(file_path: Path) -> str:
    """Calculate SHA256 checksum of a file (legacy function for compatibility)"""
    sha256_hash = hashlib.sha256()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(4096), b""):
            sha256_hash.update(chunk)
    return f"sha256:{sha256_hash.hexdigest()}"

def calculate_file_checksums(file_path: Path) -> tuple[str, str]:
    """Calculate both SHA256 and MD5 checksums of a file"""
    sha256_hash = hashlib.sha256()
    md5_hash = hashlib.md5()
    
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(4096), b""):
            sha256_hash.update(chunk)
            md5_hash.update(chunk)
    
    return f"sha256:{sha256_hash.hexdigest()}", md5_hash.hexdigest()

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

# API Token Management Functions
def generate_api_token() -> str:
    """Generate a secure API token"""
    return secrets.token_urlsafe(32)

def hash_token(token: str) -> str:
    """Hash a token for secure storage"""
    return bcrypt.hashpw(token.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')

def verify_token(token: str, token_hash: str) -> bool:
    """Verify a token against its hash"""
    try:
        return bcrypt.checkpw(token.encode('utf-8'), token_hash.encode('utf-8'))
    except Exception:
        return False

def create_api_token(token_name: str, created_by: str, expires_days: Optional[int] = None) -> tuple[str, int]:
    """Create a new API token and return (token, token_id)"""
    token = generate_api_token()
    token_hash = hash_token(token)
    
    expires_at = None
    if expires_days:
        expires_at = datetime.now(timezone.utc) + timedelta(days=expires_days)
    
    with db_lock:
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO api_tokens (token_hash, token_name, user_id, expires_at, created_by)
                VALUES (?, ?, 'system', ?, ?)
            ''', (token_hash, token_name, expires_at, created_by))
            
            token_id = cursor.lastrowid
            conn.commit()
            
    return token, token_id

def create_user_api_token(user_id: str, token_name: str, expires_days: Optional[int] = None) -> tuple[str, int]:
    """Create a token bound to a user (e.g. for Home Assistant); returns (token, token_id).

    Unlike the legacy 'system' tokens (CI/admin), user tokens authenticate as
    the user and carry no admin rights.
    """
    token = generate_api_token()
    token_hash = hash_token(token)

    expires_at = None
    if expires_days:
        expires_at = datetime.now(timezone.utc) + timedelta(days=expires_days)

    with db_lock:
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO api_tokens (token_hash, token_name, user_id, expires_at, created_by)
                VALUES (?, ?, ?, ?, ?)
            ''', (token_hash, token_name, user_id, expires_at, user_id))
            token_id = cursor.lastrowid
            conn.commit()

    return token, token_id

def validate_api_token(token: str) -> Optional[Dict[str, Any]]:
    """Validate an API token and return token info if valid"""
    with db_lock:
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT id, token_hash, token_name, expires_at, is_active, user_id
                FROM api_tokens
                WHERE is_active = TRUE
            ''')

            for row in cursor.fetchall():
                token_id, token_hash, token_name, expires_at, is_active, user_id = row

                if verify_token(token, token_hash):
                    # Check if token is expired
                    if expires_at:
                        expires_datetime = datetime.fromisoformat(expires_at.replace('Z', '+00:00'))
                        if datetime.now(timezone.utc) > expires_datetime:
                            return None

                    # Update last_used_at
                    cursor.execute('''
                        UPDATE api_tokens SET last_used_at = ? WHERE id = ?
                    ''', (datetime.now(timezone.utc), token_id))
                    conn.commit()

                    return {
                        'id': token_id,
                        'token_name': token_name,
                        'user_id': user_id,
                        # Legacy 'system' tokens (CI/firmware upload) keep admin
                        # access; user-bound tokens are never admin.
                        'is_admin': user_id == 'system'
                    }

    return None

def get_all_api_tokens() -> List[Dict[str, Any]]:
    """Get all API tokens for admin dashboard"""
    with db_lock:
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT id, token_name, created_at, expires_at, last_used_at, is_active, created_by
                FROM api_tokens
                ORDER BY created_at DESC
            ''')
            
            tokens = []
            for row in cursor.fetchall():
                token_id, token_name, created_at, expires_at, last_used_at, is_active, created_by = row
                tokens.append({
                    'id': token_id,
                    'token_name': token_name,
                    'created_at': created_at,
                    'expires_at': expires_at,
                    'last_used_at': last_used_at,
                    'is_active': bool(is_active),
                    'created_by': created_by
                })
            
            return tokens

def revoke_api_token(token_id: int) -> bool:
    """Revoke an API token"""
    with db_lock:
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                UPDATE api_tokens SET is_active = FALSE WHERE id = ?
            ''', (token_id,))
            conn.commit()
            return cursor.rowcount > 0

# --- Per-person settings (household parameters & display preferences) --------
# The pebble stays dumb: all personalization is resolved server-side from the
# claiming user's profile. Users describe their household — contract type,
# solar, battery — and the color signal is derived from that. Defaults
# reproduce the pure price-based behavior.

CONTRACT_TYPES = ("dynamic", "day_night", "fixed")
PALETTES = ("standard", "colorblind")

DEFAULT_USER_SETTINGS = {
    "contract_type": "dynamic",
    "has_solar": False,
    "has_battery": False,  # solar-charged battery: bridges the evening peak on sunny days
    "palette": "standard",
    "brightness": 100,
    "night_dim_enabled": True,
    "night_dim_start": "22:00",
    "night_dim_end": "07:00",
}

def derive_signal_source(settings: Dict[str, Any]) -> str:
    """Map household parameters to the color signal.

    - day/night tariff contract -> two-state day/night colors (solar still
      turns production hours green, battery extends that into the evening)
    - fixed contract -> the price carries no signal: neutral, except solar
      production hours (self-consumption is the only lever)
    - dynamic + solar panels -> price colors boosted by the solar forecast
    - otherwise -> pure day-ahead price colors
    """
    if settings["contract_type"] == "day_night":
        return "day_night"
    if settings["contract_type"] == "fixed":
        return "fixed"
    if settings["has_solar"]:
        return "solar"
    return "price"

TIME_RE = re.compile(r'^([01]\d|2[0-3]):[0-5]\d$')

BRUSSELS_TZ = pytz.timezone("Europe/Brussels")
SOLAR_WINDOW_HOURS = (10, 16)   # local hours treated as the solar production window
NIGHT_TARIFF_START = 22         # Belgian day/night tariff: night from 22:00...
NIGHT_TARIFF_END = 7            # ...to 07:00 local, plus weekends

class UserSettingsUpdate(BaseModel):
    contract_type: Optional[str] = None
    has_solar: Optional[bool] = None
    has_battery: Optional[bool] = None
    palette: Optional[str] = None
    brightness: Optional[int] = None
    night_dim_enabled: Optional[bool] = None
    night_dim_start: Optional[str] = None
    night_dim_end: Optional[str] = None

def get_or_create_default_home(user_id: str) -> int:
    """The user's oldest home; created on first touch."""
    with db_lock, sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT id FROM homes WHERE user_id = ? ORDER BY created_at, id LIMIT 1', (user_id,))
        row = cursor.fetchone()
        if row:
            return row[0]
        cursor.execute('INSERT INTO homes (user_id, name) VALUES (?, ?)', (user_id, 'Home'))
        conn.commit()
        return cursor.lastrowid

def get_user_homes(user_id: str) -> List[Dict[str, Any]]:
    """The user's homes with their device counts."""
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute('''
            SELECT h.id, h.name, h.address, h.latitude, h.longitude, h.created_at,
                   (SELECT COUNT(*) FROM devices d WHERE d.home_id = h.id) AS device_count
            FROM homes h WHERE h.user_id = ?
            ORDER BY h.created_at, h.id
        ''', (user_id,))
        return [{
            "id": row[0], "name": row[1], "address": row[2],
            "latitude": row[3], "longitude": row[4],
            "created_at": row[5], "device_count": row[6],
        } for row in cursor.fetchall()]

def get_home_owner(home_id: int) -> Optional[str]:
    with sqlite3.connect(DB_PATH) as conn:
        row = conn.execute('SELECT user_id FROM homes WHERE id = ?', (home_id,)).fetchone()
    return row[0] if row else None

def get_home_settings(home_id: int) -> Dict[str, Any]:
    """Return the home's settings merged over defaults."""
    settings = dict(DEFAULT_USER_SETTINGS)
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute('''
            SELECT contract_type, has_solar, has_battery, palette, brightness,
                   night_dim_enabled, night_dim_start, night_dim_end
            FROM home_settings WHERE home_id = ?
        ''', (home_id,))
        row = cursor.fetchone()
    if row:
        settings.update({
            "contract_type": row[0],
            "has_solar": bool(row[1]),
            "has_battery": bool(row[2]),
            "palette": row[3],
            "brightness": row[4],
            "night_dim_enabled": bool(row[5]),
            "night_dim_start": row[6],
            "night_dim_end": row[7],
        })
    return settings

def save_home_settings(home_id: int, updates: UserSettingsUpdate) -> Dict[str, Any]:
    """Validate and persist a partial settings update for a home."""
    changes = {k: v for k, v in updates.model_dump().items() if v is not None}

    if "contract_type" in changes and changes["contract_type"] not in CONTRACT_TYPES:
        raise HTTPException(status_code=400, detail=f"contract_type must be one of {list(CONTRACT_TYPES)}")
    if "palette" in changes and changes["palette"] not in PALETTES:
        raise HTTPException(status_code=400, detail=f"palette must be one of {list(PALETTES)}")
    if "brightness" in changes and not (5 <= changes["brightness"] <= 100):
        raise HTTPException(status_code=400, detail="brightness must be between 5 and 100")
    for field in ("night_dim_start", "night_dim_end"):
        if field in changes and not TIME_RE.match(changes[field]):
            raise HTTPException(status_code=400, detail=f"{field} must be HH:MM (24h)")

    settings = get_home_settings(home_id)
    settings.update(changes)

    with db_lock, sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO home_settings (home_id, contract_type, has_solar, has_battery, palette, brightness,
                                       night_dim_enabled, night_dim_start, night_dim_end, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(home_id) DO UPDATE SET
                contract_type = excluded.contract_type,
                has_solar = excluded.has_solar,
                has_battery = excluded.has_battery,
                palette = excluded.palette,
                brightness = excluded.brightness,
                night_dim_enabled = excluded.night_dim_enabled,
                night_dim_start = excluded.night_dim_start,
                night_dim_end = excluded.night_dim_end,
                updated_at = CURRENT_TIMESTAMP
        ''', (home_id, settings["contract_type"], settings["has_solar"], settings["has_battery"],
              settings["palette"], settings["brightness"], settings["night_dim_enabled"],
              settings["night_dim_start"], settings["night_dim_end"]))
        conn.commit()

    logger.info(f"Saved settings for home {home_id}: {changes}")
    return settings

def get_user_settings(user_id: str) -> Dict[str, Any]:
    """The user's default home's settings (backward-compatible helper)."""
    return get_home_settings(get_or_create_default_home(user_id))

def save_user_settings(user_id: str, updates: UserSettingsUpdate) -> Dict[str, Any]:
    """Save to the user's default home (backward-compatible helper)."""
    return save_home_settings(get_or_create_default_home(user_id), updates)

# --- Account preferences ------------------------------------------------------
# Settings that belong to the person rather than to a home or a device. The
# interface language is the first of them: it drives the web UI only — the
# pebble itself shows colors, which need no translation.

LANGUAGES = ("en", "nl", "fr")

DEFAULT_USER_PREFERENCES = {
    "language": "en",
}

class UserPreferencesUpdate(BaseModel):
    language: Optional[str] = None

def get_user_preferences(user_id: str) -> Dict[str, Any]:
    """Return the user's account preferences merged over defaults."""
    preferences = dict(DEFAULT_USER_PREFERENCES)
    with sqlite3.connect(DB_PATH) as conn:
        row = conn.execute(
            'SELECT language FROM user_preferences WHERE user_id = ?', (user_id,)
        ).fetchone()
    if row:
        preferences["language"] = row[0]
    return preferences

def save_user_preferences(user_id: str, updates: UserPreferencesUpdate) -> Dict[str, Any]:
    """Validate and persist a partial preferences update."""
    changes = {k: v for k, v in updates.model_dump().items() if v is not None}

    if "language" in changes and changes["language"] not in LANGUAGES:
        raise HTTPException(status_code=400, detail=f"language must be one of {list(LANGUAGES)}")

    preferences = get_user_preferences(user_id)
    preferences.update(changes)

    with db_lock, sqlite3.connect(DB_PATH) as conn:
        conn.execute('''
            INSERT INTO user_preferences (user_id, language, updated_at)
            VALUES (?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(user_id) DO UPDATE SET
                language = excluded.language,
                updated_at = CURRENT_TIMESTAMP
        ''', (user_id, preferences["language"]))
        conn.commit()

    logger.info(f"Saved preferences for user {user_id}: {changes}")
    return preferences

def get_settings_for_device(device_id: Optional[str]) -> tuple[Optional[str], Optional[Dict[str, Any]]]:
    """Resolve a device id to its home's settings.

    Devices belong to a home (devices.home_id); a claimed device without a
    home falls back to its owner's default home. Returns (user_id, settings);
    (None, None) for unknown or unclaimed devices.
    """
    if not device_id:
        return None, None
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute('''
            SELECT d.home_id, h.user_id, ud.user_id
            FROM devices d
            LEFT JOIN homes h ON h.id = d.home_id
            LEFT JOIN user_devices ud ON ud.device_id = d.id
            WHERE d.device_id = ?
            ORDER BY ud.created_at ASC
            LIMIT 1
        ''', (device_id,))
        row = cursor.fetchone()
    if not row:
        return None, None
    home_id, home_owner, claimer = row
    if home_id and home_owner:
        return home_owner, get_home_settings(home_id)
    if claimer:
        return claimer, get_user_settings(claimer)
    return None, None

BATTERY_BRIDGE_HOURS = (17, 22)      # local evening window a charged battery can cover
BATTERY_MIN_CHARGE_HOURS = 3         # solar hours before 17:00 needed to call the battery "charged"

def _battery_charged_days(solar_boost: Optional[set]) -> Optional[set]:
    """Local calendar days on which a solar-charged battery filled up.

    A day counts when the forecast gave at least BATTERY_MIN_CHARGE_HOURS of
    production before the evening window. None means "no forecast, assume
    charged" (matches the fixed-window fallback of 6 midday hours).
    """
    if solar_boost is None:
        return None
    counts: Dict[Any, int] = {}
    for hour_key in solar_boost:
        local = datetime.fromisoformat(hour_key.replace('Z', '+00:00')).astimezone(BRUSSELS_TZ)
        if local.hour < BATTERY_BRIDGE_HOURS[0]:
            counts[local.date()] = counts.get(local.date(), 0) + 1
    return {day for day, n in counts.items() if n >= BATTERY_MIN_CHARGE_HOURS}

def apply_signal_source(color_codes: List[Dict[str, Any]], settings: Dict[str, Any],
                        solar_boost: Optional[set] = None) -> List[Dict[str, Any]]:
    """Transform the committed price-based colors according to the profile.

    Transforms are deterministic functions of (committed color, hour), so the
    8-hour stability guarantee of the default pipeline carries over unchanged.
    For 'solar', solar_boost is the set of hour_keys with committed forecast
    boost (see get_solar_boost_hours); without it a fixed midday window is the
    offline fallback.

    Solar households with a battery get the evening bridge: a solar-charged
    battery delays evening grid consumption, but only on days it actually
    charged -> soften R to Y during 17:00-22:00 local after a sunny day.
    (Curtailment at negative prices is assumed: it is a prerequisite of a
    dynamic contract, so it needs no setting and no color handling.)
    """
    source = derive_signal_source(settings)
    if source == "price":
        return color_codes

    charged_days = _battery_charged_days(solar_boost) if settings.get("has_battery") else set()

    result = []
    for entry in color_codes:
        entry = dict(entry)
        hour_utc = datetime.fromisoformat(entry["hour"].replace('Z', '+00:00'))
        local = hour_utc.astimezone(BRUSSELS_TZ)

        if solar_boost is not None:
            solar_hour = entry["hour"] in solar_boost
        else:
            solar_hour = SOLAR_WINDOW_HOURS[0] <= local.hour < SOLAR_WINDOW_HOURS[1]
        in_bridge = BATTERY_BRIDGE_HOURS[0] <= local.hour < BATTERY_BRIDGE_HOURS[1]
        battery_charged = (settings.get("has_battery") and settings.get("has_solar")
                           and (charged_days is None or local.date() in charged_days))

        if source == "day_night":
            # Two-state display for day/night tariff contracts: night + weekend
            # is the cheap tariff, daytime on weekdays is not. Never red.
            is_night = local.hour >= NIGHT_TARIFF_START or local.hour < NIGHT_TARIFF_END
            is_weekend = local.weekday() >= 5
            entry["color_code"] = "G" if (is_night or is_weekend) else "Y"
            # Solar panels still beat the day tariff: self-consuming during
            # production hours is free energy, so those hours go green too...
            if settings.get("has_solar") and solar_hour:
                entry["color_code"] = "G"
            # ...and a battery charged on a sunny day carries that into the
            # evening until the night tariff takes over.
            if battery_charged and in_bridge and entry["color_code"] == "Y":
                entry["color_code"] = "G"
        elif source == "fixed":
            # Flat tariff: the price carries no signal. Neutral, except own
            # solar production, which is the one lever a fixed household has.
            entry["color_code"] = "G" if (settings.get("has_solar") and solar_hour) else "Y"
        elif source == "solar":
            # Surplus solar makes consuming one step "greener" than price alone
            # says: forecast-driven when available, fixed midday window otherwise.
            if solar_hour:
                entry["color_code"] = {"R": "Y", "Y": "G", "G": "G"}[entry["color_code"]]
            # Battery evening bridge: soften the evening peak on charged days
            if battery_charged and in_bridge and entry["color_code"] == "R":
                entry["color_code"] = "Y"
        result.append(entry)
    return result

NIGHT_DIM_BRIGHTNESS = 30  # % brightness while night dimming is active

def build_display_block(settings: Dict[str, Any]) -> Dict[str, Any]:
    """Display instructions for the firmware; old firmware ignores this block."""
    return {
        "palette": settings["palette"],
        "brightness": settings["brightness"],
        "night_dim": ({
            "from": settings["night_dim_start"],
            "to": settings["night_dim_end"],
            "brightness": NIGHT_DIM_BRIGHTNESS,
        } if settings["night_dim_enabled"] else None),
    }

# --- Solar forecast (Open-Meteo) ---------------------------------------------
# For the 'solar' signal source: instead of a fixed midday window, boost hours
# where the radiation forecast says there is meaningful solar production.
# Boost decisions are committed per hour (like colors) so a shifting forecast
# never flips a color the user has already seen.

SOLAR_FORECAST_URL = (
    "https://api.open-meteo.com/v1/forecast"
    "?latitude=50.85&longitude=4.35"          # Brussels; good enough country-wide
    "&hourly=shortwave_radiation&forecast_days=3&timezone=UTC"
)
SOLAR_FORECAST_TTL_SECONDS = 3600
SOLAR_BOOST_MIN_WM2 = 100        # absolute floor: below this, no meaningful production
SOLAR_BOOST_RELATIVE = 0.35      # ...and at least 35% of the forecast window's peak

solar_forecast_cache: Dict[str, Any] = {"fetched_at": 0.0, "radiation": {}}
solar_boost_file = DATA_DIR / "solar_boost.json"

def compute_solar_boost(radiation: Dict[str, float]) -> Dict[str, bool]:
    """Pure decision function: hour_key -> should this hour be boosted."""
    if not radiation:
        return {}
    peak = max(radiation.values())
    threshold = max(SOLAR_BOOST_MIN_WM2, SOLAR_BOOST_RELATIVE * peak)
    return {hour: value >= threshold for hour, value in radiation.items()}

async def get_solar_boost_hours() -> Optional[set]:
    """Set of hour_keys with committed solar boost; None if no forecast available."""
    now = time.time()
    if now - solar_forecast_cache["fetched_at"] > SOLAR_FORECAST_TTL_SECONDS:
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(SOLAR_FORECAST_URL)
                resp.raise_for_status()
                data = resp.json()
            hours = data["hourly"]["time"]
            values = data["hourly"]["shortwave_radiation"]
            solar_forecast_cache["radiation"] = {
                f"{t}:00Z": (v or 0.0) for t, v in zip(hours, values)
            }
            solar_forecast_cache["fetched_at"] = now
        except Exception as e:
            logger.warning(f"Solar forecast fetch failed: {e}")

    radiation = solar_forecast_cache["radiation"]
    if not radiation:
        return None

    # Commit each hour's boost decision the first time we see it, prune the past.
    try:
        committed = json.loads(solar_boost_file.read_text()) if solar_boost_file.exists() else {}
    except Exception:
        committed = {}
    fresh = compute_solar_boost(radiation)
    current_hour = datetime.now(pytz.UTC).replace(minute=0, second=0, microsecond=0)
    for hour_key, boosted in fresh.items():
        committed.setdefault(hour_key, boosted)
    committed = {
        k: v for k, v in committed.items()
        if datetime.fromisoformat(k.replace('Z', '+00:00')) >= current_hour
    }
    try:
        solar_boost_file.write_text(json.dumps(committed))
    except Exception as e:
        logger.warning(f"Could not persist solar boost cache: {e}")

    return {hour for hour, boosted in committed.items() if boosted}

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

# Serve the static site under /static for local development (in production
# Caddy serves these files at / and Traefik never routes /static here).
_static_dir = Path(__file__).parent / "static"
if _static_dir.is_dir():
    from fastapi.staticfiles import StaticFiles
    app.mount("/static", StaticFiles(directory=str(_static_dir), html=True), name="static")

# Local development page routes, mirroring Caddy's rewrites so links like the
# homepage Login button work without the edge stack. Only registered with the
# LOCAL_DEV_USER shim; in production these paths never reach this app.
if LOCAL_DEV_USER:
    from fastapi.responses import RedirectResponse

    @app.get("/dashboard", include_in_schema=False)
    async def _dev_dashboard():
        return RedirectResponse("/static/dashboard.html")

    @app.get("/impact-circle", include_in_schema=False)
    async def _dev_impact_circle():
        return RedirectResponse("/static/impact-circle.html")

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
cache_file_path = DATA_DIR / "committed_colors.json"

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
            "/api/color-code": "Color codes for the current hour and next 8 hours. Devices sending X-Device-ID get their household's personalized signal plus a display block (palette, brightness, night dim)",
            "/api/user/settings": "GET/PUT the household profile driving personalization: contract type, solar, battery, display preferences (authentication required)",
            "/api/user/preferences": "GET/PUT account-level preferences such as the interface language (authentication required)",
            "/api/sample": "Get sample electricity price data for testing",
            "/api/sample-color-code": "Get sample color codes for testing",
            "/docs": "API documentation (Swagger UI)"
        }
    }

@app.get("/api/json", tags=["public"])
async def get_json_data(date: Optional[str] = None):
    """
    Get raw electricity price data in JSON format from Elia's day-ahead market.
    
    Authentication: None required - public endpoint.
    
    Optional query parameters:
    - date: Specific date in YYYY-MM-DD format (defaults to today)
    
    Returns unprocessed price data for the specified date, useful for analysis
    and custom applications requiring raw market data.
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
    Get color codes (G, Y, R) for the current hour and next 8 hours based on price analysis.
    Uses commitment-based stability - colors won't change once committed.

    Personalization: when the device id (X-Device-ID header or device_id query
    parameter) belongs to a claimed device, the colors are transformed for that
    household's profile (contract type, solar with live radiation forecast,
    battery evening bridge) and the response carries a `display` block with
    palette, brightness, and night-dim instructions for the firmware. Unknown
    or unclaimed devices get the default pure price-based signal; the response
    shape is backward compatible either way (`meta.personalized` tells which).

    Optional query parameters:
    - date: Date in YYYY-MM-DD format
    - device_id: ESP32 eFuse MAC address (12-character hex string, e.g., '904fb0453ab4')
    """
    final_device_id = device_id or request.headers.get("x-device-id")

    # Log device request for tracking (non-breaking)
    try:
        client_ip = get_real_client_ip(request)
        user_agent = request.headers.get("user-agent", "unknown")

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

    # Personalize for claimed devices; unknown/unclaimed devices get defaults.
    settings = None
    try:
        _, settings = get_settings_for_device(final_device_id)
        if settings:
            solar_boost = None
            if settings.get("has_solar"):
                solar_boost = await get_solar_boost_hours()
            display_colors = apply_signal_source(display_colors, settings, solar_boost)
    except Exception as e:
        logger.warning(f"Settings resolution failed (falling back to defaults): {e}")
        settings = None
    effective_settings = settings or DEFAULT_USER_SETTINGS

    # Return both the current hour and display color codes
    return {
        "current_hour": current_hour,
        "hour_color_codes": display_colors,
        "display": build_display_block(effective_settings),
        "meta": {
            "total_hours": len(display_colors),
            "committed_hours": committed_count,
            "flexible_hours": len(display_colors) - committed_count,
            "reference_window_hours": 48,
            "commitment_window_hours": 8,
            "signal_source": derive_signal_source(effective_settings),
            "personalized": settings is not None
        }
    }

@app.get("/api/sample", tags=["public"])
async def get_sample_data():
    """
    Get sample electricity price data for testing and development.
    
    Authentication: None required - public endpoint.
    
    Returns realistic sample data spanning multiple days with various price
    scenarios for testing color calculations and application development
    without relying on live market data.
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
    
    Authentication: None required - public endpoint.
    
    Returns processed color codes (G/Y/R) based on sample price data,
    useful for testing device behavior and UI components without affecting
    production color commitments.
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
    Verify user authentication and return user information from Authelia.
    
    Authentication: Requires valid Authelia session (forwarded headers).
    
    Used by the dashboard and protected routes to check authentication status
    and retrieve user details. Returns user ID, display name, email, groups,
    and admin status based on Authelia headers.
    """
    # Get user information from Authelia headers
    remote_user = request.headers.get("Remote-User")
    remote_name = request.headers.get("Remote-Name")
    remote_email = request.headers.get("Remote-Email")
    remote_groups = request.headers.get("Remote-Groups")

    # Local development fallback (see LOCAL_DEV_USER at the top of this file)
    if not remote_user and LOCAL_DEV_USER:
        remote_user = LOCAL_DEV_USER
        remote_groups = "admins,users"

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
                       d.mac_address, d.software_version, d.last_ota_check,
                       ud.nickname, ud.created_at, d.home_id, h.name
                FROM devices d
                JOIN user_devices ud ON d.id = ud.device_id
                LEFT JOIN homes h ON h.id = d.home_id
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
                    "last_ota_check": row[10],
                    "nickname": row[11],
                    "claimed_at": row[12],
                    "home_id": row[13],
                    "home_name": row[14],
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
    Get all devices claimed by the authenticated user with detection info.
    
    Authentication: Requires valid Authelia session.
    
    Returns both claimed devices (user's named devices) and detected devices
    (discovered on user's network) for device management dashboard.
    """
    try:
        # Get user directly from authentication function
        user_info = get_current_user(request)
        user_id = user_info['user_id']
        
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()
            
            cursor.execute('''
                SELECT d.id, d.device_fingerprint, d.first_seen, d.last_seen,
                       d.user_agent, d.request_count, d.device_id, d.client_ip,
                       d.mac_address, d.software_version, d.last_ota_check,
                       ud.nickname, ud.created_at, d.home_id, h.name
                FROM devices d
                JOIN user_devices ud ON d.id = ud.device_id
                LEFT JOIN homes h ON h.id = d.home_id
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
                    "last_ota_check": row[10],
                    "nickname": row[11],
                    "claimed_at": row[12],
                    "home_id": row[13],
                    "home_name": row[14],
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

@app.post("/api/user/devices/claim", tags=["user"])
async def claim_own_device(claim: DeviceSelfClaimRequest, request: Request):
    """
    Self-service device claim from the setup page (setup/index.html).

    Authentication: Requires valid Authelia session (route is behind the
    /api/user forward-auth rule in Traefik).

    Proof of possession, first match wins:
    1. `secret` matches the device's minted QR-sticker secret, or
    2. the device has recently phoned home from the same public IP as the
       requester (same household network).

    The device does not need to have contacted the API yet when a valid
    secret is presented - a placeholder row is created and filled in when
    the device first phones home.
    """
    user_info = get_current_user(request)
    user_id = user_info['user_id']

    device_id = (claim.device_id or "").strip().lower()
    if not re.fullmatch(r"[0-9a-f]{12}", device_id):
        raise HTTPException(status_code=400,
                            detail="device_id must be 12 hex characters")
    nickname = (claim.nickname or "").strip() or None
    client_ip = get_real_client_ip(request)

    try:
        with db_lock:
            with sqlite3.connect(DB_PATH) as conn:
                cursor = conn.cursor()

                cursor.execute(
                    'SELECT id, client_ip, last_seen FROM devices WHERE device_id = ?',
                    (device_id,))
                device_row = cursor.fetchone()

                # Proof of possession
                proof = None
                if claim.secret:
                    cursor.execute(
                        'SELECT secret_hash FROM device_secrets WHERE device_id = ?',
                        (device_id,))
                    secret_row = cursor.fetchone()
                    if secret_row and verify_token(claim.secret, secret_row[0]):
                        proof = "secret"
                if proof is None and device_row:
                    status, _ = calculate_device_status(device_row[2])
                    if device_row[1] == client_ip and status in ("online", "recently_active"):
                        proof = "same_network"
                if proof is None:
                    raise HTTPException(
                        status_code=403,
                        detail="Cannot verify you have this device: scan its QR "
                               "sticker, or make sure it is online on the same "
                               "network as you")

                # Ensure a devices row exists so the claim has something to
                # attach to. last_seen stays NULL until the device phones home
                # (log_device_request fills it in), so it reports as offline.
                if device_row:
                    device_db_id = device_row[0]
                else:
                    placeholder_fp = hashlib.sha256(
                        f"claim:{device_id}".encode()).hexdigest()[:16]
                    cursor.execute('''
                        INSERT INTO devices (client_ip, device_fingerprint,
                                             first_seen, last_seen, user_agent,
                                             device_id, mac_address)
                        VALUES (?, ?, ?, NULL, ?, ?, ?)
                    ''', (client_ip, placeholder_fp, datetime.now(pytz.UTC),
                          "claimed-before-first-contact", device_id,
                          generate_mac_from_device_id(device_id)))
                    device_db_id = cursor.lastrowid

                cursor.execute(
                    'SELECT user_id FROM user_devices WHERE device_id = ?',
                    (device_db_id,))
                existing = cursor.fetchone()
                if existing and existing[0] != user_id:
                    raise HTTPException(
                        status_code=409,
                        detail="This device is already linked to another "
                               "account. Contact support to transfer it.")
                if existing:
                    if nickname:
                        cursor.execute(
                            'UPDATE user_devices SET nickname = ? WHERE device_id = ?',
                            (nickname, device_db_id))
                    message = "Device was already linked to your account"
                else:
                    cursor.execute('''
                        INSERT INTO user_devices (user_id, device_id, nickname)
                        VALUES (?, ?, ?)
                    ''', (user_id, device_db_id, nickname))
                    message = "Device linked to your account"

                conn.commit()

        logger.info(f"User {user_id} claimed device {device_id} (proof: {proof})")
        return {
            "message": message,
            "device_id": device_id,
            "claimed_by": user_id,
            "proof": proof,
            "nickname": nickname,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in self-claim for device {device_id}: {e}")
        raise HTTPException(status_code=500, detail="Error claiming device")

@app.get("/api/user/devices/{device_id}/status", tags=["user"])
async def get_own_device_status(device_id: str, request: Request):
    """
    Lightweight online/offline poll for the setup page while it waits for a
    freshly provisioned device to phone home.

    Authentication: Requires valid Authelia session.
    """
    user_info = get_current_user(request)
    user_id = user_info['user_id']

    device_id = (device_id or "").strip().lower()
    if not re.fullmatch(r"[0-9a-f]{12}", device_id):
        raise HTTPException(status_code=400,
                            detail="device_id must be 12 hex characters")
    try:
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT d.last_seen, ud.user_id
                FROM devices d
                LEFT JOIN user_devices ud ON ud.device_id = d.id
                WHERE d.device_id = ?
            ''', (device_id,))
            row = cursor.fetchone()

        if not row:
            return {"device_id": device_id, "online": False,
                    "status": "never_seen", "claimed_by_you": False}
        status, minutes_ago = calculate_device_status(row[0])
        return {
            "device_id": device_id,
            "online": status == "online",
            "status": status,
            "minutes_since_last_seen": minutes_ago if row[0] else None,
            "claimed_by_you": row[1] == user_id,
        }
    except Exception as e:
        logger.error(f"Error fetching status for device {device_id}: {e}")
        raise HTTPException(status_code=500, detail="Error fetching device status")

@app.get("/api/user/profile", tags=["user"])
async def get_user_profile(request: Request):
    """Get current user profile information."""
    try:
        user_info = get_current_user(request)
        user_id = user_info['user_id']
        
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
        user_info = get_current_user(request)
        user_id = user_info['user_id']
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

@app.get("/api/user/settings", tags=["user"])
async def get_user_settings_endpoint(request: Request, home_id: Optional[int] = None):
    """
    Get the authenticated user's pebble settings for one home.

    Authentication: Requires valid Authelia session or API token.

    Optional home_id selects which home (default: your oldest home). Missing
    settings fall back to defaults, which reproduce the pure price-based
    behavior.
    """
    try:
        user_info = get_current_user(request)
        if home_id is None:
            home_id = get_or_create_default_home(user_info['user_id'])
        else:
            _require_own_home(user_info['user_id'], home_id)
        settings = get_home_settings(home_id)
        return {
            "user_id": user_info['user_id'],
            "home_id": home_id,
            "settings": settings,
            "derived_signal": derive_signal_source(settings),
            "options": {
                "contract_type": list(CONTRACT_TYPES),
                "palette": list(PALETTES),
            }
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching user settings: {e}")
        raise HTTPException(status_code=500, detail=f"Error fetching user settings: {str(e)}")

@app.put("/api/user/settings", tags=["user"])
async def update_user_settings_endpoint(updates: UserSettingsUpdate, request: Request,
                                        home_id: Optional[int] = None):
    """
    Update the pebble settings of one of the user's homes (partial update).

    Authentication: Requires valid Authelia session or API token.

    Optional home_id selects which home (default: your oldest home).
    Households are described, not configured: contract_type
    ('dynamic' | 'day_night' | 'fixed'), has_solar, has_battery — the color
    signal is derived from these. Display fields: palette
    ('standard' | 'colorblind'), brightness (5-100), night_dim_enabled,
    night_dim_start/night_dim_end ('HH:MM').
    Devices pick the change up on their next /api/color-code poll.
    """
    try:
        user_info = get_current_user(request)
        if home_id is None:
            home_id = get_or_create_default_home(user_info['user_id'])
        else:
            _require_own_home(user_info['user_id'], home_id)
        settings = save_home_settings(home_id, updates)
        return {
            "message": "Settings updated successfully",
            "user_id": user_info['user_id'],
            "home_id": home_id,
            "settings": settings,
            "derived_signal": derive_signal_source(settings)
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating user settings: {e}")
        raise HTTPException(status_code=500, detail=f"Error updating user settings: {str(e)}")

@app.get("/api/test/user/settings", tags=["user"])
async def test_get_user_settings(user: str = Query("thomas", description="Test user (thomas or willie)")):
    """Test endpoint for user settings - local development (blocked at the edge)."""
    settings = get_user_settings(user)
    return {
        "user_id": user,
        "settings": settings,
        "derived_signal": derive_signal_source(settings),
        "options": {
            "contract_type": list(CONTRACT_TYPES),
            "palette": list(PALETTES),
        }
    }

@app.put("/api/test/user/settings", tags=["user"])
async def test_update_user_settings(updates: UserSettingsUpdate, user: str = Query("thomas", description="Test user (thomas or willie)")):
    """Test endpoint for updating user settings - local development (blocked at the edge)."""
    settings = save_user_settings(user, updates)
    return {
        "message": "Settings updated successfully (test mode)",
        "user_id": user,
        "settings": settings,
        "derived_signal": derive_signal_source(settings)
    }

# --- Account preferences ------------------------------------------------------

@app.get("/api/user/preferences", tags=["user"])
async def get_user_preferences_endpoint(request: Request):
    """
    Get the authenticated user's account preferences.

    Authentication: Requires valid Authelia session or API token.

    Account preferences apply to the person, not to a home or a device.
    Currently: `language`, the interface language of the web UI.
    """
    try:
        user_info = get_current_user(request)
        return {
            "user_id": user_info['user_id'],
            "preferences": get_user_preferences(user_info['user_id']),
            "options": {"language": list(LANGUAGES)},
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching user preferences: {e}")
        raise HTTPException(status_code=500, detail=f"Error fetching user preferences: {str(e)}")

@app.put("/api/user/preferences", tags=["user"])
async def update_user_preferences_endpoint(updates: UserPreferencesUpdate, request: Request):
    """
    Update the authenticated user's account preferences (partial update).

    Authentication: Requires valid Authelia session or API token.

    `language` is one of 'en', 'nl', 'fr'. It changes the web interface only;
    the pebble shows colors and is unaffected.
    """
    try:
        user_info = get_current_user(request)
        return {
            "message": "Preferences updated successfully",
            "user_id": user_info['user_id'],
            "preferences": save_user_preferences(user_info['user_id'], updates),
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating user preferences: {e}")
        raise HTTPException(status_code=500, detail=f"Error updating user preferences: {str(e)}")

@app.get("/api/test/user/preferences", tags=["user"])
async def test_get_user_preferences(user: str = Query("thomas", description="Test user (thomas or willie)")):
    """Test endpoint for account preferences - local development (blocked at the edge)."""
    return {
        "user_id": user,
        "preferences": get_user_preferences(user),
        "options": {"language": list(LANGUAGES)},
    }

@app.put("/api/test/user/preferences", tags=["user"])
async def test_update_user_preferences(updates: UserPreferencesUpdate,
                                       user: str = Query("thomas", description="Test user (thomas or willie)")):
    """Test endpoint for updating account preferences - local development (blocked at the edge)."""
    return {
        "message": "Preferences updated successfully (test mode)",
        "user_id": user,
        "preferences": save_user_preferences(user, updates),
    }

# --- Homes --------------------------------------------------------------------
# A user can have several homes; devices and household settings belong to a
# home. The user's oldest home acts as the default for backward compatibility.

def _require_own_home(user_id: str, home_id: int) -> None:
    if get_home_owner(home_id) != user_id:
        raise HTTPException(status_code=404, detail="Home not found")

@app.get("/api/user/homes", tags=["user"])
async def list_homes(request: Request):
    """List the authenticated user's homes (a default home is created on first use)."""
    user_info = get_current_user(request)
    get_or_create_default_home(user_info['user_id'])
    return {"homes": get_user_homes(user_info['user_id'])}

@app.post("/api/user/homes", tags=["user"])
async def create_home(home: HomeCreate, request: Request):
    """Add a home (name, optional address/coordinates)."""
    user_info = get_current_user(request)
    name = home.name.strip() or "Home"
    with db_lock, sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO homes (user_id, name, address, latitude, longitude)
            VALUES (?, ?, ?, ?, ?)
        ''', (user_info['user_id'], name, home.address, home.latitude, home.longitude))
        conn.commit()
        home_id = cursor.lastrowid
    logger.info(f"User {user_info['user_id']} created home {home_id} ({name})")
    return {"id": home_id, "name": name, "address": home.address}

@app.put("/api/user/homes/{home_id}", tags=["user"])
async def update_home(home_id: int, home: HomeUpdate, request: Request):
    """Rename a home or update its address/coordinates."""
    user_info = get_current_user(request)
    _require_own_home(user_info['user_id'], home_id)
    changes = {k: v for k, v in home.model_dump().items() if v is not None}
    if "name" in changes and not changes["name"].strip():
        raise HTTPException(status_code=400, detail="name cannot be empty")
    if changes:
        with db_lock, sqlite3.connect(DB_PATH) as conn:
            conn.execute(
                f"UPDATE homes SET {', '.join(f'{k} = ?' for k in changes)} WHERE id = ?",
                (*changes.values(), home_id))
            conn.commit()
    return {"message": "Home updated", "id": home_id}

@app.delete("/api/user/homes/{home_id}", tags=["user"])
async def delete_home(home_id: int, request: Request):
    """Delete a home. Refused while devices are attached or for the last home."""
    user_info = get_current_user(request)
    _require_own_home(user_info['user_id'], home_id)
    if len(get_user_homes(user_info['user_id'])) <= 1:
        raise HTTPException(status_code=400, detail="Cannot delete your last home")
    with db_lock, sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT COUNT(*) FROM devices WHERE home_id = ?', (home_id,))
        if cursor.fetchone()[0]:
            raise HTTPException(status_code=400, detail="Move the home's devices first")
        cursor.execute('DELETE FROM home_settings WHERE home_id = ?', (home_id,))
        cursor.execute('DELETE FROM homes WHERE id = ?', (home_id,))
        conn.commit()
    return {"message": "Home deleted"}

@app.put("/api/user/devices/{device_db_id}/home", tags=["user"])
async def assign_device_home(device_db_id: int, assign: DeviceHomeAssign, request: Request):
    """Move one of your claimed devices to one of your homes."""
    user_info = get_current_user(request)
    _require_own_home(user_info['user_id'], assign.home_id)
    with db_lock, sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT 1 FROM user_devices WHERE device_id = ? AND user_id = ?',
                       (device_db_id, user_info['user_id']))
        if not cursor.fetchone():
            raise HTTPException(status_code=404, detail="Device not found")
        cursor.execute('UPDATE devices SET home_id = ? WHERE id = ?', (assign.home_id, device_db_id))
        conn.commit()
    return {"message": "Device moved", "home_id": assign.home_id}

# --- Personal API tokens (Home Assistant & other integrations) ---------------
# Managed from the dashboard (Authelia-protected /api/user path). The tokens
# themselves are used against the public /api/ha/* endpoints below, which the
# edge does not gate — integrations cannot follow an Authelia login redirect.

@app.get("/api/user/tokens", tags=["user"])
async def list_user_tokens(request: Request):
    """List the authenticated user's personal API tokens (no secrets)."""
    user_info = get_current_user(request)
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute('''
            SELECT id, token_name, created_at, expires_at, last_used_at
            FROM api_tokens
            WHERE user_id = ? AND is_active = TRUE
            ORDER BY created_at DESC
        ''', (user_info['user_id'],))
        tokens = [{
            "id": row[0], "token_name": row[1], "created_at": row[2],
            "expires_at": row[3], "last_used_at": row[4],
        } for row in cursor.fetchall()]
    return {"tokens": tokens}

@app.post("/api/user/tokens", tags=["user"])
async def create_user_token_endpoint(token_data: UserTokenCreate, request: Request):
    """
    Create a personal API token for integrations like Home Assistant.

    The token is returned once and never stored in plain text. It
    authenticates as you (never as admin) against /api/ha/* endpoints.
    """
    user_info = get_current_user(request)
    if user_info['auth_method'] == 'bearer_token':
        raise HTTPException(status_code=403, detail="Tokens cannot create other tokens")
    name = token_data.token_name.strip() or "Home Assistant"
    token, token_id = create_user_api_token(user_info['user_id'], name, token_data.expires_days)
    logger.info(f"User {user_info['user_id']} created personal token '{name}'")
    return {"id": token_id, "token_name": name, "token": token}

@app.delete("/api/user/tokens/{token_id}", tags=["user"])
async def revoke_user_token_endpoint(token_id: int, request: Request):
    """Revoke one of the authenticated user's personal tokens."""
    user_info = get_current_user(request)
    with db_lock, sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute('''
            UPDATE api_tokens SET is_active = FALSE
            WHERE id = ? AND user_id = ?
        ''', (token_id, user_info['user_id']))
        conn.commit()
        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail="Token not found")
    return {"message": "Token revoked"}

# --- Home Assistant endpoints (public path, bearer-token auth) ----------------

def _require_token_user(request: Request) -> Dict[str, Any]:
    """Authenticate a personal (user-bound) bearer token."""
    user_info = get_current_user(request)
    if user_info['user_id'] == 'system':
        raise HTTPException(status_code=403, detail="A personal API token is required")
    return user_info

@app.get("/api/ha/me", tags=["user"])
async def ha_me(request: Request):
    """
    Validate a personal API token (used by the Home Assistant config flow).

    Authentication: Bearer token created via /api/user/tokens (dashboard).
    """
    user_info = _require_token_user(request)
    return {"user_id": user_info['user_id']}

@app.get("/api/ha/devices", tags=["user"])
async def ha_devices(request: Request):
    """
    List the token owner's claimed pebbles (Home Assistant device picker).

    Authentication: Bearer token created via /api/user/tokens (dashboard).
    Poll colors via the public /api/color-code with the X-Device-ID header.
    """
    user_info = _require_token_user(request)
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute('''
            SELECT d.device_id, ud.nickname, d.last_seen
            FROM devices d
            JOIN user_devices ud ON d.id = ud.device_id
            WHERE ud.user_id = ? AND d.device_id IS NOT NULL
            ORDER BY d.last_seen DESC
        ''', (user_info['user_id'],))
        devices = [{
            "device_id": row[0],
            "nickname": row[1] or row[0],
            "last_seen": row[2],
        } for row in cursor.fetchall()]
    return {"user_id": user_info['user_id'], "devices": devices}

@app.get("/api/diagnostic", tags=["public"])
async def get_diagnostic(date: Optional[str] = None):
    """
    Diagnostic endpoint to check data availability and system status.
    
    Authentication: None required - public endpoint.
    
    Optional query parameters:
    - date: Specific date in YYYY-MM-DD format (defaults to today)
    
    Returns diagnostic information including data availability, API status,
    and system health metrics for troubleshooting and monitoring.
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
    target_devices: str = Form(None),
    sha256_checksum: str = Form(None),
    md5_checksum: str = Form(None),
    signature: str = Form(None)
):
    """
    Upload a new firmware binary file.
    Requires admin authentication. Designed for use by GitHub Actions.
    
    Parameters:
    - firmware_file: The firmware binary (.bin file)
    - version: Version in semantic versioning format (e.g., "v1.2.0", "1.2.0") - 'v' prefix will be added if missing
    - product_name: Product name (default: "energy_pebble")  
    - variant: Build variant (default: "release")
    - is_stable: Whether this is a stable release (default: true)
    - force_update: Whether to force device updates (default: false)
    - min_version: Minimum version required for update in same format as version (optional)
    - rollback_version: Version to rollback to if update fails in same format as version (optional)
    - release_notes: Release notes for this version (optional)
    - target_devices: JSON array of target ESP32 eFuse MAC addresses (optional, e.g., '["904fb0453ab4"]')
    - sha256_checksum: Optional expected SHA256 (verified against the server-computed
      value; upload is rejected on mismatch). The stored checksum is ALWAYS the one
      the server computes from the received bytes, never the supplied value.
    - md5_checksum: Optional expected MD5 (verified the same way).
    - signature: Base64 Ed25519 signature over the firmware bytes, produced offline
      with the release signing key (see firmware_signing.py). Required when the
      server has a public key configured (FIRMWARE_SIGNING_PUBKEY); verified before
      the upload is accepted so a compromised admin cannot publish unsigned firmware.

    Integrity is established server-side: checksums are recomputed from the stored
    file and (when a key is configured) the signature is cryptographically verified.
    """
    try:
        # Check authentication and admin privileges
        user_info = get_current_user(request)
        user_id = user_info['user_id']
        if not user_info['is_admin']:
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

        # Compute checksums server-side from the bytes we actually stored. Never
        # trust an uploader-supplied hash — that provides no integrity against an
        # attacker who controls the upload (security finding C3).
        checksum, computed_md5 = calculate_file_checksums(firmware_path)

        # If the uploader supplied expected values, they are treated as an
        # integrity assertion to verify, not as the source of truth.
        if sha256_checksum and sha256_checksum.strip():
            expected = sha256_checksum.strip()
            if not expected.startswith("sha256:"):
                expected = f"sha256:{expected}"
            if expected.lower() != checksum.lower():
                raise HTTPException(
                    status_code=400,
                    detail=(
                        "SHA256 mismatch: uploaded file does not match the supplied "
                        f"checksum (supplied {expected}, computed {checksum})"
                    ),
                )
        if md5_checksum and md5_checksum.strip():
            if md5_checksum.strip().lower() != computed_md5.lower():
                raise HTTPException(
                    status_code=400,
                    detail="MD5 mismatch: uploaded file does not match the supplied checksum",
                )
        md5_checksum = computed_md5

        # Verify the offline signature over the stored bytes. When a public key is
        # configured this is mandatory: it is the control that survives an admin
        # compromise, since a valid signature requires the offline private key.
        server_pubkey = firmware_signing.load_server_public_key()
        signature_alg = None
        if server_pubkey is not None:
            if not signature or not signature.strip():
                raise HTTPException(
                    status_code=400,
                    detail="Firmware signature is required (server has signing enabled)",
                )
            if not firmware_signing.verify_file(server_pubkey, firmware_path, signature.strip()):
                raise HTTPException(
                    status_code=400,
                    detail="Invalid firmware signature — rejected",
                )
            signature = signature.strip()
            signature_alg = firmware_signing.SIGNATURE_ALG
            logger.info(f"Verified Ed25519 signature for {version}")
        else:
            if signature and signature.strip():
                signature = signature.strip()
                signature_alg = firmware_signing.SIGNATURE_ALG
                logger.warning(
                    "Storing firmware signature but no %s configured — signature is "
                    "NOT verified. Configure the public key to enforce signing.",
                    firmware_signing.PUBKEY_ENV,
                )
            else:
                signature = None
                logger.warning(
                    "Firmware %s uploaded WITHOUT a signature and no %s is configured. "
                    "Firmware signing is not enforced on this deployment.",
                    version, firmware_signing.PUBKEY_ENV,
                )

        file_size = firmware_path.stat().st_size
        
        # Insert into database
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO firmware_versions
                (version, filename, checksum, md5_checksum, file_size, is_stable, force_update,
                 min_version, rollback_version, release_notes, target_devices, created_by,
                 signature, signature_alg)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (version, filename, checksum, md5_checksum, file_size, is_stable, force_update,
                  min_version, rollback_version, release_notes, target_devices, user_id,
                  signature, signature_alg))
            
            firmware_id = cursor.lastrowid
            conn.commit()
        
        logger.info(f"Firmware {version} uploaded successfully by {user_id}")
        
        return {
            "id": firmware_id,
            "version": version,
            "filename": filename,
            "checksum": checksum,
            "md5_checksum": md5_checksum,
            "file_size": file_size,
            "signed": signature is not None,
            "signature_verified": signature_alg is not None and server_pubkey is not None,
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
    List all firmware versions with detailed information.
    
    Authentication: Requires admin privileges via Authelia.
    
    Returns all firmware entries with version info, stability status, file details,
    and metadata for administrative management.
    """
    try:
        user_info = get_current_user(request)
        user_id = user_info['user_id']
        if not user_info['is_admin']:
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
    
    Authentication: Requires admin privileges via Authelia.
    
    Path parameters:
    - version: Firmware version to delete (e.g., 'v1.2.0')
    
    Permanently removes the firmware version from database and deletes the
    associated binary file from the filesystem. This action cannot be undone.
    """
    try:
        user_info = get_current_user(request)
        user_id = user_info['user_id']
        if not user_info['is_admin']:
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
    Get comprehensive OTA update statistics and metrics.
    
    Authentication: Requires admin privileges via Authelia.
    
    Returns detailed analytics including total checks, success rates, version
    distribution, device activity, and update performance metrics for
    administrative monitoring and insights.
    """
    try:
        user_info = get_current_user(request)
        user_id = user_info['user_id']
        if not user_info['is_admin']:
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

@app.get("/api/ota/check", tags=["ota"])
async def check_ota_updates(request: Request):
    """
    Check for available OTA updates for a device.
    Called by devices every 12 hours to check for firmware updates.
    
    Required headers:
    - X-Device-ID: ESP32 eFuse MAC address (12-character hex string, e.g., '904fb0453ab4')
    - X-Current-Version: Current firmware version in semantic versioning format (e.g., 'v1.2.0', '1.2.0')
    
    Device ID Format:
    The device ID should be the ESP32's eFuse MAC address, which is a unique 12-character 
    hexadecimal string burned into each chip during manufacturing. This is different from 
    the WiFi MAC address and provides a more stable device identifier.
    
    Version Format:
    Versions should follow semantic versioning (MAJOR.MINOR.PATCH) with optional 'v' prefix.
    Examples: 'v1.0.0', '1.2.3', 'v2.1.0'. The system will normalize versions by adding 
    the 'v' prefix if missing.
    """
    try:
        # Extract device info from headers
        device_id = request.headers.get("x-device-id")
        current_version = request.headers.get("x-current-version")
        
        if not device_id:
            raise HTTPException(status_code=400, detail="X-Device-ID header is required")
        if not current_version:
            raise HTTPException(status_code=400, detail="X-Current-Version header is required")
        
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
                "md5_checksum": latest_firmware['md5_checksum'],
                "signature": latest_firmware['signature'],
                "signature_alg": latest_firmware['signature_alg'],
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
    
    Path parameters:
    - device_id: ESP32 eFuse MAC address (12-character hex string, e.g., '904fb0453ab4')
    
    Request body should contain OTAStatusReport with installation status and details.
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
    
    Authentication: None required - public endpoint.
    
    Returns the most recent stable firmware release with version info, checksums,
    file size, and release metadata. Used for displaying current stable version
    information to users and for reference purposes.
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
                    md5_checksum,
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
            
            version, filename, checksum, md5_checksum, file_size, release_date, release_notes = result
            
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
                "algorithm": "sha256",
                "md5_checksum": md5_checksum or ""
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
        user_info = get_current_user(request)
        user_id = user_info['user_id']
        if not user_info['is_admin']:
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
        user_info = get_current_user(request)
        user_id = user_info['user_id']
        if not user_info['is_admin']:
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
        user_info = get_current_user(request)
        user_id = user_info['user_id']
        if not user_info['is_admin']:
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
async def set_device_nickname(device_id: int, nickname_data: DeviceNicknameUpdate, request: Request):
    """
    Set or update a device nickname/location note.
    Creates a user_devices entry if it doesn't exist.
    """
    try:
        # Check authentication and admin privileges
        user_info = get_current_user(request)
        user_id = user_info['user_id']
        if not user_info['is_admin']:
            raise HTTPException(status_code=403, detail="Admin access required")
        
        # Validate nickname
        nickname = nickname_data.nickname
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
        user_info = get_current_user(request)
        user_id = user_info['user_id']
        if not user_info['is_admin']:
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
async def claim_device_for_user(device_id: int, claim_data: DeviceClaimRequest, request: Request):
    """
    Claim a device for a specific user (admin only).
    """
    try:
        # Check authentication and admin privileges
        admin_user_info = get_current_user(request)
        admin_user = admin_user_info['user_id']
        if not admin_user_info['is_admin']:
            raise HTTPException(status_code=403, detail="Admin access required")
        
        # Validate user parameter
        user = claim_data.user
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

@app.post("/api/admin/devices/{device_id}/secret", tags=["admin"])
async def mint_device_secret(device_id: str, request: Request):
    """
    Mint (or replace) the claim secret for a device and return the QR-sticker
    payload. Admin only; used at manufacturing/sticker-printing time.

    The plaintext secret is returned ONCE - only its hash is stored. Minting
    again invalidates the previous sticker.
    """
    admin_info = get_current_user(request)
    if not admin_info['is_admin']:
        raise HTTPException(status_code=403, detail="Admin access required")

    device_id = (device_id or "").strip().lower()
    if not re.fullmatch(r"[0-9a-f]{12}", device_id):
        raise HTTPException(status_code=400,
                            detail="device_id must be 12 hex characters")

    secret = secrets.token_urlsafe(9)  # 12 chars, fits a small QR + sticker
    try:
        with db_lock:
            with sqlite3.connect(DB_PATH) as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    INSERT INTO device_secrets (device_id, secret_hash, created_by)
                    VALUES (?, ?, ?)
                    ON CONFLICT(device_id) DO UPDATE SET
                        secret_hash = excluded.secret_hash,
                        created_at = CURRENT_TIMESTAMP,
                        created_by = excluded.created_by
                ''', (device_id, hash_token(secret), admin_info['user_id']))
                conn.commit()

        logger.info(f"Admin {admin_info['user_id']} minted claim secret for device {device_id}")
        return {
            "device_id": device_id,
            "secret": secret,
            "qr_url": f"https://energypebble.tdlx.nl/setup/?d={device_id}&s={secret}",
        }
    except Exception as e:
        logger.error(f"Error minting secret for device {device_id}: {e}")
        raise HTTPException(status_code=500, detail="Error minting device secret")

@app.get("/api/admin/users/management", tags=["admin"])
async def get_user_management_data(request: Request):
    """
    Get comprehensive user management data including roles, devices, and activity.
    """
    try:
        # Check authentication and admin privileges
        user_info = get_current_user(request)
        user_id = user_info['user_id']
        if not user_info['is_admin']:
            raise HTTPException(status_code=403, detail="Admin access required")
        
        # Read users from Authelia configuration
        authelia_users_path = Path("authelia/config/users.yml")
        if not authelia_users_path.exists():
            raise HTTPException(status_code=500, detail="Authelia configuration not found")
        
        try:
            with open(authelia_users_path, 'r') as f:
                authelia_config = yaml.safe_load(f)
                users_config = authelia_config.get('users', {})
                
                users_data = []
                for username, user_info in users_config.items():
                    # Determine role based on groups
                    groups = user_info.get('groups', [])
                    role = "admin" if "admins" in groups else "user"
                    
                    users_data.append({
                        "username": username,
                        "display_name": user_info.get('displayname', username),
                        "role": role,
                        "email": user_info.get('email', ''),
                        "groups": groups
                    })
        except yaml.YAMLError as e:
            raise HTTPException(status_code=500, detail=f"Error parsing Authelia configuration: {str(e)}")
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Error reading user configuration: {str(e)}")
        
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

# API Token Management Endpoints
@app.get("/api/admin/tokens", tags=["admin"])
async def get_api_tokens(request: Request, user_info = Depends(get_admin_user)):
    """Get all API tokens for admin dashboard"""
    try:
        tokens = get_all_api_tokens()
        return {"tokens": tokens, "total": len(tokens)}
    except Exception as e:
        logger.error(f"Error getting API tokens: {e}")
        raise HTTPException(status_code=500, detail=f"Error getting API tokens: {str(e)}")

@app.post("/api/admin/tokens", tags=["admin"])
async def create_api_token_endpoint(
    request: Request,
    token_data: TokenCreate,
    user_info = Depends(get_admin_user)
):
    """Create a new API token"""
    try:
        # Get creator info
        created_by = user_info['user_id']
        if user_info['auth_method'] == 'bearer_token':
            created_by = f"token:{user_info['token_name']}"
        
        # Create the token
        token, token_id = create_api_token(
            token_name=token_data.token_name,
            created_by=created_by,
            expires_days=token_data.expires_days
        )
        
        return {
            "token": token,
            "token_id": token_id,
            "message": "Token created successfully. Save this token securely - it will not be shown again."
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating API token: {e}")
        raise HTTPException(status_code=500, detail=f"Error creating API token: {str(e)}")

@app.delete("/api/admin/tokens/{token_id}", tags=["admin"])
async def revoke_api_token_endpoint(
    request: Request,
    token_id: int,
    user_info = Depends(get_admin_user)
):
    """Revoke an API token"""
    try:
        success = revoke_api_token(token_id)
        if success:
            return {"message": "Token revoked successfully"}
        else:
            raise HTTPException(status_code=404, detail="Token not found")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error revoking API token: {e}")
        raise HTTPException(status_code=500, detail=f"Error revoking API token: {str(e)}")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)