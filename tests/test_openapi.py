#!/usr/bin/env python3
"""
Test script to verify OpenAPI schema configuration
"""

import json
import sys
import os

# Add current directory to path so we can import main
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    from main import app
    
    print("🔍 Testing OpenAPI schema configuration...")
    
    # Get the OpenAPI schema
    schema = app.openapi()
    
    # Check if security schemes are present
    print("\n1. Security Schemes:")
    if 'components' in schema and 'securitySchemes' in schema['components']:
        print("✅ Security schemes found:")
        schemes = schema['components']['securitySchemes']
        for name, config in schemes.items():
            print(f"   - {name}: {config['type']} {config['scheme']}")
    else:
        print("❌ No security schemes found")
    
    # Check protected endpoints
    print("\n2. Protected Endpoints:")
    protected_found = False
    for path, methods in schema['paths'].items():
        for method, details in methods.items():
            if 'security' in details:
                protected_found = True
                print(f"✅ {method.upper()} {path}")
                print(f"   Security: {details['security']}")
    
    if not protected_found:
        print("❌ No protected endpoints found")
    
    # Check if authorization will appear in docs
    print("\n3. Authorization Button Check:")
    has_security_schemes = 'components' in schema and 'securitySchemes' in schema['components']
    has_protected_endpoints = any(
        'security' in details 
        for methods in schema['paths'].values() 
        for details in methods.values()
    )
    
    if has_security_schemes and has_protected_endpoints:
        print("✅ Authorization button SHOULD appear in /docs")
    else:
        print("❌ Authorization button will NOT appear")
        print(f"   - Has security schemes: {has_security_schemes}")
        print(f"   - Has protected endpoints: {has_protected_endpoints}")
    
    # Save schema for inspection
    with open('/tmp/openapi_schema.json', 'w') as f:
        json.dump(schema, f, indent=2)
    print(f"\n📁 Full schema saved to: /tmp/openapi_schema.json")
    
except ImportError as e:
    print(f"❌ Cannot import FastAPI app: {e}")
    print("FastAPI is not installed in this environment")
except Exception as e:
    print(f"❌ Error testing schema: {e}")