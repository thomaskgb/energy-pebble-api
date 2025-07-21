# Energy Pebble Test Suite

This directory contains various test scripts for validating Energy Pebble functionality.

## Test Files

### Authentication & API Tests
- **`test_auth_flow.py`** - Tests authentication flow with Authelia headers simulation
- **`test_dashboard_api.py`** - Tests dashboard API endpoints with mock authentication
- **`test_dashboard_complete.py`** - Comprehensive dashboard functionality testing
- **`test_dashboard_flow.py`** - End-to-end dashboard workflow testing
- **`test_minimal_auth.py`** - Minimal FastAPI authentication setup test

### Device & Hardware Tests
- **`test_device_detection.py`** - Tests Energy Dot device detection and registration
- **`test_firmware_docker.py`** - Tests firmware management in Docker environment
- **`test_firmware_management.py`** - Tests firmware upload and management features

### Documentation Tests
- **`test_docs.py`** - Tests OpenAPI documentation generation and display
- **`test_openapi.py`** - Validates OpenAPI schema configuration

## Running Tests

### Individual Tests
```bash
# Run authentication tests
python3 tests/test_auth_flow.py

# Test device detection
python3 tests/test_device_detection.py

# Test dashboard APIs
python3 tests/test_dashboard_api.py
```

### Prerequisites
- Docker containers should be running for integration tests
- Authelia should be configured and accessible
- Energy Pebble API should be running on localhost:8000

## Test Categories

### Unit Tests
Tests individual components and functions in isolation.

### Integration Tests
Tests interaction between components, API endpoints, and authentication.

### System Tests
Tests complete workflows and user scenarios.

## Notes
- Most tests simulate Authelia authentication headers for testing protected endpoints
- Some tests require the full Docker environment to be running
- Tests are designed to be run during development and CI/CD processes