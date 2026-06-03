#!/usr/bin/env python3
"""
Update firmware database with real firmware file info
"""

import sqlite3
import hashlib
from pathlib import Path

def calculate_checksum(file_path):
    """Calculate SHA256 checksum"""
    sha256_hash = hashlib.sha256()
    with open(file_path, 'rb') as f:
        for chunk in iter(lambda: f.read(4096), b''):
            sha256_hash.update(chunk)
    return f'sha256:{sha256_hash.hexdigest()}'

def main():
    firmware_path = Path('/home/cumulus/github/energy_pebble/firmware/energy_dot_v1.0.0.bin')
    db_path = '/tmp/energy_pebble.db'
    
    if not firmware_path.exists():
        print(f'❌ Firmware file not found: {firmware_path}')
        return
    
    # Calculate file properties
    file_size = firmware_path.stat().st_size
    checksum = calculate_checksum(firmware_path)
    
    print(f'Real firmware file info:')
    print(f'  File: {firmware_path.name}')
    print(f'  Size: {file_size} bytes')
    print(f'  Checksum: {checksum}')
    
    try:
        with sqlite3.connect(db_path) as conn:
            cursor = conn.cursor()
            
            # Check current entry
            cursor.execute('SELECT filename, file_size, checksum FROM firmware_versions WHERE version = ?', ('v1.0.0',))
            current = cursor.fetchone()
            
            if current:
                print(f'\nCurrent database entry:')
                print(f'  File: {current[0]}')
                print(f'  Size: {current[1]} bytes')
                print(f'  Checksum: {current[2]}')
                
                # Update with real file info
                cursor.execute('''
                    UPDATE firmware_versions 
                    SET filename = ?, checksum = ?, file_size = ?, 
                        release_notes = ?
                    WHERE version = ?
                ''', (
                    'energy_dot_v1.0.0.bin',
                    checksum,
                    file_size,
                    'Real Energy Dot firmware v1.0.0 - production release',
                    'v1.0.0'
                ))
                
                conn.commit()
                print(f'\n✅ Successfully updated database entry for v1.0.0')
            else:
                print('❌ v1.0.0 entry not found in database')
                
    except Exception as e:
        print(f'❌ Database error: {e}')

if __name__ == '__main__':
    main()