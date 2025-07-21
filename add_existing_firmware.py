#!/usr/bin/env python3
"""
Add existing firmware files to the database
"""

import sqlite3
import hashlib
import re
from pathlib import Path
from datetime import datetime

def calculate_file_checksum(file_path: Path) -> str:
    """Calculate SHA256 checksum of a file"""
    sha256_hash = hashlib.sha256()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(4096), b""):
            sha256_hash.update(chunk)
    return f"sha256:{sha256_hash.hexdigest()}"

def parse_firmware_filename(filename: str) -> dict:
    """Parse firmware filename to extract metadata"""
    # Remove .bin extension
    name_without_ext = filename.replace('.bin', '')
    
    # Pattern: product_version_variant or product_version
    # Examples: energy_dot_v1.0.0, energy_pebble_v1.2.3_beta
    
    parts = name_without_ext.split('_')
    
    if len(parts) < 3:
        raise ValueError(f"Invalid firmware filename format: {filename}")
    
    # Find version part (starts with 'v' and contains dots)
    version_idx = None
    for i, part in enumerate(parts):
        if re.match(r'^v?\d+\.\d+\.\d+', part):
            version_idx = i
            break
    
    if version_idx is None:
        raise ValueError(f"Version not found in filename: {filename}")
    
    # Extract product name (everything before version)
    product_name = '_'.join(parts[:version_idx])
    
    # Extract version
    version = parts[version_idx]
    
    # Extract variant (everything after version, if any)
    variant = '_'.join(parts[version_idx + 1:]) if len(parts) > version_idx + 1 else 'release'
    
    return {
        'product_name': product_name,
        'version': version,
        'variant': variant,
        'filename': filename
    }

def add_firmware_to_db(firmware_path: Path, db_path: str = "data/energy_pebble.db"):
    """Add a firmware file to the database"""
    
    # Parse filename
    try:
        firmware_info = parse_firmware_filename(firmware_path.name)
        print(f"Parsed firmware info: {firmware_info}")
    except ValueError as e:
        print(f"Error parsing filename: {e}")
        return False
    
    # Calculate file properties
    file_size = firmware_path.stat().st_size
    checksum = calculate_file_checksum(firmware_path)
    
    print(f"File size: {file_size} bytes")
    print(f"Checksum: {checksum}")
    
    # Check if SHA256 file exists and verify
    sha256_file = firmware_path.with_suffix(firmware_path.suffix + '.sha256')
    if sha256_file.exists():
        with open(sha256_file, 'r') as f:
            external_checksum = f.read().strip().split()[0]
        
        calculated_hash = checksum.replace('sha256:', '')
        if calculated_hash == external_checksum:
            print("✅ Checksum verified against .sha256 file")
        else:
            print(f"⚠️  Checksum mismatch! File: {external_checksum}, Calculated: {calculated_hash}")
    
    # Add to database
    try:
        with sqlite3.connect(db_path) as conn:
            cursor = conn.cursor()
            
            # Check if version already exists
            cursor.execute('SELECT id FROM firmware_versions WHERE version = ?', (firmware_info['version'],))
            if cursor.fetchone():
                print(f"⚠️  Firmware version {firmware_info['version']} already exists in database")
                return False
            
            # Insert firmware version
            cursor.execute('''
                INSERT INTO firmware_versions 
                (version, filename, checksum, file_size, is_stable, force_update, 
                 release_notes, created_by)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                firmware_info['version'],
                firmware_info['filename'],
                checksum,
                file_size,
                True,  # is_stable
                False,  # force_update
                f"Added {firmware_info['product_name']} {firmware_info['variant']} firmware from existing file",  # release_notes
                "admin"  # created_by
            ))
            
            firmware_id = cursor.lastrowid
            conn.commit()
            
            print(f"✅ Successfully added firmware to database with ID: {firmware_id}")
            return True
            
    except Exception as e:
        print(f"❌ Database error: {e}")
        return False

def main():
    print("=== Adding Existing Firmware to Database ===")
    
    firmware_dir = Path("firmware")
    
    if not firmware_dir.exists():
        print(f"❌ Firmware directory not found: {firmware_dir}")
        return
    
    # Find all .bin files
    bin_files = list(firmware_dir.glob("*.bin"))
    
    if not bin_files:
        print("❌ No .bin files found in firmware directory")
        return
    
    print(f"Found {len(bin_files)} firmware file(s):")
    for bin_file in bin_files:
        print(f"  - {bin_file.name}")
    
    print("\nProcessing firmware files...")
    
    success_count = 0
    for bin_file in bin_files:
        print(f"\n--- Processing {bin_file.name} ---")
        if add_firmware_to_db(bin_file):
            success_count += 1
    
    print(f"\n=== Complete: {success_count}/{len(bin_files)} firmware files added ===")

if __name__ == "__main__":
    main()