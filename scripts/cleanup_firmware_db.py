#!/usr/bin/env python3
"""
Clean up firmware database by removing entries without corresponding files
"""

import requests
import json

def cleanup_firmware_db():
    """Remove firmware entries that don't have corresponding files"""
    print("=== Cleaning up firmware database ===")
    
    headers = {'Authorization': 'Bearer thomas'}
    
    try:
        # Get all firmware versions
        response = requests.get('http://localhost:8000/api/firmware/versions', headers=headers)
        
        if response.status_code != 200:
            print(f"❌ Failed to get firmware versions: {response.status_code}")
            return
        
        versions = response.json()['versions']
        print(f"Found {len(versions)} firmware versions in database:")
        
        for version in versions:
            print(f"  - {version['version']}: {version['filename']} ({version['file_size']} bytes)")
        
        # Check which files actually exist by trying to download them
        print("\nChecking which firmware files exist...")
        to_delete = []
        
        for version in versions:
            filename = version['filename']
            download_url = f"http://localhost:8000/firmware/{filename}"
            
            try:
                response = requests.head(download_url)  # HEAD request to check existence
                if response.status_code == 404:
                    print(f"❌ File missing: {filename}")
                    to_delete.append(version['version'])
                elif response.status_code == 200:
                    print(f"✅ File exists: {filename}")
                else:
                    print(f"⚠️  Unexpected status for {filename}: {response.status_code}")
            except Exception as e:
                print(f"❌ Error checking {filename}: {e}")
                to_delete.append(version['version'])
        
        # Delete missing firmware entries
        if to_delete:
            print(f"\nDeleting {len(to_delete)} firmware entries without files...")
            
            for version_to_delete in to_delete:
                try:
                    delete_url = f"http://localhost:8000/api/firmware/versions/{version_to_delete}"
                    response = requests.delete(delete_url, headers=headers)
                    
                    if response.status_code == 200:
                        print(f"✅ Deleted: {version_to_delete}")
                    else:
                        print(f"❌ Failed to delete {version_to_delete}: {response.status_code}")
                        
                except Exception as e:
                    print(f"❌ Error deleting {version_to_delete}: {e}")
        else:
            print("\n✅ No cleanup needed - all firmware entries have corresponding files")
        
        # Show final state
        print("\n=== Final firmware list ===")
        response = requests.get('http://localhost:8000/api/firmware/versions', headers=headers)
        if response.status_code == 200:
            final_versions = response.json()['versions']
            print(f"Remaining firmware versions: {len(final_versions)}")
            for version in final_versions:
                print(f"  - {version['version']}: {version['filename']}")
        
    except Exception as e:
        print(f"❌ Cleanup failed: {e}")

if __name__ == "__main__":
    cleanup_firmware_db()