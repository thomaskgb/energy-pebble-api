#!/usr/bin/env python3
"""
Minimal test case to verify FastAPI authentication setup
Run this if you have FastAPI available to test the authorization button
"""

try:
    from fastapi import FastAPI, Depends, HTTPException
    from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
    from fastapi.openapi.utils import get_openapi
    
    app = FastAPI(title="Test API")
    security = HTTPBearer()
    
    def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)):
        # Simple auth - just return the token as username
        return credentials.credentials
    
    @app.get("/public")
    async def public_endpoint():
        return {"message": "This is public"}
    
    @app.get("/protected")
    async def protected_endpoint(current_user: str = Depends(get_current_user)):
        return {"message": f"Hello {current_user}!", "authenticated": True}
    
    def custom_openapi():
        if app.openapi_schema:
            return app.openapi_schema
        
        openapi_schema = get_openapi(
            title=app.title,
            version="1.0.0",
            routes=app.routes,
        )
        
        # Add security scheme
        if "components" not in openapi_schema:
            openapi_schema["components"] = {}
        
        openapi_schema["components"]["securitySchemes"] = {
            "bearerAuth": {
                "type": "http",
                "scheme": "bearer",
                "description": "Enter your username as token"
            }
        }
        
        # Add security to protected endpoint
        if "/protected" in openapi_schema["paths"] and "get" in openapi_schema["paths"]["/protected"]:
            openapi_schema["paths"]["/protected"]["get"]["security"] = [{"bearerAuth": []}]
        
        app.openapi_schema = openapi_schema
        return app.openapi_schema
    
    app.openapi = custom_openapi
    
    if __name__ == "__main__":
        import uvicorn
        print("🚀 Starting test server...")
        print("📖 Open http://localhost:8002/docs to test authorization")
        print("🔑 Use 'thomas' as the Bearer token")
        uvicorn.run(app, host="127.0.0.1", port=8002, log_level="info")
        
except ImportError:
    print("❌ FastAPI not available")
    print("This is a test script that would verify the authorization button works")
    print("The main application should have the same configuration")
    
except Exception as e:
    print(f"❌ Error: {e}")