#!/usr/bin/env python3
"""
Test what the /docs endpoint should show
"""

# Simulate the key parts of the OpenAPI schema that affect the Authorize button
openapi_simulation = {
    "openapi": "3.0.2",
    "info": {
        "title": "Electricity Price API",
        "version": "1.0.0"
    },
    "components": {
        "securitySchemes": {
            "bearerAuth": {
                "type": "http",
                "scheme": "bearer",
                "bearerFormat": "Token",
                "description": "Enter your username (e.g., 'thomas') or encoded token"
            }
        }
    },
    "paths": {
        "/api/devices/{device_id}/claim": {
            "post": {
                "tags": ["devices"],
                "summary": "Claim Device",
                "security": [{"bearerAuth": []}],
                "parameters": [
                    {
                        "name": "device_id",
                        "in": "path",
                        "required": True,
                        "schema": {"type": "integer"}
                    }
                ]
            }
        },
        "/api/user/devices": {
            "get": {
                "tags": ["user"],
                "summary": "Get User Devices", 
                "security": [{"bearerAuth": []}]
            }
        },
        "/api/devices": {
            "get": {
                "tags": ["devices"],
                "summary": "Get Detected Devices"
                # No security - public endpoint
            }
        }
    }
}

print("🔍 OpenAPI Schema Analysis for Authorization Button")
print("=" * 60)

# Check 1: Security schemes exist
has_security_schemes = (
    "components" in openapi_simulation and 
    "securitySchemes" in openapi_simulation["components"]
)
print(f"1. Security schemes defined: {'✅' if has_security_schemes else '❌'}")

if has_security_schemes:
    schemes = openapi_simulation["components"]["securitySchemes"] 
    for name, config in schemes.items():
        print(f"   - {name}: {config['type']} {config['scheme']}")

# Check 2: Protected endpoints exist
protected_endpoints = []
for path, methods in openapi_simulation["paths"].items():
    for method, details in methods.items():
        if "security" in details:
            protected_endpoints.append(f"{method.upper()} {path}")

print(f"\n2. Protected endpoints: {'✅' if protected_endpoints else '❌'}")
for endpoint in protected_endpoints:
    print(f"   - {endpoint}")

# Check 3: Will authorization button appear?
will_show_auth = has_security_schemes and len(protected_endpoints) > 0
print(f"\n3. Authorization button will appear: {'✅' if will_show_auth else '❌'}")

if will_show_auth:
    print("\n🎉 The 'Authorize' button SHOULD appear in the FastAPI docs!")
    print("   - Click the 'Authorize' button")
    print("   - Enter 'thomas' in the value field")
    print("   - Click 'Authorize' to save")
    print("   - Try the protected endpoints")
else:
    print("\n❌ The 'Authorize' button will NOT appear")
    print("   Possible issues:")
    if not has_security_schemes:
        print("   - No security schemes defined")
    if not protected_endpoints:
        print("   - No endpoints use authentication")

print(f"\n📋 Summary:")
print(f"   - Security schemes: {len(openapi_simulation['components']['securitySchemes']) if has_security_schemes else 0}")
print(f"   - Protected endpoints: {len(protected_endpoints)}")
print(f"   - Total endpoints: {sum(len(methods) for methods in openapi_simulation['paths'].values())}")